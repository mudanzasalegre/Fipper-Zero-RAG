import json
from flipper_rag.audit import audit_catalog, audit_store
from flipper_rag.storage import Document, Store
from flipper_rag.chunking import chunk_text


def test_catalog_audit_passes(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"web":[{"url":"https://docs.flipper.net/zero"}], "git":[{"id":"firmware", "url":"https://github.com/flipperdevices/flipperzero-firmware.git","branch":"dev","max_files":500}]}))
    assert audit_catalog(path)["valid"]


def test_catalog_audit_rejects_external(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"web":[{"url":"https://example.com/x"}], "git":[]}))
    assert not audit_catalog(path)["valid"]


def test_index_audit(tmp_path):
    store = Store(tmp_path / "index.sqlite3")
    d = Document("abc","test","Title","https://example.com/","test","hello GPIO world")
    store.upsert(d,chunk_text(d.body))
    assert audit_store(store)["valid"]
    with store.connect() as con:
        con.execute("DELETE FROM chunks_fts")
    assert not audit_store(store)["valid"]
