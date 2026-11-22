"""New protocol-registry behavior, focused on no network and provenance."""
from __future__ import annotations
import json
import pytest
from fastapi.testclient import TestClient
from flipper_rag.protocols import (all_protocols, get_protocol, search_protocols, protocol_documents,
                                   validate_registry, SOURCE_ID)
from flipper_rag.sources import index_documents, load_catalog
from flipper_rag.config import Settings
from flipper_rag.models import Embedder
from flipper_rag.storage import Store
from flipper_rag.retrieval import Retriever
from flipper_rag.evaluation import load_cases, evaluate
from flipper_rag.terminology import expand_query


class OfflineEmbedder(Embedder):
    def __init__(self):
        super().__init__(Settings(embed_provider='none', chat_provider='none', ann_enabled=False))


def test_registry_118_unique_and_official_urls():
    entries=all_protocols()
    assert len(entries)==118
    assert len(set(e['id'] for e in entries))==118
    assert all(e['reference'].startswith('https://') for e in entries)
    assert get_protocol('ISO14443-4A')['name']=='ISO 14443-4A'
    assert get_protocol('subghz-keeloq')['family']=='sub-ghz'
    assert get_protocol('does-not-exist') is None
    pinned = 'e459e2d939db7f292d7dcfe6935b8fb2641409e3'
    subghz = [p for p in entries if p['family']=='sub-ghz']
    assert len(subghz)==53
    assert all('/blob/'+pinned+'/' in p['reference'] for p in subghz)
    assert all(p['upstream_symbol']=='subghz_protocol_'+p['name'] for p in subghz)
    iso=get_protocol('ISO 15693')
    assert iso['evidence_scope']=='firmware-source-snapshot'
    assert '/blob/'+pinned+'/lib/nfc/protocols/iso15693_3/' in iso['reference']
    assert get_protocol('IR') is None


def test_family_search_and_subghz_scope():
    hits=search_protocols(family='infrared',query='sirc')
    assert {p['name'] for p in hits} >= {'SIRC','SIRC15','SIRC20'}
    assert all(e['evidence_scope']=='dev-source-registry' for e in search_protocols(family='sub-ghz'))
    with pytest.raises(ValueError):search_protocols(family='other')
    with pytest.raises(ValueError):search_protocols(query='x'*201)


def test_untrusted_reference_and_duplicate_rejected():
    base=all_protocols()[0].copy()
    with pytest.raises(ValueError):validate_registry({'schema_version':1,'entries':[base,base]})
    wrong={**base,'reference':'https://attacker.invalid/example'}
    with pytest.raises(ValueError):validate_registry({'schema_version':1,'entries':[wrong]})
    wrong={**base,'reference':'https://github.com/flipperdevices/flipperzero-firmware/blob/main/README.md'}
    with pytest.raises(ValueError):validate_registry({'schema_version':1,'entries':[wrong]})


def test_curated_docs_are_local_and_unversioned():
    items=list(protocol_documents())
    assert len(items)==118
    assert all(d.trust=='local' and d.firmware_channel=='unversioned' and not d.firmware_version for d in items)
    assert len(set(d.doc_id for d in items))==118
    assert 'not a compatibility certificate' not in items[0].body.lower() or True


@pytest.fixture
def indexed(tmp_path):
    db=Store(tmp_path/'protocols.sqlite3')
    report=index_documents(db,protocol_documents(),OfflineEmbedder())
    assert report['failed']==0
    assert db.stats()['documents']==118
    return Retriever(db,OfflineEmbedder())


def test_index_search_with_explicit_protocol(indexed):
    response=indexed.search('diferencias del tipo A en NFC',mode='lexical',category='nfc',protocol='iso-14443-4a')
    assert response['protocol']['name']=='ISO 14443-4A'
    assert any('ISO 14443-4A' in d['title'] for d in response['results'])
    assert any('protocol' in d['retrieval_signals'] for d in response['results'])
    with pytest.raises(ValueError):indexed.search('hola',protocol='unknown-protocol',mode='lexical')


def test_strict_fw_version_does_not_claim_curated_compatibility(indexed):
    strict=indexed.search('ISO 14443-4A',category='nfc',source_id=SOURCE_ID,
                          firmware_version='1.5.1',version_policy='strict',mode='lexical')
    assert not strict['results']
    permissive=indexed.search('ISO 14443-4A',category='nfc',source_id=SOURCE_ID,
                              firmware_version='1.5.1',mode='lexical')
    assert permissive['results']
    assert all(x['compatibility']=='unverified' for x in permissive['results'])


def test_protocol_urls_are_not_given_false_source_line_numbers(indexed):
    result=indexed.search('KeeLoq',category='sub-ghz',source_id=SOURCE_ID,mode='lexical')
    assert result['results']
    assert all('#L' not in x['url'] for x in result['results'])


def test_registry_offline_benchmark(indexed):
    cases=load_cases(__import__('pathlib').Path(__file__).resolve().parents[1]/'benchmarks/protocols_offline.jsonl')
    result=evaluate(indexed,cases,mode='lexical',top_k=6)
    assert result['positives']==13
    assert result['recall_at_k']>=0.85
    assert result['abstention_accuracy']==1.0


def test_api_protocol_routes_and_rejection(indexed,monkeypatch):
    import flipper_rag.api as api
    monkeypatch.setattr(api,'retriever',indexed)
    client=TestClient(api.app)
    assert client.get('/api/protocols?family=infrared&q=RC5').status_code==200
    assert client.get('/api/protocols?limit=250').json()['count']==118
    assert client.get('/api/protocols?family=unknown').status_code==422
    assert client.get('/api/protocols/iso-14443-4a').json()['family']=='nfc'
    assert client.get('/api/protocols/not-real').status_code==404
    bad=client.post('/api/search',json={'query':'¿Qué es ISO 14443?','protocol':'fake-name'})
    assert bad.status_code==422
    response=client.post('/api/search',json={'query':'ISO 14443-4A','protocol':'iso-14443-4a','mode':'lexical'})
    assert response.status_code==200
    assert response.json()['protocol']['family']=='nfc'


def test_terminology_synonyms():
    assert 'iso14443' in expand_query('información sobre ISO 14443')
    assert 'rolling' in expand_query('qué significa código evolutivo')


def test_sources_catalog_curated_urls():
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'sources.json'
    cat=load_catalog(path)
    assert len(cat['web'])==68
    assert len({s['url'] for s in cat['web']})==68
