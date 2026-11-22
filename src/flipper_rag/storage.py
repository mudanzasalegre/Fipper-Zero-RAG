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
    firmware_version: str = ""
    firmware_channel: str = "unversioned"


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
                    license TEXT NOT NULL, trust TEXT NOT NULL DEFAULT 'official',
                    firmware_version TEXT NOT NULL DEFAULT '', firmware_channel TEXT NOT NULL DEFAULT 'unversioned',
                    content_sha TEXT NOT NULL, indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_doc_source ON documents(source_id);
                CREATE INDEX IF NOT EXISTS idx_doc_category_trust ON documents(category,trust);
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
                CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                INSERT OR IGNORE INTO index_meta(key,value) VALUES('vector_epoch',0);
                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    seen INTEGER NOT NULL DEFAULT 0,
                    added INTEGER NOT NULL DEFAULT 0,
                    updated INTEGER NOT NULL DEFAULT 0,
                    removed INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL CHECK(status IN ('ok', 'partial', 'error'))
                );
                CREATE INDEX IF NOT EXISTS idx_runs_source ON sync_runs(source_id, id DESC);
            """)
            # Migration for databases created by the v0.1 prototype.
            cols = {row[1] for row in c.execute("PRAGMA table_info(documents)")}
            if "trust" not in cols:
                c.execute("ALTER TABLE documents ADD COLUMN trust TEXT NOT NULL DEFAULT 'official'")
            if "firmware_version" not in cols:
                c.execute("ALTER TABLE documents ADD COLUMN firmware_version TEXT NOT NULL DEFAULT ''")
            if "firmware_channel" not in cols:
                c.execute("ALTER TABLE documents ADD COLUMN firmware_channel TEXT NOT NULL DEFAULT 'unversioned'")
            c.execute("CREATE INDEX IF NOT EXISTS idx_documents_firmware ON documents(firmware_version,firmware_channel)")

    def upsert(self, doc: Document, chunks: Sequence[Chunk], vectors: Sequence[list[float]] | None = None,
               embedding_model: str = "", force: bool = False) -> str:
        digest = hashlib.sha256(doc.body.encode("utf-8")).hexdigest()
        if vectors is not None and len(vectors) != len(chunks):
            raise ValueError("Embedding count does not match chunks")
        with self.connect() as c:
            old = c.execute("SELECT content_sha,revision,url,category,title,trust,license,firmware_version,firmware_channel FROM documents WHERE id=?", (doc.doc_id,)).fetchone()
            if old and old["content_sha"] == digest and old["revision"] == doc.revision and all(old[k] == getattr(doc,k) for k in ("url","category","title","trust","license","firmware_version","firmware_channel")) and not force:
                return "unchanged"
            self._delete_chunks(c, doc.doc_id)
            c.execute("""INSERT INTO documents(id,source_id,title,url,category,revision,license,trust,firmware_version,firmware_channel,content_sha)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                         source_id=excluded.source_id,title=excluded.title,url=excluded.url,
                         category=excluded.category,revision=excluded.revision,license=excluded.license,
                         trust=excluded.trust,firmware_version=excluded.firmware_version,
                         firmware_channel=excluded.firmware_channel,
                         content_sha=excluded.content_sha,indexed_at=CURRENT_TIMESTAMP""",
                      (doc.doc_id, doc.source_id, doc.title, doc.url, doc.category,
                       doc.revision, doc.license, doc.trust, doc.firmware_version, doc.firmware_channel, digest))
            for n, ch in enumerate(chunks):
                cid = f"{doc.doc_id}:{n}"
                v = json.dumps(vectors[n]) if vectors is not None else None
                c.execute("""INSERT INTO chunks(id,doc_id,ordinal,heading,content,line_start,line_end,embedding,embedding_model)
                             VALUES(?,?,?,?,?,?,?,?,?)""",
                          (cid, doc.doc_id, n, ch.heading, ch.content, ch.line_start, ch.line_end,
                           v, embedding_model if v else None))
                c.execute("INSERT INTO chunks_fts(title,body,chunk_id) VALUES(?,?,?)",
                          (doc.title + " " + ch.heading, ch.content, cid))
            self._bump_vector_epoch(c)
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
            if removed:
                self._bump_vector_epoch(c)
            return removed

    def has_current(self, doc: Document, *, force=False) -> bool:
        if force:
            return False
        with self.connect() as c:
            row = c.execute("SELECT content_sha,revision,url,category,title,trust,license,firmware_version,firmware_channel FROM documents WHERE id=?", (doc.doc_id,)).fetchone()
            return bool(row and row["content_sha"] == hashlib.sha256(doc.body.encode()).hexdigest()
                        and row["revision"] == doc.revision
                        and all(row[k] == getattr(doc,k) for k in ("url","category","title","trust","license","firmware_version","firmware_channel")))

    @staticmethod
    def _filter_clause(category: str | None, trust: str | None, source_id: str | None,
                       firmware_version: str | None = None,
                       version_policy: str = 'include-unversioned') -> tuple[str, list[str]]:
        filters, args = [], []
        for field, value in (("category", category), ("trust", trust), ("source_id", source_id)):
            if value:
                filters.append(f"d.{field}=?")
                args.append(value)
        if firmware_version:
            from .versioning import normalize_version
            version = normalize_version(firmware_version)
            if version_policy not in {'strict', 'include-unversioned'}:
                raise ValueError('Invalid firmware version policy')
            if version_policy == 'strict':
                filters.append("d.firmware_version=?")
            else:
                # Only exact releases or explicitly unversioned sources. Never
                # treat a moving dev branch as validated for a stable release.
                filters.append("(d.firmware_version=? OR (d.firmware_version='' AND d.firmware_channel='unversioned'))")
            args.append(version)
        return "".join(" AND " + clause for clause in filters), args

    @staticmethod
    def _bump_vector_epoch(con: sqlite3.Connection):
        con.execute("UPDATE index_meta SET value=value+1 WHERE key='vector_epoch'")

    def vector_epoch(self) -> int:
        with self.connect() as c:
            return int(c.execute("SELECT value FROM index_meta WHERE key='vector_epoch'").fetchone()[0])

    def eligible_chunk_ids(self, ids: Sequence[str], *, category: str | None = None,
                           trust: str | None = None, source_id: str | None = None,
                           firmware_version: str | None = None,
                           version_policy: str = 'include-unversioned') -> set[str]:
        if not ids:
            return set()
        extra, params = self._filter_clause(category, trust, source_id, firmware_version, version_policy)
        result: set[str] = set()
        # Avoid SQLite variable-number limits, which vary by installed version.
        with self.connect() as c:
            for n in range(0, len(ids), 500):
                batch = ids[n:n+500]
                marks = ','.join('?' for _ in batch)
                for row in c.execute(f"SELECT c.id FROM chunks c JOIN documents d ON c.doc_id=d.id WHERE c.id IN ({marks})" + extra, (*batch, *params)):
                    result.add(row[0])
        return result

    def lexical(self, query: str, limit: int = 60, *, category: str | None = None,
                trust: str | None = None, source_id: str | None = None,
                firmware_version: str | None = None,
                version_policy: str = "include-unversioned") -> list[str]:
        import re
        # FTS5 parameter binding prevents MATCH operator injection. Keep C symbols,
        # snake_case, and accented words intact for exact technical searches.
        stopwords = {"que", "qué", "como", "cómo", "cual", "cuál", "cuales", "cuáles",
                     "el", "la", "los", "las", "lo", "de", "del", "y", "o", "a",
                     "en", "para", "por", "con", "sin", "sobre", "se", "su", "un", "una",
                     "es", "son", "está", "esta", "funciona", "funcionan", "funcionar",
                     "usar", "hacer", "hay", "the", "what", "how", "is", "are", "to",
                     "for", "and", "in", "of", "does", "do", "with", "from", "can",
                     "my", "me", "i", "it", "on", "al", "le", "puedo", "puede",
                     "flipper", "zero", "implica", "implicar", "reglas", "sirve", "tipos"}
        tokens = [word for word in re.findall(r"[^\W_][\w-]*", query, re.UNICODE)
                  if len(word) > 1 and word.casefold() not in stopwords][:16]
        if not tokens:
            return []
        fts_query = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)
        extra, params = self._filter_clause(category, trust, source_id, firmware_version, version_policy)
        with self.connect() as c:
            rows = c.execute("""SELECT chunks_fts.chunk_id, chunks_fts.title, chunks_fts.body FROM chunks_fts
                JOIN chunks c ON c.id=chunks_fts.chunk_id
                JOIN documents d ON d.id=c.doc_id
                WHERE chunks_fts MATCH ?""" + extra + """
                ORDER BY bm25(chunks_fts, 3.0, 1.0) LIMIT ?""",
                (fts_query, *params, max(1, min(limit, 500)))).fetchall()
        # Require more than a single coincidental generic word when the user
        # supplied a multi-concept question. This reduces unsupported answers.
        # Match only on the same chunk (not on unrelated text in a document).
        if len(set(tokens)) >= 3:
            import unicodedata
            def fold(value):
                value = unicodedata.normalize("NFKD", value.casefold())
                return "".join(char for char in value if not unicodedata.combining(char))
            needle = [fold(t) for t in dict.fromkeys(tokens)]
            rows = [r for r in rows if sum(t in fold(r[1] + " " + r[2]) for t in needle) >= 2]
        return [r[0] for r in rows]

    def embedded_rows(self, model: str):
        with self.connect() as c:
            return [(r["id"], json.loads(r["embedding"])) for r in c.execute(
                "SELECT id,embedding FROM chunks WHERE embedding IS NOT NULL AND embedding_model=?", (model,))]

    def iter_embeddings(self, model: str, *, category: str | None = None,
                        trust: str | None = None, source_id: str | None = None,
                        firmware_version: str | None = None, version_policy: str = "include-unversioned"):
        """Stream only relevant vectors for the requested filters."""
        extra, params = self._filter_clause(category, trust, source_id, firmware_version, version_policy)
        with self.connect() as c:
            for r in c.execute("""SELECT c.id,c.embedding FROM chunks c
                JOIN documents d ON d.id=c.doc_id
                WHERE c.embedding IS NOT NULL AND c.embedding_model=?""" + extra,
                (model, *params)):
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
            if ids:
                self._bump_vector_epoch(c)

    def get_chunks(self, ids: Sequence[str]) -> dict[str, dict]:
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        with self.connect() as c:
            rows = c.execute(f"""SELECT c.id,c.content,c.heading,c.line_start,c.line_end,
                 d.title,d.url,d.category,d.source_id,d.revision,d.license,d.trust,d.indexed_at,c.doc_id,d.firmware_version,d.firmware_channel
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
        return {"documents": d, "chunks": ch, "embedded_chunks": emb,
                "vector_epoch": self.vector_epoch(),
                "embedding_coverage": round(emb / ch, 4) if ch else 0,
                "sources": sources}

    def record_sync(self, source_id: str, result: dict, *, removed: int = 0) -> None:
        status = "error" if result.get("error") else (
            "partial" if (result.get("failed", 0) or result.get("web_fetch_failed", 0)
                          or result.get("crawl_limit_reached", False)) else "ok")
        with self.connect() as c:
            c.execute("""INSERT INTO sync_runs(source_id, seen, added, updated, removed, failed, status)
                         VALUES(?,?,?,?,?,?,?)""", (source_id, result.get("documents_seen", 0),
                            result.get("added", 0), result.get("updated", 0), removed,
                            result.get("failed", 0) + result.get("web_fetch_failed", 0)
                            + int(bool(result.get("error"))), status))

    def source_runs(self, limit: int = 30) -> list[dict]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("""SELECT source_id,finished_at,seen,added,updated,removed,failed,status
                       FROM sync_runs ORDER BY id DESC LIMIT ?""", (max(1, min(limit, 200)),))]
