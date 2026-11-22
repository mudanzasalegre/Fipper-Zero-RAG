"""SQLite provenance store, FTS5 index and optional vector embeddings."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Sequence
from .chunking import Chunk

@dataclass(frozen=True)
class Document:
    doc_id: str
    source_id: str
    title: str
    url: str
    category: str
    body: str
    revision: str = ""
    license: str = "See original source"
    trust: str = "official"


def document_id(source_id: str, path: str) -> str:
    return hashlib.sha256(f"{source_id}\0{path}".encode()).hexdigest()[:24]

class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=30000")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_schema(self):
        with self.connect() as c:
            c.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, title TEXT NOT NULL,
                    url TEXT NOT NULL, category TEXT NOT NULL, revision TEXT NOT NULL,
                    license TEXT NOT NULL, trust TEXT NOT NULL DEFAULT 'official', content_sha TEXT NOT NULL, indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_doc_source ON documents(source_id);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, heading TEXT NOT NULL, content TEXT NOT NULL,
                    line_start INTEGER NOT NULL, line_end INTEGER NOT NULL,
                    embedding TEXT, embedding_model TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    title, body, chunk_id UNINDEXED, tokenize='unicode61 remove_diacritics 2'
                );
            """)
            # Migration for databases created by the v0.1 prototype.
            cols = {row[1] for row in c.execute("PRAGMA table_info(documents)")}
            if "trust" not in cols:
                c.execute("ALTER TABLE documents ADD COLUMN trust TEXT NOT NULL DEFAULT 'official'")

    def upsert(self, doc: Document, chunks: Sequence[Chunk], vectors: Sequence[list[float]] | None = None,
               embedding_model: str = "", force: bool = False) -> str:
        digest = hashlib.sha256(doc.body.encode("utf-8")).hexdigest()
        if vectors is not None and len(vectors) != len(chunks):
            raise ValueError("Embedding count does not match chunks")
        with self.connect() as c:
            old = c.execute("SELECT content_sha,revision,url,category,title,trust,license FROM documents WHERE id=?", (doc.doc_id,)).fetchone()
            if old and old["content_sha"] == digest and old["revision"] == doc.revision and all(old[k] == getattr(doc,k) for k in ("url","category","title","trust","license")) and not force:
                return "unchanged"
            self._delete_chunks(c, doc.doc_id)
            c.execute("""INSERT INTO documents(id,source_id,title,url,category,revision,license,trust,content_sha)
                         VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                         source_id=excluded.source_id,title=excluded.title,url=excluded.url,
                         category=excluded.category,revision=excluded.revision,license=excluded.license,
                         trust=excluded.trust,
                         content_sha=excluded.content_sha,indexed_at=CURRENT_TIMESTAMP""",
                      (doc.doc_id, doc.source_id, doc.title, doc.url, doc.category,
                       doc.revision, doc.license, doc.trust, digest))
            for n, ch in enumerate(chunks):
                cid = f"{doc.doc_id}:{n}"
                v = json.dumps(vectors[n]) if vectors is not None else None
                c.execute("""INSERT INTO chunks(id,doc_id,ordinal,heading,content,line_start,line_end,embedding,embedding_model)
                             VALUES(?,?,?,?,?,?,?,?,?)""",
                          (cid, doc.doc_id, n, ch.heading, ch.content, ch.line_start, ch.line_end,
                           v, embedding_model if v else None))
                c.execute("INSERT INTO chunks_fts(title,body,chunk_id) VALUES(?,?,?)",
                          (doc.title + " " + ch.heading, ch.content, cid))
            return "updated" if old else "added"

    @staticmethod
    def _delete_chunks(c: sqlite3.Connection, doc_id: str):
        c.execute("DELETE FROM chunks_fts WHERE chunk_id IN (SELECT id FROM chunks WHERE doc_id=?)", (doc_id,))
        c.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))

    def prune_source(self, source_id: str, keep: set[str]) -> int:
        with self.connect() as c:
            old_ids = [r[0] for r in c.execute("SELECT id FROM documents WHERE source_id=?", (source_id,))]
            removed = 0
            for did in old_ids:
                if did not in keep:
                    self._delete_chunks(c, did)
                    c.execute("DELETE FROM documents WHERE id=?", (did,))
                    removed += 1
            return removed

    def has_current(self, doc: Document, *, force=False) -> bool:
        if force:
            return False
        with self.connect() as c:
            row = c.execute("SELECT content_sha,revision,url,category,title,trust,license FROM documents WHERE id=?", (doc.doc_id,)).fetchone()
            return bool(row and row["content_sha"] == hashlib.sha256(doc.body.encode()).hexdigest()
                        and row["revision"] == doc.revision
                        and all(row[k] == getattr(doc,k) for k in ("url","category","title","trust","license")))

    def lexical(self, query: str, limit: int = 60) -> list[str]:
        import re
        tokens = re.findall(r"[^\W_][\w-]*", query, re.UNICODE)[:15]
        if not tokens:
            return []
        fts_query = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)
        with self.connect() as c:
            rows = c.execute("""SELECT chunk_id FROM chunks_fts
                                WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts, 2.8, 1.0) LIMIT ?""",
                             (fts_query, limit)).fetchall()
        return [r[0] for r in rows]

    def embedded_rows(self, model: str):
        with self.connect() as c:
            return [(r["id"], json.loads(r["embedding"])) for r in c.execute(
                "SELECT id,embedding FROM chunks WHERE embedding IS NOT NULL AND embedding_model=?", (model,))]

    def iter_embeddings(self, model: str):
        """Stream vector rows instead of materializing the full embedding corpus."""
        with self.connect() as c:
            for r in c.execute("SELECT id,embedding FROM chunks WHERE embedding IS NOT NULL AND embedding_model=?", (model,)):
                try:
                    vector = json.loads(r["embedding"])
                except (TypeError, ValueError):
                    continue
                if isinstance(vector, list) and vector:
                    yield r["id"], vector

    def missing_embeddings(self, model: str, limit: int = 500):
        with self.connect() as c:
            return [(r["id"], r["content"]) for r in c.execute("""SELECT id, content FROM chunks
                WHERE embedding IS NULL OR embedding_model!=? LIMIT ?""", (model, limit))]

    def update_embeddings(self, ids: Sequence[str], vectors: Sequence[list[float]], model: str):
        if len(ids) != len(vectors):
            raise ValueError("Embedding count mismatch")
        with self.connect() as c:
            c.executemany("UPDATE chunks SET embedding=?,embedding_model=? WHERE id=?",
                          [(json.dumps(v), model, cid) for cid, v in zip(ids, vectors)])

    def get_chunks(self, ids: Sequence[str]) -> dict[str, dict]:
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        with self.connect() as c:
            rows = c.execute(f"""SELECT c.id,c.content,c.heading,c.line_start,c.line_end,
                 d.title,d.url,d.category,d.source_id,d.revision,d.license,d.trust
                 FROM chunks c JOIN documents d ON c.doc_id=d.id
                 WHERE c.id IN ({marks})""", tuple(ids)).fetchall()
        return {r["id"]: dict(r) for r in rows}

    def stats(self) -> dict:
        with self.connect() as c:
            d = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            ch = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            emb = c.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
            sources = [dict(r) for r in c.execute("""SELECT source_id, category, COUNT(*) AS documents
                            FROM documents GROUP BY source_id,category ORDER BY source_id""")]
        return {"documents": d, "chunks": ch, "embedded_chunks": emb, "sources": sources}
