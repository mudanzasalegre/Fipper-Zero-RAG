"""v1.0 integration, privacy and retrieval tests. No network or devices required."""
from __future__ import annotations
import argparse
import copy
from pathlib import Path
import json
import urllib.error

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flipper_rag.config import Settings
from flipper_rag.models import Embedder
from flipper_rag.platform import Platform, OfficialHTTPClient, PageResult, _canonical
from flipper_rag.platform_api import attach_platform
from flipper_rag.platform_cli import add_parser, run
from flipper_rag.platform_eval import BenchmarkIncomplete, evaluate_official, load_benchmark
from flipper_rag.retrieval import Retriever
from flipper_rag.sources import index_documents
from flipper_rag.storage import Document, Store, document_id

URL1 = "https://developer.flipper.net/flipperzero/doxygen/apps_on_sd_card.html"
URL2 = "https://developer.flipper.net/flipperzero/doxygen/subghz_file_format.html"


class NoEmbeddings:
    active = False


class FakeClient:
    def __init__(self):
        self.content = "Flipper FAP external applications use api_symbols.csv for exported symbols. " * 4
        self.fail = False
        self.calls = 0

    def fetch(self, url, previous=None, *, force=False):
        self.calls += 1
        if self.fail:
            raise OSError("Test network failure")
        if previous and previous["body"] == self.content and not force:
            return PageResult("not-modified", "FAP", previous["body"], '"etag1"')
        return PageResult("modified", "FAP", self.content, '"etag1"')


@pytest.fixture
def platform(tmp_path):
    return Platform(Store(tmp_path/"flipper.sqlite3"))


def _case_file(tmp_path):
    path = tmp_path/"benchmark.json"
    data = {"schema_version":1, "sources":[URL1,URL2],"cases":[
        {"id":"fap-exported","question":"external applications exported api_symbols.csv symbols","relevance":{URL1:3}},
        {"id":"sub-ghz-frequency","question":"SubGhz radio Frequency field and RAW preset","relevance":{URL2:3}},
        {"id":"negative","question":"Etruscan bakery revenue from synthetic mortgage discounts","should_abstain":True},
    ]}
    path.write_text(json.dumps(data),encoding="utf-8")
    return path


def _index_two(platform):
    docs = [
        Document(doc_id=document_id("web-oficial",URL1), source_id="web-oficial",title="FAP API exports",url=URL1,
                 category="documentation",body="External FAP applications use exported api_symbols.csv symbols; API compatibility is versioned."),
        Document(doc_id=document_id("web-oficial",URL2), source_id="web-oficial",title="SubGhz Frequency and RAW",url=URL2,
                 category="documentation",body="A SubGhz RAW radio file has a Frequency field and a Preset entry."),
    ]
    index_documents(platform.store,docs,NoEmbeddings())


def test_incremental_http_two_passes(platform):
    c = FakeClient()
    spec = [{"url":URL1,"category":"development"}]
    first = platform.sync_web(spec,NoEmbeddings(),client=c,delay=0)
    second = platform.sync_web(spec,NoEmbeddings(),client=c,delay=0)
    assert first["added"] == 1 and first["http_modified"] == 1
    assert second["unchanged"] == 1 and second["http_304"] == 1
    assert platform.status()["index"]["documents"] == 1
    assert len(platform.reports("synchronization")) == 2
    assert platform.get_cached_page(URL1)["etag"] == '"etag1"'


def test_modified_document_replaces_chunks(platform):
    c = FakeClient()
    platform.sync_web([{"url":URL1}], NoEmbeddings(),client=c,delay=0)
    c.content += " NEW api_versions export signature change"
    result = platform.sync_web([{"url":URL1}], NoEmbeddings(),client=c,delay=0)
    assert result["updated"] == 1
    assert "NEW" in platform.get_cached_page(URL1)["body"]


def test_304_repairs_missing_index(platform):
    c = FakeClient()
    platform.sync_web([{"url":URL1}], NoEmbeddings(),client=c,delay=0)
    assert platform.store.prune_source("web-oficial", set()) == 1
    result = platform.sync_web([{"url":URL1}], NoEmbeddings(),client=c,delay=0)
    assert result["http_304"] == 1 and result["added"] == 1


def test_network_error_never_prunes(platform):
    c = FakeClient()
    platform.sync_web([{"url":URL1}], NoEmbeddings(),client=c,delay=0)
    c.fail = True
    result = platform.sync_web([{"url":URL1}], NoEmbeddings(),client=c,delay=0)
    assert result["failed"] >= 1
    assert platform.store.stats()["documents"] == 1
    assert platform.store.source_runs(1)[0]["status"] == "partial"
    assert result["pages"][0]["error"] == "OSError"


def test_official_url_validation():
    for bad in ("http://docs.flipper.net/zero", "https://evil.example/a",
                "https://developer.flipper.net.evil.example/flipperzero/doxygen/a.html",
                "https://developer.flipper.net/flipperzero/doxygen/a.html?x=1",
                "https://docs.flipper.net/zero/../private"):
        with pytest.raises(ValueError): _canonical(bad)
    assert _canonical(URL1) == URL1


def test_http_304_requires_cached_body(monkeypatch):
    client = OfficialHTTPClient()
    monkeypatch.setattr(client,"_allowed",lambda url:None)
    class Opener:
        def open(self,*a,**kw):
            raise urllib.error.HTTPError(URL1,304,"Not Modified",{},None)
    client._opener = Opener()
    cache = {"title":"Title","body":"alpha","etag":'"abc"',"last_modified":"Wed, 10 Jan 2024 00:00:00 GMT"}
    got = client.fetch(URL1, cache)
    assert got.status == "not-modified" and got.body == "alpha"
    with pytest.raises(urllib.error.HTTPError): client.fetch(URL1)


def test_live_benchmark_validation(tmp_path):
    bm = load_benchmark(_case_file(tmp_path))
    assert len(bm["cases"]) == 3 and len(bm["sha256"]) == 64
    bad = copy.deepcopy(bm)
    bad["cases"][0]["relevance"]={"https://example.org":3}
    p=tmp_path/"bad.json";p.write_text(json.dumps(bad),encoding="utf-8")
    with pytest.raises(ValueError):load_benchmark(p)


def test_live_evaluation_no_fake_success(platform,tmp_path):
    benchmark = load_benchmark(_case_file(tmp_path))
    retriever=Retriever(platform.store,Embedder(Settings(embed_provider="none", ann_enabled=False)))
    with pytest.raises(BenchmarkIncomplete):evaluate_official(platform,retriever,benchmark)
    record=platform.reports("evaluation",1)[0]["report"]
    assert record["status"] == "incomplete" and record["metrics"] is None
    assert record["corpus"]["fraction"] == 0


def test_live_evaluation_real_indexed_pages(platform,tmp_path,monkeypatch):
    monkeypatch.setenv("RAG_EMBED_PROVIDER","none")
    monkeypatch.setenv("RAG_CHAT_PROVIDER","none")
    bm=load_benchmark(_case_file(tmp_path))
    _index_two(platform)
    retriever=Retriever(platform.store,Embedder(Settings(embed_provider="none", ann_enabled=False)))
    report=evaluate_official(platform,retriever,bm,top_k=4)
    assert report["status"] == "complete"
    assert report["corpus"]["indexed"] == 2
    assert 0 <= report["metrics"]["ndcg_at_k"] <= 1
    assert 0 <= report["metrics"]["mrr_at_k"] <= 1
    assert report["metrics"]["citation_metadata_coverage"] == 1
    assert report["metrics"]["positive_questions"] == 2
    assert report["metrics"]["negative_questions"] == 1


def test_local_content_cannot_fake_official_corpus(platform,tmp_path):
    source=Document(doc_id="local-fake",source_id="notes",title="Fake",url=URL1,
                    category="documentation",body="Fake api_symbols.csv note",trust="local")
    index_documents(platform.store,[source],NoEmbeddings())
    bm=load_benchmark(_case_file(tmp_path))
    with pytest.raises(BenchmarkIncomplete):
        evaluate_official(platform,Retriever(platform.store,Embedder(Settings(embed_provider="none", ann_enabled=False))),bm)


def test_coverage_and_stale_health(platform):
    status=platform.status()
    assert status["version"] == "1.0.0"
    assert "catalog_coverage" in status
    assert status["trust"]["official"] == 0
    assert len(status["modules"]) == 5
    assert status["latest_evaluation"] is None
    with pytest.raises(ValueError):platform.status(stale_days=0)


def test_audit_detects_missing_fts(platform):
    _index_two(platform)
    assert platform.audit()["valid"]
    with platform.store.connect() as db:
        db.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT rowid FROM chunks_fts LIMIT 1)")
    assert not platform.audit()["valid"]


def test_curated_local_sync(platform,tmp_path):
    root=tmp_path/"starter";root.mkdir();(root/"readme.md").write_text("A curated local content note about Flipper SDK.")
    report=platform.sync_local([("starter",root)],NoEmbeddings())
    assert report["sources"]["starter"]["added"]==1
    with pytest.raises(ValueError):platform.sync_local([("arbitrary",tmp_path)],NoEmbeddings())


def test_cli_parser_and_status(platform):
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    add_parser(sub)
    args=parser.parse_args(["platform","status"])
    assert run(args,platform.store,None,None)["index"]["documents"]==0
    args=parser.parse_args(["platform","sync"])
    with pytest.raises(ValueError):run(args,platform.store,None,None)


def test_readonly_fastapi_exposes_all_status(platform):
    app=FastAPI()
    attach_platform(app,platform.store.path)
    client=TestClient(app)
    html=client.get("/platform")
    assert html.status_code==200 and "Knowledge Platform 1.0" in html.text
    health=client.get("/api/platform/status")
    assert health.status_code==200 and health.json()["version"]=="1.0.0"
    assert client.get("/api/platform/audit").json()["valid"]
    assert client.get("/api/platform/evaluations").json()["items"]==[]
    assert client.post("/api/platform/status").status_code==405


def test_report_storage_boundaries(platform):
    with pytest.raises(ValueError):platform.save_report("other",{})
    platform.save_report("evaluation",{"status":"incomplete","dataset_sha256":"x","corpus":{"indexed":0,"configured":1}})
    assert len(platform.reports("evaluation"))==1
    with pytest.raises(ValueError):platform.reports("garbage")


def test_partial_cap_cannot_claim_full_sync(platform):
    c=FakeClient()
    result=platform.sync_web([{"url":URL1},{"url":URL2}],NoEmbeddings(),max_pages=1,client=c,delay=0)
    assert result["configured"]==2 and result["selected"]==1 and result["partial"]
    assert platform.store.source_runs(1)[0]["status"] == "partial"


def test_git_metadata_only_keeps_existing_vectors(platform):
    doc1=Document(doc_id="git-doc",source_id="firmware-oficial",title="lib/test.c",
                  url="https://github.com/flipperdevices/flipperzero-firmware/blob/aaaa/lib/test.c",
                  category="firmware",body="Furi API source unchanged",revision="aaaa")
    index_documents(platform.store,[doc1],NoEmbeddings())
    epoch=platform.store.vector_epoch()
    doc2=Document(**{**doc1.__dict__,"revision":"bbbb", "url":doc1.url.replace("aaaa", "bbbb")})
    assert platform.refresh_git_metadata(doc2)
    assert platform.store.vector_epoch()==epoch
    with platform.store.connect() as db:
        row=db.execute("SELECT url,revision FROM documents WHERE id='git-doc'").fetchone()
        assert row["revision"]=="bbbb" and "/bbbb/" in row["url"]
    assert not platform.refresh_git_metadata(Document(**{**doc2.__dict__,"body":"modified body"}))


def test_federated_discovery_stays_readonly(platform,monkeypatch):
    monkeypatch.setenv("RAG_EMBED_PROVIDER","none")
    from flipper_rag.platform_discovery import discover
    retriever=Retriever(platform.store,Embedder(Settings(embed_provider="none", ann_enabled=False)))
    _index_two(platform)
    result=discover("api_symbols.csv",retriever,platform.store.path,limit=3)
    assert result["groups"]["documents"]
    assert result["counts"]["documents"]>=1
    assert set(result["groups"])=={"documents","protocols","development","formats","firmware"}
    with pytest.raises(ValueError): discover("?",retriever,platform.store.path)


def test_federated_api_endpoint(platform,monkeypatch):
    monkeypatch.setenv("RAG_EMBED_PROVIDER","none")
    app=FastAPI();attach_platform(app,platform.store.path)
    client=TestClient(app)
    assert client.get("/api/platform/discover",params={"q":"api_symbols.csv"}).status_code==200
    assert client.get("/api/platform/discover",params={"q":"a"}).status_code==422


def test_internal_ingest_degrades_gracefully_without_optional_catalog(platform):
    out = platform.sync_internal(NoEmbeddings())
    assert set(out["sources"])=={"catalogo-protocolos","ontologia-protocolos","development-v08"}
    assert all('documents_seen' in value for value in out['sources'].values())
