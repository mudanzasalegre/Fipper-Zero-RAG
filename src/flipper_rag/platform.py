"""v1.0 integrated knowledge platform: official incremental ingestion and provenance.

The SQLite database is the local source of truth.  HTTP conditional requests save
bandwidth; content hashes, rather than ETags alone, decide whether to reindex.
The web API is read-only. No code in this module controls Flipper hardware.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import time
from typing import Callable, Iterable
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from .sources import (ALLOWED_DOC_HOSTS, USER_AGENT, _SameHostRedirectHandler,
                      _canonical_doc_link, TextHTMLParser, git_documents,
                      index_documents, local_documents, load_catalog)
from .storage import Document, Store, document_id

MAX_TEXT_BYTES = 2_000_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    # Reject URL-encoded traversal, alternate ports, embedded credentials and
    # backslashes before URL joining can normalize suspicious segments.
    segments = urllib.parse.unquote(urllib.parse.unquote(parsed.path)).replace("\\", "/").split("/")
    if (parsed.username or parsed.password or parsed.port is not None
            or any(part in {".", ".."} for part in segments)
            or "%2f" in parsed.path.lower() or "\\" in parsed.path):
        raise ValueError("Unsafe official URL")
    canonical = _canonical_doc_link(url, url)
    if canonical != url or not canonical:
        raise ValueError("Source must be a canonical official HTTPS documentation URL")
    return canonical


@dataclass(frozen=True)
class PageResult:
    status: str  # modified | not-modified
    title: str
    body: str
    etag: str = ""
    last_modified: str = ""
    links: tuple[str, ...] = ()


class OfficialHTTPClient:
    """Same-host HTTPS fetcher with robots, validators and response-size limits."""

    def __init__(self):
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._opener = urllib.request.build_opener(_SameHostRedirectHandler())

    def _allowed(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(_canonical(url))
        origin = f"https://{parsed.hostname}"
        if origin not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(origin + "/robots.txt")
            try:
                rp.read()
            except Exception as exc:
                raise RuntimeError(f"Could not verify robots policy for {origin}") from exc
            self._robots[origin] = rp
        if not self._robots[origin].can_fetch(USER_AGENT, url):
            raise PermissionError("robots.txt disallows access")

    def fetch(self, url: str, previous: dict | None = None, *, force: bool = False) -> PageResult:
        self._allowed(url)
        headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
        if previous and not force:
            if previous.get("etag"):
                headers["If-None-Match"] = previous["etag"]
            if previous.get("last_modified"):
                headers["If-Modified-Since"] = previous["last_modified"]
        request = urllib.request.Request(url, headers=headers)
        try:
            response = self._opener.open(request, timeout=25)
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and previous and previous.get("body"):
                return PageResult("not-modified", previous["title"], previous["body"],
                                  previous.get("etag", ""), previous.get("last_modified", ""))
            raise
        with response:
            final = urllib.parse.urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != urllib.parse.urlsplit(url).hostname:
                raise ValueError("Cross-host or non-HTTPS redirect blocked")
            if "text/html" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("Only HTML documentation is supported")
            raw = response.read(MAX_TEXT_BYTES + 1)
            if len(raw) > MAX_TEXT_BYTES:
                raise ValueError("Official page exceeds 2 MB text limit")
            etag = response.headers.get("ETag", "")[:300]
            modified = response.headers.get("Last-Modified", "")[:150]
        parser = TextHTMLParser()
        parser.feed(raw.decode("utf-8", "replace"))
        text = parser.text()
        if len(text) < 100:
            raise ValueError("Official page has insufficient extractable text")
        return PageResult("modified", parser.title.strip() or urllib.parse.urlsplit(url).path,
                          text, etag, modified, tuple(parser.links))


class Platform:
    def __init__(self, store: Store):
        self.store = store
        self._init_schema()

    def _init_schema(self) -> None:
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS platform_web_cache (
                    url TEXT PRIMARY KEY,
                    title TEXT NOT NULL, body TEXT NOT NULL,
                    etag TEXT NOT NULL DEFAULT '', last_modified TEXT NOT NULL DEFAULT '',
                    content_sha TEXT NOT NULL, checked_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS platform_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK(kind IN ('evaluation','synchronization')),
                    created_at TEXT NOT NULL,
                    report_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_platform_reports_kind
                    ON platform_reports(kind,id DESC);
            """)

    def get_cached_page(self, url: str) -> dict | None:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM platform_web_cache WHERE url=?", (url,)).fetchone()
            return dict(row) if row else None

    def cache_page(self, url: str, result: PageResult, *, previous: dict | None = None) -> None:
        now = _now()
        sha = hashlib.sha256(result.body.encode("utf-8")).hexdigest()
        with self.store.connect() as db:
            db.execute("""INSERT INTO platform_web_cache
                (url,title,body,etag,last_modified,content_sha,checked_at,fetched_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,body=excluded.body,etag=excluded.etag,
                last_modified=excluded.last_modified,content_sha=excluded.content_sha,
                checked_at=excluded.checked_at,fetched_at=excluded.fetched_at""",
                (url, result.title, result.body, result.etag, result.last_modified, sha,
                 now, (previous or {}).get("fetched_at", now) if result.status == "not-modified" else now))

    def save_report(self, kind: str, report: dict) -> None:
        if kind not in {"evaluation", "synchronization"}:
            raise ValueError("Invalid report kind")
        payload = json.dumps(report, ensure_ascii=False, sort_keys=True)
        if len(payload) > 1_000_000:
            raise ValueError("Report too large")
        with self.store.connect() as db:
            db.execute("INSERT INTO platform_reports(kind,created_at,report_json) VALUES(?,?,?)",
                       (kind, _now(), payload))

    def reports(self, kind: str = "evaluation", limit: int = 5) -> list[dict]:
        if kind not in {"evaluation", "synchronization"}:
            raise ValueError("Invalid report kind")
        with self.store.connect() as db:
            rows = db.execute("""SELECT id,created_at,report_json FROM platform_reports
                               WHERE kind=? ORDER BY id DESC LIMIT ?""",
                              (kind, max(1, min(limit, 25)))).fetchall()
        return [{"id": row["id"], "at": row["created_at"],
                 "report": json.loads(row["report_json"])} for row in rows]

    def sync_web(self, specs: Iterable[dict], embedder, *, max_pages: int = 100,
                 delay: float = 0.35, force: bool = False,
                 client: OfficialHTTPClient | None = None) -> dict:
        """Sync a fixed list of official sources. Never prune on partial fetch failures."""
        if max_pages < 1 or max_pages > 500:
            raise ValueError("max_pages must be between 1 and 500")
        if not 0 <= delay <= 30:
            raise ValueError("delay must be between 0 and 30 seconds")
        client = client or OfficialHTTPClient()
        unique: dict[str, dict] = {}
        for spec in specs:
            url = _canonical(spec["url"])
            if url not in unique:
                unique[url] = spec
        selected = list(unique.items())[:max_pages]
        counts = {"source": "web-oficial", "selected": len(selected), "configured": len(unique),
                  "retrieved": 0, "http_modified": 0, "http_304": 0, "added": 0,
                  "updated": 0, "unchanged": 0, "failed": 0, "documents_seen": 0,
                  "pages": [], "at": _now()}
        for url, spec in selected:
            previous = self.get_cached_page(url)
            try:
                result = client.fetch(url, previous, force=force)
                if result.status not in {"modified", "not-modified"} or not result.body.strip():
                    raise ValueError("Fetcher returned an invalid page")
                self.cache_page(url, result, previous=previous)
                counts["http_304" if result.status == "not-modified" else "http_modified"] += 1
                doc = Document(doc_id=document_id("web-oficial", url), source_id="web-oficial",
                               title=spec.get("title") or result.title, url=url,
                               category=spec.get("category", "manual"), body=result.body,
                               trust="official", license="Copyright upstream; index locally for reference")
                changes = index_documents(self.store, [doc], embedder, force=force)
                for key in ("added", "updated", "unchanged", "documents_seen", "failed"):
                    counts[key] += changes.get(key, 0)
                counts["retrieved"] += 1
                counts["pages"].append({"url": url, "status": result.status,
                                        "sha256": hashlib.sha256(result.body.encode()).hexdigest()})
            except Exception as exc:
                counts["failed"] += 1
                # Store only an error type in a public-ready report (no raw bodies or secrets).
                counts["pages"].append({"url": url, "status": "error", "error": type(exc).__name__})
            if delay:
                time.sleep(delay)
        counts["partial"] = counts["failed"] > 0 or len(selected) < len(unique)
        self.store.record_sync("web-oficial", {**counts,
                                              "crawl_limit_reached": len(selected) < len(unique)})
        self.save_report("synchronization", counts)
        return counts

    def refresh_git_metadata(self, doc: Document) -> bool:
        """Move a pinned Git citation to the newest SHA without regenerating vectors.

        Only safe when document identity, body digest and FTS title are identical.
        Changing a title requires rebuilding FTS and cannot use this path.
        """
        sha = hashlib.sha256(doc.body.encode("utf-8")).hexdigest()
        with self.store.connect() as db:
            row = db.execute("SELECT content_sha,title FROM documents WHERE id=?", (doc.doc_id,)).fetchone()
            if row is None or row["content_sha"] != sha or row["title"] != doc.title:
                return False
            db.execute("""UPDATE documents SET source_id=?,url=?,category=?,revision=?,
                     license=?,trust=?,firmware_version=?,firmware_channel=?,
                     indexed_at=CURRENT_TIMESTAMP WHERE id=?""",
                     (doc.source_id,doc.url,doc.category,doc.revision,doc.license,doc.trust,
                      doc.firmware_version,doc.firmware_channel,doc.doc_id))
        return True

    def sync_git(self, catalog: dict, embedder, cache_dir: Path, *, with_code: bool = False,
                 include_community: bool = False, force: bool = False) -> dict:
        """Use the existing audited, allowlisted Git collector with hash-based updates."""
        if include_community:
            raise ValueError("Community sources require explicit legacy sync --community")
        reports: dict[str, dict] = {}
        for spec in catalog["git"]:
            if spec.get("tier", "official") != "official":
                continue
            result = {"added":0,"updated":0,"unchanged":0,"metadata_only":0,
                      "documents_seen":0,"failed":0,"not_embedded":0}
            try:
                for doc in git_documents(spec, cache_dir, include_code=with_code):
                    if not force and self.refresh_git_metadata(doc):
                        result["metadata_only"] += 1
                        result["documents_seen"] += 1
                        continue
                    part = index_documents(self.store, [doc], embedder, force=force)
                    for key in ("added","updated","unchanged","documents_seen","failed","not_embedded"):
                        result[key] += part.get(key,0)
            except Exception as exc:
                result["error"] = type(exc).__name__
                result["failed"] += 1
            self.store.record_sync(spec["id"], result)
            reports[spec["id"]] = result
        data = {"at": _now(), "sources": reports, "with_code": with_code}
        self.save_report("synchronization", data)
        return data

    def sync_local(self, roots: Iterable[tuple[str, Path]], embedder, *, force: bool = False) -> dict:
        out: dict[str, dict] = {}
        for name, path in roots:
            # Never recursively index the complete home directory by accident.
            if path.name not in {"starter", "protocols", "protocol_lab", "platform"}:
                raise ValueError("Only explicitly curated knowledge/ subfolders are accepted")
            try:
                result = index_documents(self.store,
                                         local_documents(path, source_id=f"integrated-{name}", category="guide"),
                                         embedder, force=force)
            except Exception as exc:
                result = {"error": type(exc).__name__, "failed": 1, "documents_seen": 0}
            self.store.record_sync(f"integrated-{name}", result)
            out[name] = result
        report = {"at": _now(), "sources": out}
        self.save_report("synchronization", report)
        return report

    def sync_internal(self, embedder, *, force: bool = False) -> dict:
        """Add curated v0.5/v0.6/v0.8 source-backed summaries to the shared RAG.

        These are *local editorial summaries*, never claimed as official text.
        Firmware v0.7 snapshots are version-specific and must be indexed via
        the explicit `firmware index --index-rag` command separately.
        """
        result = {}
        generators = (
            ("catalogo-protocolos", lambda: __import__("flipper_rag.protocols",fromlist=["protocol_documents"]).protocol_documents()),
            ("ontologia-protocolos", lambda: __import__("flipper_rag.protocol_intelligence",fromlist=["get_intelligence"]).get_intelligence().documents()),
            ("development-v08", lambda: __import__("flipper_rag.development",fromlist=["development_documents"]).development_documents()),
        )
        for source_id, loader in generators:
            try:
                rows = index_documents(self.store, loader(), embedder, force=force)
            except (ImportError, ValueError, OSError) as exc:
                rows = {"error": type(exc).__name__, "failed": 1, "documents_seen": 0}
            self.store.record_sync(source_id, rows)
            result[source_id] = rows
        report = {"at": _now(), "sources": result}
        self.save_report("synchronization", report)
        return report

    def status(self, *, stale_days: int = 14) -> dict:
        if stale_days < 1 or stale_days > 3650:
            raise ValueError("stale_days out of bounds")
        now = datetime.now(timezone.utc)
        with self.store.connect() as db:
            docs = [dict(r) for r in db.execute("""SELECT source_id,trust,category,
                   COUNT(*) AS documents, MAX(indexed_at) AS indexed_at,
                   SUM(CASE WHEN firmware_version != '' THEN 1 ELSE 0 END) AS versioned
                   FROM documents GROUP BY source_id,trust,category
                   ORDER BY documents DESC""")]
            cache = db.execute("""SELECT COUNT(*) pages, MAX(checked_at) latest_checked,
                   SUM(CASE WHEN checked_at >= datetime('now','-14 days') THEN 1 ELSE 0 END) recent
                   FROM platform_web_cache""").fetchone()
        # Make the absence of configured official documents visible. A missing
        # sources.json is not silently treated as a fully indexed catalog.
        try:
            catalog = load_catalog(Path("sources.json"))
            configured_urls = {_canonical(row["url"]) for row in catalog["web"]}
            configured = len(configured_urls)
            configured_repos = len([r for r in catalog["git"] if r.get("tier", "official") == "official"])
        except (OSError, ValueError, KeyError, TypeError):
            configured = None
            configured_urls = set()
            configured_repos = None
        with self.store.connect() as db:
            official_urls = {r[0] for r in db.execute("""SELECT DISTINCT url FROM documents
                WHERE source_id='web-oficial' AND trust='official'""")}
            indexed_official_pages = len(official_urls)
            indexed_seeds = len(configured_urls & official_urls)
        runs = self.store.source_runs(100)
        recent = {}
        for run in runs:
            if run["source_id"] not in recent:
                recent[run["source_id"]] = run
        source_health = []
        for source in sorted({d["source_id"] for d in docs} | set(recent)):
            row = recent.get(source)
            age = None
            if row:
                try:
                    at = datetime.strptime(row["finished_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    age = round((now-at).total_seconds()/86400, 2)
                except ValueError:
                    pass
            state = "unobserved" if age is None else ("error" if row["status"] == "error" else (
                    "stale" if age > stale_days else row["status"]))
            source_health.append({"id":source, "state":state, "age_days":age,
                                  "documents":sum(r["documents"] for r in docs if r["source_id"] == source),
                                  "last_run":row["finished_at"] if row else None,
                                  "failed_last_run":row["failed"] if row else None})
        return {"version": "1.0.0", "at": _now(), "stale_days": stale_days,
                "index": self.store.stats(), "source_health": source_health,
                "trust": {k:sum(d["documents"] for d in docs if d["trust"] == k)
                          for k in ("official", "community", "local")},
                "versioned_documents": sum(d["versioned"] for d in docs),
                "web_cache": {"pages": cache["pages"], "last_checked": cache["latest_checked"]},
                "catalog_coverage": {"configured_web_pages": configured,
                                     "indexed_official_pages": indexed_official_pages,
                                     "indexed_configured_seeds": indexed_seeds,
                                     "configured_official_repositories": configured_repos,
                                     "fraction": indexed_seeds / configured if configured else None},
                "latest_evaluation": (self.reports("evaluation", 1) or [None])[0],
                "latest_sync": (self.reports("synchronization", 1) or [None])[0],
                "modules": [
                    {"id":"rag","name":"Asistente RAG", "href":"/"},
                    {"id":"ontology","name":"Protocol Intelligence", "href":"/ontology"},
                    {"id":"firmware","name":"Firmware Knowledge Graph", "href":"/firmware"},
                    {"id":"development","name":"Development Assistant", "href":"/development"},
                    {"id":"lab","name":"Protocol Lab", "href":"/lab"},
                ]}

    def audit(self, *, stale_days: int = 14) -> dict:
        state = self.status(stale_days=stale_days)
        with self.store.connect() as db:
            bad = db.execute("SELECT COUNT(*) FROM chunks c LEFT JOIN documents d ON c.doc_id=d.id WHERE d.id IS NULL").fetchone()[0]
            missing = db.execute("SELECT COUNT(*) FROM chunks c LEFT JOIN chunks_fts f ON f.chunk_id=c.id WHERE f.chunk_id IS NULL").fetchone()[0]
            counts = db.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        return {"valid": bad == 0 and missing == 0 and counts == state["index"]["chunks"],
                "dangling_chunks":bad,"missing_fts_rows":missing,
                "fts_rows":counts,"stale_sources":[s["id"] for s in state["source_health"] if s["state"] == "stale"],
                "unobserved_sources":[s["id"] for s in state["source_health"] if s["state"] == "unobserved"],
                "health":state}
