"""Offline v0.4 tests: provenance, ANN invalidation, filtered retrieval, rerank."""
import json
import math
import sys
import types
from pathlib import Path
import pytest
from flipper_rag.ann import ANNIndex, ANNUnavailable
from flipper_rag.chunking import chunk_text
from flipper_rag.config import Settings
from flipper_rag.models import Embedder
from flipper_rag.retrieval import Retriever
from flipper_rag.reranking import LocalReranker, RerankerUnavailable
from flipper_rag.storage import Store, Document
from flipper_rag.versioning import normalize_version, channel_for_ref, firmware_source_for_ref, compatibility


class FixtureEmbedder(Embedder):
    def __init__(self, vector=None):
        super().__init__(Settings(embed_model='fixture'))
        self.vector = vector or [0.9, 0.1]
    @property
    def active(self):
        return True
    def embed(self, texts):
        return [self.vector for _ in texts]


def add(db, id, content, vector=None, source='official', version='', channel='unversioned', trust='official'):
    doc = Document(id, source, id, f'https://github.com/flipperdevices/example/blob/sha/{id}.md',
                   'firmware', content, revision='sha123', trust=trust,
                   firmware_version=version, firmware_channel=channel)
    db.upsert(doc, chunk_text(content), [vector] if vector else None, 'fixture')


@pytest.mark.parametrize('tag,expected', [('v1.5','1.5.0'),('1.5.1','1.5.1'),('1.5.1-rc','1.5.1-rc'),('1.10.0','1.10.0')])
def test_version_tag_parse(tag, expected):
    assert normalize_version(tag) == expected


@pytest.mark.parametrize('invalid',['dev','1.5.x','1.2.3; rm -rf /','1.2.3-foo','../../data',''])
def test_version_tag_rejects_unsafe_input(invalid):
    with pytest.raises(ValueError):
        normalize_version(invalid)


def test_upstream_firmware_tag_has_own_source_and_provenance():
    spec = {'id':'firmware-oficial','branch':'dev','url':'https://github.com/flipperdevices/flipperzero-firmware.git'}
    tagged = firmware_source_for_ref(spec, '1.5.1')
    assert tagged['id'] == 'firmware-oficial-v1_5_1'
    assert tagged['branch'] == '1.5.1'
    assert tagged['firmware_version'] == '1.5.1'
    assert tagged['firmware_channel'] == 'release'
    assert spec['branch'] == 'dev'
    assert channel_for_ref('dev') == 'dev'
    assert channel_for_ref('1.5.1-rc') == 'rc'
    with pytest.raises(ValueError):
        firmware_source_for_ref({'id':'community-fork'},'1.5.1')


def test_migration_preserves_rows_and_version_fields(tmp_path):
    db=Store(tmp_path/'v.sqlite')
    add(db,'manual','NFC Furi GPIO example')
    assert Store(db.path).get_chunks(['manual:0'])['manual:0']['firmware_version']==''
    with db.connect() as c:
        c.execute('UPDATE documents SET firmware_version=?,firmware_channel=? WHERE id=?',('1.5.1','release','manual'))
    assert Store(db.path).get_chunks(['manual:0'])['manual:0']['firmware_version']=='1.5.1'


def test_strict_version_filters_before_lexical_and_vector_search(tmp_path):
    db=Store(tmp_path/'v.sqlite')
    add(db,'v151','Furi versioned api support', [1,0], version='1.5.1',channel='release')
    add(db,'v140','Furi versioned api support', [0,1], version='1.4.0',channel='release')
    add(db,'dev','Furi versioned api support', [0,1],channel='dev')
    add(db,'manual','Furi versioned api support', [0,1],channel='unversioned')
    assert db.lexical('Furi versioned',firmware_version='1.5.1',version_policy='strict')==['v151:0']
    ids=[cid for cid,_ in db.iter_embeddings('fixture',firmware_version='1.5.1',version_policy='include-unversioned')]
    assert set(ids)=={'v151:0','manual:0'}
    r=Retriever(db,FixtureEmbedder())
    hits=r.search('Furi versioned',firmware_version='1.5.1',version_policy='strict')
    assert [item['id'] for item in hits['results']]==['v151:0']
    assert hits['results'][0]['compatibility']=='exact_snapshot'
    assert hits['semantic_backend']=='exact'
    mixed=r.search('Furi versioned',firmware_version='1.5.1')
    assert {x['compatibility'] for x in mixed['results']}=={'exact_snapshot','unverified'}
    assert set(x['id'] for x in mixed['results'])=={'v151:0','manual:0'}
    assert 'different_version'==compatibility('1.4.0','release','1.5.1').status


def test_epoch_changes_only_on_vector_content_mutation(tmp_path):
    db=Store(tmp_path/'v.sqlite')
    assert db.vector_epoch()==0
    add(db,'a','Versioned Furi GPIO', [1,0]); first=db.vector_epoch()
    assert first==1
    add(db,'a','Versioned Furi GPIO', [1,0]); assert db.vector_epoch()==first
    db.update_embeddings(['a:0'],[[0,1]],'fixture'); assert db.vector_epoch()==first+1
    db.prune_source('official',set()); assert db.vector_epoch()==first+2


def install_fake_usearch(monkeypatch):
    class FakeMatch:
        def __init__(self,key,distance):
            self.key, self.distance = key, distance
    class Index:
        def __init__(self, *, ndim, **kwargs):
            self.ndim=ndim
            self.content={}
        def add(self, keys, vectors):
            self.content={int(k):[float(x) for x in v] for k,v in zip(keys,vectors)}
        def search(self, vector, count):
            x=[float(v) for v in vector]
            def similarity(y):
                return sum(a*b for a,b in zip(x,y))/(math.sqrt(sum(a*a for a in x))*math.sqrt(sum(b*b for b in y)))
            return [FakeMatch(k,1-similarity(v)) for k,v in sorted(self.content.items(),key=lambda kv:-similarity(kv[1]))[:count]]
        def save(self, filename):
            Path(filename).write_text(json.dumps({'ndim':self.ndim,'content':self.content}))
        def load(self, filename):
            data=json.loads(Path(filename).read_text())
            if self.ndim!=data['ndim']:
                raise ValueError('dimension mismatch')
            self.content={int(k):v for k,v in data['content'].items()}
    parent=types.ModuleType('usearch')
    child=types.ModuleType('usearch.index')
    child.Index=Index
    monkeypatch.setitem(sys.modules,'usearch',parent)
    monkeypatch.setitem(sys.modules,'usearch.index',child)


def test_ann_persistence_staleness_and_fallback(tmp_path,monkeypatch):
    install_fake_usearch(monkeypatch)
    db=Store(tmp_path/'v.sqlite')
    add(db,'one','Furi app example', [1,0]);add(db,'two','GPIO chip data',[0,1])
    index=ANNIndex(db)
    assert index.status('fixture').state=='missing'
    result=index.build('fixture')
    assert result['indexed']==2
    assert index.status('fixture').state=='ready'
    assert index.search([1,0],'fixture')[0][0]=='one:0'
    assert ANNIndex(db).search([0,1],'fixture')[0][0]=='two:0'
    retriever=Retriever(db,FixtureEmbedder(),ann=index)
    result=retriever.search('Furi app',mode='semantic')
    assert result['semantic_backend']=='ann'
    assert result['results'][0]['id']=='one:0'
    db.update_embeddings(['one:0'],[[0.2,0.8]],'fixture')
    assert index.status('fixture').state=='stale'
    result=retriever.search('Furi app',mode='semantic')
    assert result['semantic_backend']=='exact'
    index.build('fixture')
    assert index.status('fixture').state=='ready'
    assert index.status('different-model').state=='stale'


def test_ann_filtered_candidates_never_leak(tmp_path, monkeypatch):
    install_fake_usearch(monkeypatch)
    db=Store(tmp_path/'v.sqlite')
    add(db,'release','Version GPIO circuits',[0,1],source='releases',version='1.5.1',channel='release')
    for i in range(20):
        add(db,f'dev{i}','Development GPIO circuits',[1,0],source='dev',channel='dev')
    ann=ANNIndex(db);ann.build('fixture')
    r=Retriever(db,FixtureEmbedder(),ann=ann)
    out=r.search('GPIO',mode='semantic',firmware_version='1.5.1',version_policy='strict')
    assert [h['id'] for h in out['results']]==['release:0']
    assert out['semantic_backend']=='exact-filtered'


def test_reranker_reorders_candidates_and_is_off_by_default(tmp_path):
    db=Store(tmp_path/'v.sqlite')
    add(db,'one','Furi firmware guide')
    add(db,'two','Furi GPIO firmware guide')
    reranker=LocalReranker('cross-encoder', scorer=lambda pairs:[0.,10.] if pairs[0][1].startswith('one') else [10.,0.])
    r=Retriever(db,FixtureEmbedder(),reranker=reranker)
    bare=r.search('Furi',mode='lexical',top_k=2,rerank=False)
    assert bare['reranker_status']=='disabled'
    out=r.search('Furi',mode='lexical',top_k=2,rerank=True)
    assert out['reranker_status']=='active'
    assert out['results'][0]['rerank_score']>=out['results'][1]['rerank_score']
    assert any('rerank_score' in x for x in out['results'])


def test_invalid_reranker_does_not_break_retrieval(tmp_path):
    db=Store(tmp_path/'v.sqlite')
    add(db,'one','Furi firmware guide')
    r=Retriever(db,FixtureEmbedder(),reranker=LocalReranker('cross-encoder',scorer=lambda pairs:[float('nan')]))
    out=r.search('Furi',mode='lexical',rerank=True)
    assert out['results'] and out['reranker_status'].startswith('unavailable:')
    with pytest.raises(RerankerUnavailable):
        r.reranker.score('x',[{'title':'x','heading':'','content':'x'}])


def test_api_version_contract_and_source_description(tmp_path):
    from flipper_rag.api import Query
    from pydantic import ValidationError
    assert Query(query='Furi', firmware_version='1.5.1').version_policy=='include-unversioned'
    with pytest.raises(ValidationError):
        Query(query='Furi',firmware_version='1.5.1; rm -rf /')
    with pytest.raises(ValidationError):
        Query(query='Furi',version_policy='unsafe')
