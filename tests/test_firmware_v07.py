"""Offline versioned graph fixture. No real Flipper or internet required."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from flipper_rag.firmware_parser import parse_c, parse_exports, parse_fam
from flipper_rag.firmware_graph import FirmwareGraph, resolve_ref


def git(directory, *args):
    return subprocess.check_output(['git','-C',str(directory),*args], stderr=subprocess.PIPE).decode().strip()


def write(root, name, content):
    p=root/name
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(content, encoding='utf-8')


@pytest.fixture
def fwrepo(tmp_path):
    root=tmp_path/'upstream'
    root.mkdir()
    subprocess.run(['git','init','-b','dev',str(root)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    git(root,'config','user.name','Graph Test')
    git(root,'config','user.email','graph@example.invalid')
    git(root,'remote','add','origin','https://github.com/flipperdevices/flipperzero-firmware.git')
    write(root,'furi/core/util.h','''#pragma once\nint helper(int a);\n''')
    write(root,'furi/core/util.c','''#include "util.h"\nint helper(int a){ return a+1; }\n''')
    write(root,'furi/core/demo.c','''#include "util.h"\n#define COUNT 2\nstatic int local(void){ return helper(COUNT); }\nint app_start(void){ return local(); }\n''')
    write(root,'applications/system/application.fam','''App(appid="system",apptype=FlipperAppType.SERVICE)\n''')
    write(root,'applications/example/application.fam','''App(appid="example",apptype=FlipperAppType.EXTERNAL,requires=["system"])\n''')
    write(root,'targets/f7/api_symbols.csv','''entry,status,name,type,params\nVersion,+,1.0,,\nHeader,+,furi/core/util.h,,\nFunction,+,helper,int,(int a)\nFunction,-,app_start,int,(void)\n''')
    git(root,'add','.')
    git(root,'commit','-m','v1')
    git(root,'tag','1.0.0')
    sha1=git(root,'rev-parse','HEAD')
    write(root,'furi/core/util.h','''#pragma once\nlong helper(long a);\nint added(void);\n''')
    write(root,'furi/core/util.c','''#include "util.h"\nlong helper(long a){ return a+2; }\nint added(void){ return helper(3); }\n''')
    write(root,'furi/core/demo.c','''#include "util.h"\n#define COUNT 2\nstatic int local(void){ return helper(COUNT); }\nint app_start(void){ return local()+added(); }\n''')
    write(root,'targets/f7/api_symbols.csv','''entry,status,name,type,params\nVersion,+,1.1,,\nHeader,+,furi/core/util.h,,\nFunction,+,helper,long,(long a)\nFunction,+,added,int,(void)\n''')
    git(root,'add','.')
    git(root,'commit','-m','v2')
    git(root,'tag','1.1.0')
    sha2=git(root,'rev-parse','HEAD')
    return root,sha1,sha2


def test_parser_symbols_and_calls():
    code='''#include "util.h"\n#define SCALE(n) ((n)*2)\n// int fake(void) { foo(); }\nstatic int foo(int v) { if(v) return helper(v); return 0; }\nint bar(void);\nvoid bar(void){ foo(3); const char *s="hello(false())"; }\n'''
    parsed=parse_c('furi/core/example.c',code)
    kinds={(s.name,s.kind) for s in parsed.symbols}
    assert ('foo','function') in kinds
    assert ('bar','declaration') in kinds and ('bar','function') in kinds
    assert ('SCALE','macro') in kinds
    assert 'fake' not in [s.name for s in parsed.symbols]
    names=[(r.relation,r.target_name) for r in parsed.references]
    assert ('includes','util.h') in names
    assert ('calls','helper') in names and ('calls','foo') in names
    assert ('calls','false') not in names


def test_fam_does_not_execute(tmp_path):
    marker=tmp_path/'SHOULD_NOT_EXIST'
    data=f'''App(appid="hello", apptype=FlipperAppType.EXTERNAL, requires=["gui"])\nopen({str(marker)!r},"w").write("danger")\n'''
    parsed=parse_fam('applications/hello/application.fam',data)
    assert parsed.app_id=='hello' and not marker.exists()
    assert parsed.app_properties['requires']==['gui']
    assert parsed.references[0].relation=='requires_app'


def test_exports_distinguish_inaccessible():
    version,entries=parse_exports('entry,status,name,type,params\nVersion,+,88.5,,\nFunction,+,one,int,(int x)\nFunction,-,two,void,(void)\nFunction,?,three,void,(void)\n')
    assert version=='88.5'
    assert [x['status'] for x in entries]==['+','-','?']
    with pytest.raises(ValueError):parse_exports('not,a,valid,csv\n')


def test_index_graph_crossrefs_and_citation(fwrepo,tmp_path):
    repo,sha1,sha2=fwrepo
    graph=FirmwareGraph(tmp_path/'graph.sqlite')
    out=graph.index(repo,'1.0.0')
    assert out['sha']==sha1 and out['complete'] and out['official']
    assert out['files']>=6 and out['api_entries']==2
    assert graph.index(repo,'1.0.0')['state']=='unchanged'
    all_symbols=graph.symbols('1.0.0',query='helper')
    assert all_symbols['total']>=2
    impl=next(s for s in all_symbols['results'] if s['kind']=='function')
    assert impl['url'].startswith('https://github.com/flipperdevices/flipperzero-firmware/blob/'+sha1)
    assert graph.symbol('1.0.0',impl['id'])['api_exports'][0]['status']=='+'
    refs=graph.references('1.0.0','helper')
    assert any(x['relation']=='calls' and x['resolution']=='resolved' and x['target']==impl['id'] for x in refs['references'])
    assert any(x['relation']=='includes' for x in graph.references('1.0.0','util.h')['references'])
    assert any(x['relation']=='requires_app' and x['resolution']=='resolved' for x in graph.references('1.0.0','system')['references'])
    assert graph.symbols('1.0.0',query='app_start',exported_only=True)['total']==0
    assert graph.exports('1.0.0',query='helper')['results'][0]['status']=='+'
    assert graph.neighbors('1.0.0','app_start')['edges']
    assert graph.rag_documents('1.0.0',10)


def test_compare_release_and_api_contract(fwrepo,tmp_path):
    repo,a,b=fwrepo
    graph=FirmwareGraph(tmp_path/'graph.sqlite')
    graph.index(repo,'1.0.0')
    graph.index(repo,'1.1.0')
    diff=graph.compare('1.0.0','1.1.0')
    assert diff['before']==a and diff['after']==b
    assert diff['counts']['signature_changed']>=1
    assert any(x['name']=='helper' and x['change']=='api_signature_changed' for x in diff['api_changes'])
    assert any(x['name']=='added' and x['change']=='api_export_added' for x in diff['api_changes'])
    assert diff['api_versions'] == ['1.0', '1.1']
    assert diff['file_changes']['modified']>=2
    assert graph.compare(a,b)['counts'] == diff['counts']
    assert graph.compare('1.0.0',a)['same_commit']
    assert len(graph.snapshots())==2


def test_invalid_ref_does_not_run_commands(fwrepo,tmp_path):
    repo,_,_=fwrepo
    graph=FirmwareGraph(tmp_path/'test.sqlite')
    for ref in ('../../etc/passwd','dev;touch evil','--help','a'*200):
        with pytest.raises(ValueError):graph.index(repo,ref)
    assert resolve_ref(repo,'1.0.0')


def test_partial_scan_is_refused_in_diff(fwrepo,tmp_path):
    repo,_,_=fwrepo
    graph=FirmwareGraph(tmp_path/'test.sqlite')
    out=graph.index(repo,'1.0.0',max_file_bytes=1024)
    assert out['complete']
    with pytest.raises(ValueError,match='max_files'):
        graph.index(repo,'1.1.0',max_files=1)


def test_api_routes_read_only(fwrepo,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from flipper_rag import firmware_api
    from flipper_rag.api import app
    repo,_,_=fwrepo
    graph=FirmwareGraph(tmp_path/'graph.sqlite')
    graph.index(repo,'1.0.0')
    monkeypatch.setattr(firmware_api,'_graph',graph)
    client=TestClient(app)
    assert client.get('/firmware').status_code==200
    assert client.get('/api/firmware/snapshots').json()['snapshots']
    res=client.get('/api/firmware/symbols',params={'ref':'1.0.0','query':'helper'})
    assert res.status_code==200 and res.json()['total']>=1
    comp=client.get('/api/firmware/compare',params={'before':'missing','after':'1.0.0'})
    assert comp.status_code==422
    assert client.get('/api/firmware/symbols',params={'ref':'1.0.0','limit':9999}).status_code==422


def test_static_only_resolution_does_not_cross_files():
    graph = FirmwareGraph.__new__(FirmwareGraph)  # pure resolver, no database needed
    one = parse_c('furi/one.c', 'static void local(void) {}')
    two = parse_c('furi/two.c', 'void public_action(void){local();}')
    out = graph._resolve_references([one, two])
    link = next(r for r in out if r.target_name == 'local')
    assert link.target is None and link.resolution == 'unresolved'


def test_duplicate_global_symbols_remain_ambiguous():
    graph = FirmwareGraph.__new__(FirmwareGraph)
    one = parse_c('furi/a.c', 'int duplicate(void){return 1;}')
    two = parse_c('furi/b.c', 'int duplicate(void){return 2;}')
    caller = parse_c('furi/c.c', 'int run(void){return duplicate();}')
    out = graph._resolve_references([one, two, caller])
    link = next(r for r in out if r.target_name == 'duplicate')
    assert link.target is None and link.resolution == 'ambiguous'


def test_commented_includes_are_not_indexed():
    code='''// #include "fake.h"\n/* #include "nope.h" */\n#include "real.h"\n'''
    refs=parse_c('furi/a.c', code).references
    assert [r.target_name for r in refs] == ['real.h']


def test_api_comparison_missing_file_is_unknown(fwrepo,tmp_path):
    repo,_,_=fwrepo
    from flipper_rag.firmware_graph import FirmwareGraph
    graph=FirmwareGraph(tmp_path/'partial.sqlite')
    graph.index(repo,'1.0.0')
    # Remove SDK CSV and make a third version to emulate an upstream build
    # where no export metadata is available, without claiming exports removed.
    (repo/'targets/f7/api_symbols.csv').unlink()
    git(repo,'add','-A');git(repo,'commit','-m','SDK CSV missing');git(repo,'tag','1.2.0')
    graph.index(repo,'1.2.0')
    diff=graph.compare('1.0.0','1.2.0')
    assert diff['api_comparison_status']=='unavailable-missing-api-symbols'
    assert diff['api_changes']==[]


def test_cli_firmware_index_and_snapshots(fwrepo,tmp_path,monkeypatch,capsys):
    from flipper_rag.cli import main
    repo,sha,_=fwrepo
    monkeypatch.setenv('RAG_DB_PATH',str(tmp_path/'all.sqlite'))
    monkeypatch.setenv('RAG_EMBED_PROVIDER','none')
    monkeypatch.setenv('RAG_CHAT_PROVIDER','none')
    main(['firmware','index','--repo',str(repo),'--ref','1.0.0'])
    assert json.loads(capsys.readouterr().out)['sha']==sha
    main(['firmware','snapshots'])
    assert json.loads(capsys.readouterr().out)['snapshots'][0]['sha']==sha
    main(['firmware','rag-index','--ref','1.0.0','--limit','2'])
    printed=capsys.readouterr().out
    counts=json.loads(printed[printed.index('{'):])
    assert counts['added']>=1
