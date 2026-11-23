"""Read-only v1.0 knowledge console and indexed provenance API."""
from __future__ import annotations
from importlib.resources import files
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from .platform import Platform
from .storage import Store
from .platform_discovery import discover
from .config import Settings
from .models import Embedder
from .retrieval import Retriever


def attach_platform(app: FastAPI, db_path: Path) -> None:
    @app.get("/platform", response_class=HTMLResponse)
    def platform_console():
        return files("flipper_rag").joinpath("web/platform.html").read_text(encoding="utf-8")

    @app.get("/api/platform/discover")
    def platform_discover(q: str = Query(min_length=2, max_length=160),
                          limit: int = Query(default=6, ge=1, le=15),
                          firmware_ref: str = Query(default="", max_length=100)):
        try:
            settings = Settings()
            local_store = Store(db_path)
            return discover(q, Retriever(local_store, Embedder(settings)), db_path,
                            limit=limit, firmware_ref=firmware_ref)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/platform/status")
    def platform_status(stale_days: int = Query(default=14, ge=1, le=3650)):
        return Platform(Store(db_path)).status(stale_days=stale_days)

    @app.get("/api/platform/audit")
    def platform_audit(stale_days: int = Query(default=14, ge=1, le=3650)):
        return Platform(Store(db_path)).audit(stale_days=stale_days)

    @app.get("/api/platform/evaluations")
    def platform_evaluations(limit: int = Query(default=5, ge=1, le=25)):
        return {"items": Platform(Store(db_path)).reports("evaluation", limit)}

    @app.get("/api/platform/sync-history")
    def platform_sync_history(limit: int = Query(default=5, ge=1, le=25)):
        return {"items": Platform(Store(db_path)).reports("synchronization", limit)}
