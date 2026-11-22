"""Read-only, source-auditable protocol ontology endpoints (v0.6)."""
from __future__ import annotations

from collections import Counter
from importlib.resources import files
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .protocol_intelligence import get_intelligence, OPERATIONS, STATUSES


class CompareRequest(BaseModel):
    protocols: list[str] = Field(min_length=2, max_length=8)
    firmware_version: str | None = Field(default=None, max_length=32,
        pattern=r"^v?[0-9]+\.[0-9]+(\.[0-9]+)?(-rc(\.[0-9]+)?)?$")


router = APIRouter(prefix="/api/ontology", tags=["Protocol Intelligence v0.6"])
pages = APIRouter()


@pages.get("/ontology", response_class=HTMLResponse)
def ontology_page():
    return files("flipper_rag").joinpath("web/ontology.html").read_text(encoding="utf-8")


@router.get("/stats")
def stats():
    engine = get_intelligence()
    families = Counter(card["family"] for card in engine._cards.values())
    covered = Counter(cap["status"] for card in engine._cards.values() for cap in card["capabilities"].values())
    return {"protocols": len(engine), "families": dict(sorted(families.items())),
            "enriched_profiles": len(engine.data["profiles"]),
            "curated_relations": len(engine.data["relations"]),
            "evidence_claims": dict(sorted(covered.items())),
            "reviewed_at": engine.data.get("reviewed_at"),
            "note": "Protocol registry names are not confirmed emulation capabilities."}


@router.get("/search")
def search(query: str = Query(default="", max_length=200),
           family: str | None = Query(default=None, max_length=32),
           feature: str | None = Query(default=None, max_length=42),
           capability: str | None = Query(default=None, max_length=30),
           status: Literal["any", "established", "documented", "limited", "not_supported", "unknown"] = "established",
           medium: str | None = Query(default=None, max_length=60),
           file_format: str | None = Query(default=None, max_length=12),
           frequency_hz: int | None = Query(default=None, ge=1, le=9_999_999_999),
           related_to: str | None = Query(default=None, max_length=120),
           limit: int = Query(default=60, ge=1, le=200)):
    try:
        entries = get_intelligence().search(query=query, family=family, feature=feature,
            capability=capability, status=status, medium=medium, file_format=file_format,
            frequency_hz=frequency_hz, related_to=related_to, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"results": entries, "count": len(entries), "limit": limit,
            "limitations": "Las capacidades sin referencia se consideran desconocidas; las frecuencias de familia no son certificación por protocolo."}


@router.get("/graph")
def graph(format: Literal["json", "jsonld"] = "json"):
    engine = get_intelligence()
    return engine.jsonld() if format == "jsonld" else engine.graph()


@router.get("/protocols/{identifier}")
def protocol(identifier: str, firmware_version: str | None = Query(default=None, max_length=32)):
    try:
        card = get_intelligence().card(identifier, firmware_version=firmware_version)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if card is None:
        raise HTTPException(status_code=404, detail="Unknown or ambiguous protocol")
    return card


@router.get("/protocols/{identifier}/relations")
def relations(identifier: str, depth: int = Query(default=1, ge=1, le=3)):
    try:
        return get_intelligence().neighbors(identifier, depth=depth)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/compare")
def compare(req: CompareRequest):
    try:
        return get_intelligence().compare(req.protocols, firmware_version=req.firmware_version)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def attach_ontology(app: FastAPI) -> None:
    app.include_router(pages)
    app.include_router(router)
