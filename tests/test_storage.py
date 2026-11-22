from flipper_rag.storage import Document, Store, document_id
from flipper_rag.chunking import chunk_text
from flipper_rag.retrieval import Retriever, cosine
from flipper_rag.config import Settings
from flipper_rag.models import Embedder


def test_index_search_update_delete(tmp_path):
    db = Store(tmp_path / "rag.sqlite3")
    d = Document(document_id("test", "nfc"), "test", "NFC y lector", "https://example.org/nfc",
                 "nfc", "# NFC\nEl lector NFC utiliza una antena de 13.56 MHz.")
    assert db.upsert(d, chunk_text(d.body)) == "added"
    assert db.stats()["documents"] == 1
    assert db.lexical("antena MHz")
    assert db.upsert(d, chunk_text(d.body)) == "unchanged"
    settings = Settings()
    result = Retriever(db, Embedder(settings)).search("NFC antena MHz", 3)
    assert len(result["results"]) == 1
    assert result["results"][0]["category"] == "nfc"
    assert db.prune_source("test", set()) == 1
    assert db.stats()["chunks"] == 0
    assert not db.lexical("antena")


def test_vectors_and_hybrid(tmp_path, monkeypatch):
    db = Store(tmp_path / "v.sqlite3")
    d = Document("abc", "demo", "GPIO hardware", "https://example.org/gpio", "gpio", "# GPIO\nLED pin GPIO")
    db.upsert(d, chunk_text(d.body), [[1.0, 0.0]], "demo-embed")
    assert len(db.embedded_rows("demo-embed")) == 1
    assert cosine([1,0], [1,0]) == 1.0
    assert cosine([1,0], [0,1]) == 0.0
    assert len(db.missing_embeddings("other")) == 1
    db.update_embeddings(["abc:0"], [[0.0, 1.0]], "other")
    assert not db.missing_embeddings("other")


def test_documents_are_incremental(tmp_path):
    db = Store(tmp_path / "x.sqlite3")
    original = Document("id", "test", "A", "https://example.org", "firmware", "hello")
    db.upsert(original, chunk_text(original.body))
    assert db.has_current(original)
    changed = Document("id", "test", "A", "https://example.org", "firmware", "hello again")
    assert not db.has_current(changed)
    assert db.upsert(changed, chunk_text(changed.body)) == "updated"
    assert db.stats()["chunks"] == 1
