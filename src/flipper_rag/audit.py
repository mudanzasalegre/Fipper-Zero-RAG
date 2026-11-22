"""Read-only source and database integrity audit."""
from __future__ import annotations
from pathlib import Path
import json
import re
from urllib.parse import urlsplit
from .storage import Store


def audit_catalog(path: Path) -> dict:
    problems: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return {"valid": False, "problems": [str(exc)]}
    if not isinstance(data, dict) or not isinstance(data.get("web"), list) or not isinstance(data.get("git"), list):
        return {"valid": False, "problems": ["Expected web/git arrays"]}
    seen: set[str] = set()
    for src in data["web"]:
        url = src.get("url", "") if isinstance(src, dict) else ""
        u = urlsplit(url)
        if u.scheme != "https" or u.hostname not in {"docs.flipper.net", "developer.flipper.net"}:
            problems.append(f"Unapproved web source: {url}")
        if url in seen:
            problems.append(f"Duplicate source: {url}")
        seen.add(url)
    for src in data["git"]:
        if not isinstance(src, dict):
            problems.append("Invalid git entry")
            continue
        sid, url = src.get("id", ""), src.get("url", "")
        u = urlsplit(url)
        from .sources import validate_git_source
        try:
            validate_git_source(src)
        except ValueError as exc:
            problems.append(f"Unapproved git source: {url}: {exc}")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
            problems.append(f"Invalid git source ID: {sid}")
        if sid in seen:
            problems.append(f"Duplicate source ID: {sid}")
        seen.add(sid)
        if not src.get("branch") or int(src.get("max_files", 0)) <= 0:
            problems.append(f"Invalid branch/max_files: {sid}")
    return {"valid": not problems, "web_sources": len(data["web"]), "git_sources": len(data["git"]), "problems": problems}


def audit_store(store: Store) -> dict:
    with store.connect() as c:
        missing_fts = c.execute("SELECT COUNT(*) FROM chunks c WHERE NOT EXISTS (SELECT 1 FROM chunks_fts f WHERE f.chunk_id=c.id)").fetchone()[0]
        orphan_fts = c.execute("SELECT COUNT(*) FROM chunks_fts f WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.id=f.chunk_id)").fetchone()[0]
        invalid_vectors = 0
        for row in c.execute("SELECT embedding FROM chunks WHERE embedding IS NOT NULL"):
            try:
                vector = json.loads(row[0])
                if not isinstance(vector, list) or not vector or not all(isinstance(x,(int,float)) for x in vector):
                    invalid_vectors += 1
            except (ValueError, TypeError):
                invalid_vectors += 1
        return {"valid": not any((missing_fts, orphan_fts, invalid_vectors)), "missing_fts": missing_fts, "orphan_fts": orphan_fts, "invalid_vectors": invalid_vectors}
