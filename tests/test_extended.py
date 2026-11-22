"""Offline integration, provenance, migration and safe-source tests."""
import json
import sqlite3
from pathlib import Path
import pytest
from flipper_rag.chunking import chunk_text
from flipper_rag.sources import local_documents, load_catalog, validate_git_source, _canonical_doc_link
from flipper_rag.storage import Document, Store
from flipper_rag.retrieval import Retriever
from flipper_rag.config import Settings
from flipper_rag.models import Embedder, ChatModel, ModelUnavailable
from flipper_rag.service import RAGService


class OfflineEmbedder(Embedder):
    @property
    def active(self):
        return False


def test_catalog_all_sources_are_allowlisted():
    catalog = load_catalog(Path(__file__).resolve().parents[1] / 'sources.json')
    assert len(catalog['web']) >= 25
    assert len(catalog['git']) >= 9
    assert sum(s['tier'] == 'community' for s in catalog['git']) == 3


@pytest.mark.parametrize('bad_url', [
    'https://evil.example/payload.git',
    'http://github.com/flipperdevices/flipperzero-firmware.git',
    'https://github.com/flipperdevices/flipperzero-firmware.git?token=abc',
    'https://github.com/evil/flipperzero-firmware.git',
])
def test_unapproved_git_source_rejected(bad_url):
    with pytest.raises(ValueError):
        validate_git_source({'id': 'unsafe', 'url': bad_url, 'branch': 'dev',
                             'tier': 'official', 'paths': []})


def test_trust_mismatch_rejected():
    with pytest.raises(ValueError):
        validate_git_source({'id': 'mismatch',
                             'url': 'https://github.com/djsime1/awesome-flipperzero.git',
                             'branch': 'main', 'tier': 'official', 'paths': []})


def test_local_ingest_excludes_hidden_and_private(tmp_path):
    (tmp_path / 'guide.md').write_text('Knowledge of NFC', encoding='utf-8')
    (tmp_path / '.env').write_text('API_KEY=NOT_FOR_INDEX', encoding='utf-8')
    (tmp_path / 'credentials').mkdir()
    (tmp_path / 'credentials' / 'leak.json').write_text('{"secret": 1}', encoding='utf-8')
    (tmp_path / 'test.py').write_text('print("safe")', encoding='utf-8')
    docs = list(local_documents(tmp_path))
    assert sorted(d.title for d in docs) == ['guide.md', 'test.py']
    assert all(d.trust == 'local' for d in docs)


def test_migration_adds_trust_column(tmp_path):
    path = tmp_path / 'legacy.sqlite'
    db = Store(path)
    with db.connect() as c:
        c.execute('INSERT INTO documents(id,source_id,title,url,category,revision,license,trust,content_sha)'
                  ' VALUES(?,?,?,?,?,?,?,?,?)', ('x', 's', 't', 'https://example.org', 'cat', '', '', 'community', '123'))
    # The init path is repeatable; previously indexed documents survive.
    Store(path)
    with db.connect() as c:
        assert c.execute('SELECT trust FROM documents WHERE id="x"').fetchone()[0] == 'community'


def test_multisource_trust_filter_and_no_models(tmp_path):
    db = Store(tmp_path / 'index.db')
    for doc in [
        Document('a', 'official', 'Furi API', 'https://github.com/flipperdevices/flipperzero-firmware',
                 'furi', 'Furi is a firmware abstraction API.', trust='official'),
        Document('b', 'community', 'Furi community', 'https://github.com/community/x',
                 'furi', 'A community Furi extension.', trust='community'),
    ]:
        db.upsert(doc, chunk_text(doc.body))
    r = Retriever(db, OfflineEmbedder(Settings()))
    results = r.search('Furi', top_k=4, trust='official', mode='lexical')
    assert len(results['results']) == 1
    assert results['results'][0]['trust'] == 'official'
    assert not results['semantic_available']
    assert r.search('Furi', trust='community', mode='lexical')['results'][0]['trust'] == 'community'
    with pytest.raises(ValueError):
        r.search('Furi', mode='danger')


def test_citations_are_not_fabricated_by_service(tmp_path):
    db = Store(tmp_path / 'idx.db')
    doc = Document('furi', 'test', 'Furi', 'https://docs.flipper.net/zero', 'furi', 'Furi Core APIs.', trust='official')
    db.upsert(doc, chunk_text(doc.body))
    class BadModel(ChatModel):
        def generate(self, system, prompt):
            assert 'Furi Core APIs' in prompt
            return 'El contexto habla de Furi [99].'
    data = RAGService(Retriever(db, OfflineEmbedder(Settings())), BadModel(Settings()), Settings()).ask('Furi')
    assert 'cita inexistente' in data['answer']
    assert data['sources'][0]['citation'] == 1


def test_fts_query_does_not_execute_syntax(tmp_path):
    db = Store(tmp_path / 'idx.db')
    doc = Document('doc', 'test', 'GPIO', 'https://example.org', 'gpio', '# GPIO\nExample content for pin interfaces')
    db.upsert(doc, chunk_text(doc.body))
    assert isinstance(db.lexical('GPIO " OR ) *'), list)


def test_all_local_starter_notes_are_indexable(tmp_path):
    base = Path(__file__).resolve().parents[1] / 'knowledge/starter'
    docs = list(local_documents(base, source_id='starter'))
    assert len(docs) >= 15
    db = Store(tmp_path / 'idx.db')
    for d in docs:
        db.upsert(d, chunk_text(d.body))
    assert db.stats()['documents'] == len(docs)
    hits = Retriever(db, OfflineEmbedder(Settings())).search('FAP uFBT', mode='lexical')
    assert hits['results']


def test_api_input_contract():
    from flipper_rag.api import Query
    from pydantic import ValidationError
    assert Query(query='Furi').mode == 'hybrid'
    with pytest.raises(ValidationError):
        Query(query='A', top_k=99)
    with pytest.raises(ValidationError):
        Query(query='Furi', trust='not-trust')
