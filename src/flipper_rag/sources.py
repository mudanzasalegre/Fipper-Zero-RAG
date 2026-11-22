"""Official-source ingestion with provenance, size limits and safe Git subprocess calls."""
from __future__ import annotations
from html.parser import HTMLParser
from pathlib import Path
from collections import deque
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from typing import Iterable
from .chunking import chunk_text
from .models import Embedder, ModelUnavailable
from .storage import Document, Store, document_id

USER_AGENT = "FlipperZeroRAG/0.1 (local documentation indexing)"
ALLOWED_DOC_HOSTS = {"docs.flipper.net", "developer.flipper.net"}
# Explicitly reviewed upstream repositories. Users must opt into community firmware.
ALLOWED_GIT_REPOS = {
    "flipperdevices/flipperzero-firmware", "flipperdevices/flipper-application-catalog",
    "flipperdevices/flipperzero-ufbt", "flipperdevices/flipperzero-protobuf",
    "flipperdevices/qflipper", "flipperdevices/flipperzero-good-faps",
    "djsime1/awesome-flipperzero", "darkflippers/unleashed-firmware",
    "next-flip/momentum-firmware",
}
SUPPORTED_LOCAL_SUFFIXES = {".md", ".txt", ".rst", ".c", ".h", ".cpp", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".proto", ".fam"}
BLOCKED_NAME_PARTS = {".git", ".venv", "node_modules", "__pycache__", "secrets", "credentials", "private_keys", "dumps", "captures", "backups", "private", "keyfiles"}


class TextHTMLParser(HTMLParser):
    EXCLUDE = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "button"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skipped: list[str] = []
        self._skip_depth = 0
        self.heading = None
        self.out: list[str] = []
        self.title = ""
        self.in_title = False
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag in self.EXCLUDE:
            self._skip_depth = 1
            return
        if tag == "title":
            self.in_title = True
        if re.fullmatch(r"h[1-6]", tag):
            self.heading = int(tag[1])
            self.out.append("\n" + "#" * self.heading + " ")
        elif tag in {"p", "li", "div", "pre", "section", "article", "br", "tr"}:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self.in_title = False
        if re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n")
            self.heading = None

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self.in_title:
            self.title += data
        text = re.sub(r"[ \t\f\v]+", " ", data)
        if text.strip():
            self.out.append(text)

    def text(self) -> str:
        raw = "".join(self.out)
        lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
        result = []
        previous = ""
        for line in lines:
            if line and line != previous:
                result.append(line)
                previous = line
        return "\n".join(result)


def read_web(url: str, robot_cache: dict) -> tuple[str, str, list[str]]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOC_HOSTS:
        raise ValueError("Only official HTTPS documentation domains are allowed")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in robot_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(origin + "/robots.txt")
        try:
            rp.read()
        except Exception as exc:
            raise RuntimeError(f"Could not verify robots.txt for {origin}: {exc}") from exc
        robot_cache[origin] = rp
    if not robot_cache[origin].can_fetch(USER_AGENT, url):
        raise PermissionError("Robots.txt disallows fetching " + url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                              "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=25) as res:
        final = urllib.parse.urlparse(res.geturl())
        if final.hostname not in ALLOWED_DOC_HOSTS:
            raise ValueError("Redirected outside official domains")
        ct = res.headers.get("Content-Type", "")
        if "html" not in ct.lower():
            raise ValueError(f"Not HTML ({ct})")
        body = res.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Document larger than 2 MB")
    parser = TextHTMLParser()
    parser.feed(body.decode("utf-8", "replace"))
    text = parser.text()
    if len(text) < 100:
        raise ValueError("Document is too short; likely requires JavaScript rendering")
    return parser.title.strip() or parsed.path, text, parser.links


def load_catalog(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config.get("web"), list) or not isinstance(config.get("git"), list):
        raise ValueError("sources.json must have web and git lists")
    ids = [spec.get("id") for spec in config["git"]]
    if len(ids) != len(set(ids)) or any(not isinstance(i, str) for i in ids):
        raise ValueError("Duplicate or invalid Git source IDs")
    for spec in config["git"]:
        validate_git_source(spec)
    for spec in config["web"]:
        if not _canonical_doc_link(spec.get("url", ""), spec.get("url", "")):
            raise ValueError("Invalid official web source: " + str(spec))
    return config


def index_documents(store: Store, docs: Iterable[Document], embedder: Embedder,
                    *, force: bool = False) -> dict:
    count = {"added": 0, "updated": 0, "unchanged": 0, "failed": 0,
             "not_embedded": 0, "documents_seen": 0}
    embeddings_ok = embedder.active
    for doc in docs:
        count["documents_seen"] += 1
        try:
            if store.has_current(doc, force=force):
                count["unchanged"] += 1
                continue
            chunks = chunk_text(doc.body)
            if not chunks:
                count["failed"] += 1
                continue
            vectors = None
            if embeddings_ok:
                try:
                    vectors = []
                    for n in range(0, len(chunks), 16):
                        vectors.extend(embedder.embed([c.content for c in chunks[n:n+16]]))
                except ModelUnavailable as exc:
                    print(f"[WARN] Embeddings unavailable, FTS5-only until reembed: {exc}")
                    embeddings_ok = False
                    vectors = None
            if vectors is None:
                count["not_embedded"] += len(chunks)
            result = store.upsert(doc, chunks, vectors,
                                  embedder.settings.embed_model if vectors else "", force=force)
            count[result] += 1
        except Exception as exc:
            count["failed"] += 1
            print(f"[ERROR] {doc.title}: {exc}")
    return count


def _canonical_doc_link(base_url: str, href: str) -> str | None:
    """Limit discovered links to the two official documentation trees."""
    target = urllib.parse.urlsplit(urllib.parse.urljoin(base_url, href))
    if target.scheme != "https" or target.hostname not in ALLOWED_DOC_HOSTS:
        return None
    path = target.path.rstrip("/") or "/"
    if target.hostname == "docs.flipper.net" and not (path == "/zero" or path.startswith("/zero/")):
        return None
    if target.hostname == "developer.flipper.net" and not path.startswith("/flipperzero/doxygen/"):
        return None
    if any(path.lower().endswith(ext) for ext in (".png", ".jpg", ".svg", ".pdf", ".gif", ".zip", ".js", ".css", ".xml")):
        return None
    if len(path) > 220 or any(part in path for part in ("/search", "/login", "/signup", "/logout")):
        return None
    return urllib.parse.urlunsplit((target.scheme, target.netloc, path, "", ""))


def web_documents(catalog: dict, delay: float = 0.5, *, crawl: bool = False,
                  max_pages: int = 250, max_depth: int = 2):
    robots: dict = {}
    seeds = [(item["url"], item.get("title", ""), item.get("category", "manual"), 0)
             for item in catalog["web"]]
    todo = deque(seeds)
    seen: set[str] = set()
    success = 0
    while todo and len(seen) < max_pages:
        url, name, category, depth = todo.popleft()
        url = _canonical_doc_link(url, url)
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            title, body, links = read_web(url, robots)
            success += 1
            yield Document(doc_id=document_id("web-oficial", url), source_id="web-oficial",
                           title=name or title, url=url, category=category, body=body,
                           license="Copyright upstream; indexed for local reference", trust="official")
            if crawl and depth < max_depth:
                for href in links:
                    child = _canonical_doc_link(url, href)
                    if child and child not in seen:
                        guessed_category = (urllib.parse.urlsplit(child).path.split("/")[2:3] or ["manual"])[0]
                        todo.append((child, "", guessed_category, depth + 1))
        except Exception as exc:
            print(f"[WARN] Web fetch failed {url}: {exc}")
        time.sleep(max(0, delay))
    print(f"Web pages retrieved: {success}/{len(seen)}, max_pages={max_pages}, depth={max_depth}, crawl={crawl}")


def _git(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *cmd], cwd=cwd, check=True, capture_output=True, text=True, timeout=150)
    return result.stdout.strip()


def validate_git_source(spec: dict) -> None:
    parsed = urllib.parse.urlsplit(spec.get("url", ""))
    repo = parsed.path.strip("/").removesuffix(".git").lower()
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            not parsed.path.endswith(".git") or repo not in ALLOWED_GIT_REPOS):
        raise ValueError("Git repository must match the explicit HTTPS allowlist")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", spec.get("id", "")):
        raise ValueError("Invalid source ID")
    if spec.get("tier", "official") not in {"official", "community"}:
        raise ValueError("Invalid trust tier")
    if repo.startswith("flipperdevices/") != (spec.get("tier", "official") == "official"):
        raise ValueError("Trust tier disagrees with repository owner")
    if not re.fullmatch(r"[a-zA-Z0-9_./-]+", spec.get("branch", "")) or ".." in spec["branch"]:
        raise ValueError("Invalid Git branch")
    for key in ("paths", "code_paths"):
        for pattern in spec.get(key, []):
            if pattern.startswith(("/", "\\")) or ".." in Path(pattern).parts or "\\" in pattern:
                raise ValueError("Unsafe file glob")


def sync_git_repo(spec: dict, workdir: Path) -> tuple[Path, str]:
    validate_git_source(spec)
    repo = workdir / spec["id"]
    repo.parent.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        _git(["clone", "--depth", "1", "--single-branch", "--branch", spec["branch"], spec["url"], str(repo)])
    else:
        _git(["fetch", "--depth", "1", "origin", spec["branch"]], cwd=repo)
        _git(["checkout", "--force", "FETCH_HEAD"], cwd=repo)
    return repo, _git(["rev-parse", "HEAD"], cwd=repo)


def git_documents(spec: dict, cache: Path, *, include_code=False):
    repo, commit = sync_git_repo(spec, cache)
    paths = list(spec.get("paths", [])) + (list(spec.get("code_paths", [])) if include_code else [])
    max_files = min(int(spec.get("max_files", 1200)), 5000)
    matched: dict[str, Path] = {}
    for pattern in paths:
        if "*" not in pattern and "?" not in pattern:
            p = repo / pattern
            if p.is_file():
                matched[p.relative_to(repo).as_posix()] = p
        else:
            for p in repo.glob(pattern):
                if p.is_file() and not p.is_symlink() and ".git" not in p.parts:
                    matched[p.relative_to(repo).as_posix()] = p
    count = 0
    for rel, p in sorted(matched.items()):
        if count >= max_files:
            break
        if not p.resolve().is_relative_to(repo.resolve()):
            continue
        if p.stat().st_size > 128_000 or p.stat().st_size == 0:
            continue
        if any(part.lower() in BLOCKED_NAME_PARTS for part in p.relative_to(repo).parts):
            continue
        try:
            raw = p.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if not raw.strip():
            continue
        count += 1
        url = spec["url"].removesuffix(".git") + "/blob/" + commit + "/" + urllib.parse.quote(rel, safe="/")
        yield Document(doc_id=document_id(spec["id"], rel), source_id=spec["id"],
                       title=rel, url=url, category=spec.get("category", "source"),
                       body=raw, revision=commit, license="See upstream repository license",
                       trust=spec.get("tier", "official"))
    print(f"Git {spec['id']}: {count} files indexed from {commit[:12]}")


def local_documents(root: Path, *, source_id="local", category="notas"):
    root = root.resolve()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.is_symlink() or p.suffix.lower() not in SUPPORTED_LOCAL_SUFFIXES:
            continue
        if any(part.lower() in BLOCKED_NAME_PARTS or part.startswith(".") for part in p.relative_to(root).parts):
            continue
        if p.stat().st_size > 128_000 or p.stat().st_size == 0:
            continue
        rel = p.relative_to(root).as_posix()
        yield Document(doc_id=document_id(source_id, rel), source_id=source_id,
                       title=rel, url=p.as_uri(), category=category, body=p.read_text("utf-8", "replace"),
                       license="User-provided local document", trust="local")
