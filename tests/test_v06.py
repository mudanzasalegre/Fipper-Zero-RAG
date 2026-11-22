"""Protocol Intelligence v0.6: no external network, live hardware or models needed."""
import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
import pytest

from flipper_rag.protocol_intelligence import (
    ProtocolIntelligence, _official_reference, validate_ontology, evaluate_ontology, load_benchmark,
)

ONTOLOGY = json.loads(files('flipper_rag').joinpath('data/ontology_v06.json').read_text(encoding='utf-8'))


def catalog_fixture():
    """Minimal local stand-in for the 118-entry v0.5 registry; its presence is tested separately in CI."""
    manual = {
        'iso-14443-3a':'nfc','iso-14443-3b':'nfc','iso-14443-4a':'nfc','iso-15693':'nfc',
        'mifare-classic':'nfc','mifare-ultralight':'nfc','mifare-desfire':'nfc',
        'ntag213':'nfc','ntag215':'nfc','ntag216':'nfc','nfc-felica':'nfc','hid-iclass-picopass':'nfc',
        'hid-h10301':'lf-rfid','em4100':'lf-rfid','em4100-32':'lf-rfid','em4100-16':'lf-rfid',
        'nec':'infrared','necext':'infrared','nec42':'infrared','nec42ext':'infrared',
        'kaseikyo':'infrared','rc5':'infrared','rc5x':'infrared','rc6':'infrared','sirc':'infrared','sirc15':'infrared','sirc20':'infrared',
        'ds1990':'ibutton','ds1992':'ibutton','ds1996':'ibutton','ds1971':'ibutton','dsgeneric':'ibutton',
        'cyfral':'ibutton','metakom':'ibutton','1-wire':'ibutton',
        'uart':'gpio','spi':'gpio','i2c':'gpio',
        'flipper-expansion-protocol':'expansion','rpc-protobuf':'expansion',
        'bluetooth-le':'bluetooth','usb-cdc':'usb','usb-hid':'usb','subghz-keeloq':'sub-ghz'
    }
    for edge in ONTOLOGY['relations']:
        for key in ('source','target'):
            pid=edge[key]
            if pid.startswith('subghz-'):manual[pid]='sub-ghz'
            assert pid in manual
    for pid in ONTOLOGY['profiles']:
        if pid.startswith('subghz-'):manual[pid]='sub-ghz'
        assert pid in manual
    for fam in ONTOLOGY['families']:
        if fam not in manual.values():
            manual['placeholder-'+fam]=fam
    specs = ONTOLOGY['families']
    res=[]
    for pid, family in manual.items():
        scope = ('official-reader-list' if family=='lf-rfid' else
                 'file-format-listed' if family in {'infrared','ibutton'} and pid!='1-wire' else
                 'dev-source-registry' if family=='sub-ghz' else 'official-hardware-or-protocol-doc')
        res.append({'id':pid, 'family':family, 'name':pid, 'layer':family, 'evidence_scope':scope,
                    'aliases':[], 'summary':pid+' description', 'reference':specs[family]['evidence']['reference']})
    return res


@pytest.fixture
def engine():
    return ProtocolIntelligence(catalog_fixture(), ONTOLOGY)


def test_schema_valid(engine):
    assert len(engine)==len(catalog_fixture())
    assert len(engine.data['profiles'])>=30
    assert len(engine.data['relations'])>=20


def test_requires_exact_family_map():
    data=deepcopy(ONTOLOGY);data['families'].pop('nfc')
    with pytest.raises(ValueError,match='families'):
        validate_ontology(data,catalog_fixture())


def test_invalid_profile_reference():
    data=deepcopy(ONTOLOGY);data['profiles']['nonexistent-protocol']={'features':[]}
    with pytest.raises(ValueError,match='Unknown'):
        validate_ontology(data,catalog_fixture())


def test_invalid_external_reference():
    assert not _official_reference('https://docs.flipper.net.evil.example/zero/nfc/read')
    assert not _official_reference('http://docs.flipper.net/zero/nfc/read')
    assert not _official_reference('https://docs.flipper.net/zero/nfc/read?q=x')
    assert _official_reference('https://docs.flipper.net/zero/nfc/read')


def test_claim_without_source_rejected():
    data=deepcopy(ONTOLOGY)
    data['profiles']['mifare-desfire']['capabilities']['emulate_data'].pop('evidence')
    with pytest.raises(ValueError,match='evidence'):
        validate_ontology(data,catalog_fixture())


def test_unknown_is_not_evidence():
    data=deepcopy(ONTOLOGY)
    data['profiles']['mifare-desfire']['capabilities']['read']={
        'status':'unknown','evidence':{'reference':'https://docs.flipper.net/zero/nfc/read','scope':'protocol','note':'no verified evidence'}}
    with pytest.raises(ValueError,match='must not masquerade'):
        validate_ontology(data,catalog_fixture())


def test_cycle_detected():
    data=deepcopy(ONTOLOGY)
    data['relations'].append({'source':'iso-14443-3a','target':'iso-14443-4a','type':'layered_over',
        'evidence':{'reference':'https://developer.flipper.net/flipperzero/doxygen/nfc_file_format.html',
                    'scope':'protocol','note':'Testing a forbidden edge that creates a directed cycle'}})
    with pytest.raises(ValueError,match='Cyclic'):
        validate_ontology(data,catalog_fixture())


def test_explicit_desfire_limit(engine):
    c=engine.capabilities('mifare-desfire')
    assert c['emulate_uid']['status']=='documented'
    assert c['emulate_data']['status']=='not_supported'
    assert c['write']['status']=='unknown'
    assert c['emulate_data']['evidence']['reference'].startswith('https://docs.flipper.net/')


def test_no_generalize_variant_capability(engine):
    assert engine.capabilities('nfc-felica')['emulate_data']['status']=='unknown'
    assert engine.capabilities('iso-15693')['emulate_data']['status']=='unknown'
    assert engine.capabilities('subghz-keeloq')['transmit']['status']=='unknown'


def test_dev_registry_is_not_read_support(engine):
    p=engine.card('subghz-princeton')
    assert 'listed-in-dev-registry' in p['features']
    assert engine.capabilities('subghz-princeton')['read']['status']=='unknown'
    assert engine.capabilities('subghz-princeton')['parse_file']['status']=='documented'


def test_frequency_family_caveat(engine):
    x=engine.search(frequency_hz=13560000)
    assert x and all(c['family']=='nfc' for c in x)
    assert engine.search(frequency_hz=433920000)==[]  # no guessed Sub-GHz frequency
    assert engine.card('iso-14443-3a')['family_context']['evidence']['scope']=='family'


def test_capability_and_filters(engine):
    found=engine.search(family='nfc',capability='emulate_data',status='limited')
    ids={x['id'] for x in found}
    assert {'mifare-classic','mifare-ultralight','ntag213'}.issubset(ids)
    assert 'mifare-desfire' not in ids
    unsupported=engine.search(capability='emulate_data',status='not_supported')
    assert {x['id'] for x in unsupported} == {'mifare-desfire'}
    assert engine.search(capability='emulate_data',status='documented')==[]


def test_feature_query(engine):
    ids={x['id'] for x in engine.search(feature='page-memory')}
    assert 'mifare-ultralight' in ids
    assert 'ntag213' in ids
    assert 'mifare-desfire' not in ids


def test_exact_alias_matching(engine):
    assert engine.resolve('MIFARE DESFire')=='mifare-desfire'
    assert engine.resolve('unknown-protocol') is None
    assert engine.card('unknown-protocol') is None


def test_related_graph_and_two_steps(engine):
    rel=engine.neighbors('mifare-desfire',depth=2)
    assert 'iso-14443-4a' in {x['id'] for x in rel['nodes']}
    assert 'iso-14443-3a' in {x['id'] for x in rel['nodes']}
    assert all('evidence' in e for e in rel['edges'])


def test_compare_clear_discrepancies(engine):
    c=engine.compare(['mifare-classic','mifare-desfire'])
    assert c['capabilities']['emulate_data']['mifare-classic']['status']=='limited'
    assert c['capabilities']['emulate_data']['mifare-desfire']['status']=='not_supported'
    assert 'emulate_data' in c['differences']
    assert 'family' in c['similarities']
    assert 'unknown' in c['warning'].lower() or 'desconocido' in c['warning'].lower()


def test_version_requires_exact_evidence(engine):
    c=engine.card('mifare-classic',firmware_version='1.5.1')
    assert c['capabilities']['read']['version_compatibility']=='not_verified_for_release'


def test_graph_jsonld_has_edges(engine):
    g=engine.graph()
    assert len([n for n in g['nodes'] if n['kind']=='protocol'])==len(engine)
    assert any(e['type']=='layered_over' for e in g['edges'])
    assert len(g['edges'])>len(engine)
    exported=engine.jsonld()
    assert exported['@graph'] and any('prov#wasDerivedFrom' in v for e in exported['@graph'] for v in e.keys())


def test_documents_are_local_and_cited(engine):
    docs=list(engine.documents())
    assert len(docs)==len(engine)
    assert all(d.trust=='local' and not d.firmware_version for d in docs)
    assert 'emulate_data' in next(d.body for d in docs if 'mifare-desfire' in d.title)


def test_invalid_filter_values(engine):
    for arg in ({'family':'unknown'},{'capability':'inject'},{'status':'bogus'},{'frequency_hz':-4},
                {'file_format':'../etc/passwd'},{'related_to':'unknown'}):
        with pytest.raises(ValueError):engine.search(**arg)


def test_ambiguous_comparison_rejected(engine):
    with pytest.raises(ValueError):engine.compare(['mifare-classic','mifare-classic'])
    with pytest.raises(ValueError):engine.compare(['mifare-classic'])


def test_bluetooth_not_assumed_hid(engine):
    assert engine.capabilities('bluetooth-le')['emulate_data']['status']=='unknown'
    assert engine.capabilities('usb-hid')['write']['status']=='unknown'


def test_offline_ontology_evaluation(engine):
    from pathlib import Path
    path=Path(__file__).resolve().parent.parent/'benchmarks'/'ontology_v06.jsonl'
    report=evaluate_ontology(engine,load_benchmark(path))
    assert report['cases']==18
    assert report['passed'], [x for x in report['details'] if not x['success']]
    assert report['positive_recall']==1.0
    assert report['negative_accuracy']==1.0


def test_source_snapshot_not_device_capability(engine):
    caps=engine.capabilities('subghz-keeloq')
    assert caps['source_identified']['status']=='documented'
    assert caps['source_identified']['evidence']['scope']=='dev-snapshot'
    assert caps['transmit']['status']=='unknown'


def test_inverse_direction_graph(engine):
    rel=engine.neighbors('iso-14443-3a', depth=1)
    assert 'mifare-classic' in {x['id'] for x in rel['nodes']}
    assert any(e['direction_from_root']=='incoming' for e in rel['edges'])


def test_version_uncertainty_honest(engine):
    result=engine.compare(['mifare-classic','mifare-desfire'],firmware_version='1.5.1')
    assert result['capabilities']['emulate_data']['mifare-classic']['status']=='unknown'
    assert result['capabilities']['emulate_data']['mifare-classic']['documentation_status']=='limited'
