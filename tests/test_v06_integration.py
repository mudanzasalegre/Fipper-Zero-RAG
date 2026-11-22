"""V0.6 integration suite against the real v0.5 protocol catalog on CI."""
from pathlib import Path
import pytest

pytest.importorskip('flipper_rag.protocols')

from flipper_rag.protocol_intelligence import get_intelligence, evaluate_ontology, load_benchmark


def test_actual_registry_and_ontology():
    engine = get_intelligence()
    assert len(engine) == 118
    assert len(engine.data['profiles']) >= 35
    assert len(engine.data['relations']) >= 27
    assert engine.card('mifare-desfire')['name'] == 'MIFARE DESFire'
    assert engine.card('subghz-keeloq')['capabilities']['source_identified']['status']=='documented'


def test_actual_ontology_offline_benchmark():
    engine = get_intelligence()
    cases=load_benchmark(Path(__file__).parent.parent/'benchmarks/ontology_v06.jsonl')
    report=evaluate_ontology(engine,cases)
    assert report['passed'], [c for c in report['details'] if not c['success']]
    assert report['positive_recall']==1.0
    assert report['negative_accuracy']==1.0


def test_read_only_fastapi_routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from flipper_rag.ontology_api import attach_ontology
    app=FastAPI()
    attach_ontology(app)
    client=TestClient(app)
    assert client.get('/ontology').status_code == 200
    assert 'PROTOCOL INTELLIGENCE' in client.get('/ontology').text
    assert client.get('/api/ontology/stats').json()['protocols']==118
    data=client.get('/api/ontology/search',params={'family':'nfc','feature':'page-memory'}).json()
    assert any(x['id']=='ntag213' for x in data['results'])
    card=client.get('/api/ontology/protocols/mifare-desfire').json()
    assert card['capabilities']['emulate_data']['status']=='not_supported'
    assert client.get('/api/ontology/protocols/invented').status_code==404
    assert client.get('/api/ontology/protocols/mifare-desfire',params={'firmware_version':'1.5.1'}).json()['capabilities']['emulate_uid']['status']=='unknown'
    comparison=client.post('/api/ontology/compare',json={'protocols':['mifare-classic','mifare-desfire']}).json()
    assert comparison['capabilities']['emulate_data']['mifare-desfire']['status']=='not_supported'
    assert client.post('/api/ontology/compare',json={'protocols':['mifare-classic','mifare-classic']}).status_code==422
    graph=client.get('/api/ontology/graph',params={'format':'jsonld'}).json()
    assert '@graph' in graph
    neighbors=client.get('/api/ontology/protocols/iso-14443-3a/relations').json()
    assert any(n['id']=='mifare-classic' for n in neighbors['nodes'])
