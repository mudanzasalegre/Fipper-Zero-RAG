"""v0.8 test suite: local only, no hardware or network access."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from flipper_rag.development import (
    APP_ID, DEV_SOURCE_ID, build_fap, catalog, development_documents,
    get_template, guides, parse_fam, scaffold, templates, validate_fap,
    validate_mjs, validate_project, valid_relative_path,
)
from flipper_rag.models import Embedder
from flipper_rag.config import Settings
from flipper_rag.retrieval import Retriever
from flipper_rag.sources import index_documents
from flipper_rag.storage import Store


def test_catalog_complete():
    items = catalog()
    assert items['schema_version'] == 1
    assert len(items['templates']) >= 7
    assert len(items['guides']) >= 7
    assert {x['kind'] for x in templates()} == {'fap', 'mjs'}
    assert all(x['references'] for x in guides())
    with pytest.raises(ValueError): get_template('missing')


@pytest.mark.parametrize('spec', templates(), ids=lambda x: x['id'])
def test_all_templates_scaffold_and_validate(tmp_path, spec):
    project = tmp_path / spec['id']
    res = scaffold(spec['id'], 'test_app', project, name='Test App')
    assert len(res['files']) >= 1
    assert validate_project(project, kind=spec['kind'])['valid']
    assert '.flipper-rag-project.json' in {x.name for x in project.iterdir()}
    assert b'{{APP_ID}}' not in b''.join(x.read_bytes() for x in project.iterdir() if x.is_file())
    with pytest.raises(ValueError): scaffold(spec['id'], 'test_app', project)


@pytest.mark.parametrize('bad', ['A', 'A_NAME', '123abc', '../path', 'hello-world', 'x'*34, 'xx'])
def test_unsafe_app_ids_rejected(tmp_path, bad):
    with pytest.raises(ValueError): scaffold('furi-dialog', bad, tmp_path / 'out')


def test_unsafe_title_is_rejected(tmp_path):
    with pytest.raises(ValueError): scaffold('furi-dialog', 'abc', tmp_path/'out', name='Hello"\n')


def test_manifest_static_no_execution(tmp_path):
    marker = tmp_path/'BAD'
    payload = "__import__('pathlib').Path(%r).write_text('HACK')\nApp(appid='abc', apptype=FlipperAppType.EXTERNAL, entry_point='abc_app')" % str(marker)
    with pytest.raises(ValueError): parse_fam(payload)
    assert not marker.exists()
    with pytest.raises(ValueError): parse_fam("App(appid=__import__('os').getcwd(), apptype=FlipperAppType.EXTERNAL)")
    with pytest.raises(ValueError): parse_fam("App(appid='abc', appid='def')")
    assert parse_fam("App(appid='demo', apptype=FlipperAppType.EXTERNAL)")['apptype'] == 'EXTERNAL'


def test_fam_validation_semantics():
    basic = {'application.fam': "App(appid='my_app', apptype=FlipperAppType.EXTERNAL, entry_point='my_app_app', sources=['my_app.c'])", 'my_app.c': 'int32_t my_app_app(void* ctx){return 0;}'}
    assert not validate_fap(basic)
    assert any(x.code == 'c.entry_missing' for x in validate_fap(basic | {'my_app.c': 'int32_t other(void* p){return 0;}' }))
    assert any(x.code == 'fam.apptype' for x in validate_fap(basic | {'application.fam': basic['application.fam'].replace('EXTERNAL','STARTUP')}))
    assert any(x.code == 'fam.sources' for x in validate_fap(basic | {'application.fam':basic['application.fam'].replace('my_app.c','../evil.c')}))
    assert any(x.code == 'fam.custom_build' for x in validate_fap(basic | {'application.fam':basic['application.fam'][:-1]+',fap_extbuild=[1])'}))
    assert any(x.code == 'fam.unapproved_field' for x in validate_fap(basic | {'application.fam':basic['application.fam'][:-1]+',weird_hook="exec")'}))


class FakeGraph:
    def exports(self, ref, **kwargs):
        if ref == 'unknown':
            raise ValueError('not indexed')
        return {'snapshot':'1'*40,'api_version':'1.5','results':[{'name':'furi_record_open','status':'+'}, {'name':'furi_record_close','status':'-'}]}


def test_firmware_export_crosscheck():
    src={'application.fam':"App(appid='demo_app', apptype=FlipperAppType.EXTERNAL, entry_point='demo_app_app')",
         'demo_app.c': 'int32_t demo_app_app(void* p){ furi_record_open(0); furi_record_close(0); return 0; }'}
    issues=validate_fap(src, FakeGraph(), '1.5.1')
    assert any(x.code=='api.not_exported' for x in issues)
    assert not any(x.code=='api.snapshot' for x in issues)
    assert any(x.code=='api.snapshot' for x in validate_fap(src,FakeGraph(),'unknown'))


def test_mjs_checks():
    assert validate_mjs({'main.js':'print("Hello");'}) == []
    assert any(x.code=='js.event_order' for x in validate_mjs({'main.js':'let g=require("gpio"); let ev=require("event_loop");'}))
    assert any(x.code=='js.browser_node' for x in validate_mjs({'main.js':'window.alert("Hi");'}))
    assert any(x.code=='js.esmodule' for x in validate_mjs({'main.js':'import x from "fs";'}))
    assert any(x.code=='js.brackets' for x in validate_mjs({'main.js':'print((1);'}))
    assert not any(x.code=='js.brackets' for x in validate_mjs({'main.js':'print("})]"); // } ]\n'}))
    assert any(x.code=='js.unknown_module' for x in validate_mjs({'main.js':'require("node:fs");'}))
    assert any(x.code=='js.arrow' for x in validate_mjs({'main.js':'let a = () => 3;'}))
    assert any(x.code=='js.event_order' for x in validate_mjs({'main.js':'let g=require("gui");'}))


def test_paths_and_symlinks(tmp_path):
    assert not valid_relative_path('../evil')
    assert not valid_relative_path('/tmp/file.js')
    assert not valid_relative_path('folder\\name.js')
    assert valid_relative_path('src/demo.c')
    assert not valid_relative_path('.env')
    p=tmp_path/'src';p.mkdir();(p/'main.js').write_text('print("test")')
    link=p/'danger.js'
    try:
        link.symlink_to(p/'main.js')
    except (NotImplementedError, OSError):
        pytest.skip('Symlinks not supported')
    with pytest.raises(ValueError): validate_project(p)


def test_build_dry_run_without_ufbt(tmp_path):
    p=tmp_path/'demo';scaffold('furi-dialog','demo_app',p)
    data=build_fap(p)
    assert data['status']=='dry-run' and not data['executed']
    assert data['command']==['ufbt']


@pytest.mark.skipif(os.name=='nt', reason='Fake uFBT shell executable is POSIX-only')
def test_real_subprocess_runner_with_fake_toolchain(tmp_path):
    project=tmp_path/'demo';scaffold('furi-dialog','demo_app',project)
    stub=tmp_path/'fake-ufbt'
    stub.write_text('#!/usr/bin/env python3\nfrom pathlib import Path\np=Path("dist");p.mkdir(exist_ok=True)\n(p/"demo_app.fap").write_bytes(b"FAP_TEST_BLOB")\nprint("build OK")\n')
    stub.chmod(0o755)
    report=build_fap(project,execute=True,ufbt_binary=str(stub))
    assert report['status']=='passed' and report['artifacts'][0]['sha256']
    assert report['returncode']==0 and 'build OK' in report['output']
    report2=build_fap(project,execute=True,ufbt_binary=str(stub))
    assert report2['status']=='passed' and not report2['artifacts'][0]['content_changed']
    bad=tmp_path/'failing-ufbt'
    bad.write_text('#!/usr/bin/env python3\nimport sys\nprint("fail")\nsys.exit(8)\n')
    bad.chmod(0o755)
    assert build_fap(project,execute=True,ufbt_binary=str(bad))['status']=='failed'


def test_validation_does_not_compile_invalid_fap(tmp_path):
    project=tmp_path/'demo';scaffold('furi-dialog','demo_app',project)
    (project/'application.fam').write_text('print("oops")')
    assert build_fap(project,execute=True)['status']=='invalid'


def test_api_readonly_and_inline_validation():
    from flipper_rag.api import app
    client=TestClient(app)
    assert client.get('/development').status_code==200
    templates_data=client.get('/api/development/templates').json()
    assert templates_data['count']>=7
    assert 'application.fam' in client.get('/api/development/templates/furi-dialog').json()['files']
    assert client.get('/api/development/templates/unknown').status_code==404
    assert client.get('/api/development/guides').json()['count']>=7
    assert client.get('/api/development/guides/furi-gui').status_code==200
    assert client.get('/api/development/guides/unknown').status_code==404
    assert client.post('/api/development/validate',json={'kind':'mjs','files':{'main.js':'print("okay")'}}).json()['valid']
    assert client.post('/api/development/validate',json={'files':{'../leak.js':'x'}}).status_code==422
    assert client.post('/api/development/validate',json={'files':{'main.js':'x'*65000}}).status_code==413
    assert client.post('/api/development/build',json={'cmd':'ufbt'}).status_code==404


def test_cli_subcommands(tmp_path,capsys,monkeypatch):
    from flipper_rag.cli import main
    monkeypatch.setenv('RAG_DB_PATH',str(tmp_path/'index.sqlite3'))
    monkeypatch.setenv('RAG_CHAT_PROVIDER','none')
    monkeypatch.setenv('RAG_EMBED_PROVIDER','none')
    main(['dev','templates']); assert 'furi-dialog' in capsys.readouterr().out
    main(['dev','guides']); assert 'typescript-sdk' in capsys.readouterr().out
    project=tmp_path/'project'
    main(['dev','scaffold','--template','js-hello','--appid','demo_app','--output',str(project)])
    assert 'js-hello' in capsys.readouterr().out
    main(['dev','validate','--project',str(project)])
    assert json.loads(capsys.readouterr().out)['valid']
    main(['dev','doctor']); assert 'ufbt_installed' in capsys.readouterr().out


def test_development_docs_index_and_lexical_search(tmp_path,monkeypatch):
    monkeypatch.setenv('RAG_EMBED_PROVIDER','none')
    store=Store(tmp_path/'idx.sqlite3')
    embedder=Embedder(Settings())
    result=index_documents(store,development_documents(),embedder)
    assert result['added']>=14
    data=Retriever(store,embedder).search('uFBT SDK build FAP compile',mode='lexical',top_k=6)
    assert data['results']
    assert any('Development' in row['title'] for row in data['results'])
    assert len(list(development_documents()))>=14


def test_no_network_or_flash_in_runner():
    from flipper_rag import development
    import inspect
    text=inspect.getsource(development.build_fap)
    assert "subprocess.run([str(binary)]" in text
    assert 'subprocess.run([str(binary)]' in text
