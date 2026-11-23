"""Cross-module, read-only discovery for v1.0. No scripts, radio or builds."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from .retrieval import Retriever


def _fold(s: str) -> str:
    text = unicodedata.normalize("NFKD", s.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def _matches(text: str, query: str) -> bool:
    tokens = [w for w in re.findall(r"[a-z0-9_.-]{3,}", _fold(query))
              if w not in {"como","para","flipper","zero","what","does","with","from","este","sobre","usar","hacer"}]
    return bool(tokens) and all(token in _fold(text) for token in tokens[:6])


def discover(query: str, retriever: Retriever, db_path: Path | str, *, limit: int = 6,
             firmware_ref: str = "") -> dict:
    if not 2 <= len(query.strip()) <= 160:
        raise ValueError("Query must contain 2–160 characters")
    if not 1 <= limit <= 15 or len(firmware_ref) > 100:
        raise ValueError("Invalid discovery limit or firmware reference")
    output = {"query":query,"groups":{},"limitations":[],
              "note":"Knowledge search is read-only; catalog matches are not proof of hardware capability."}
    rag = retriever.search(query, top_k=limit, mode="hybrid")
    output["groups"]["documents"]=[
        {"id":r["id"], "name":r["title"],"url":r["url"],"source":r["source_id"],
         "trust":r["trust"],"revision":r.get("revision") or "unversioned"}
        for r in rag["results"]]
    output["retrieval_backend"] = rag.get("semantic_backend", "not-used")

    try:
        from .protocol_intelligence import get_intelligence
        protocols = get_intelligence().search(query=query, status="any", limit=limit)
        output["groups"]["protocols"]=[
            {"id":p["id"],"name":p["name"],"url":"/ontology", "family":p["family"],
             "reference":p.get("reference"), "evidence_scope":p.get("evidence_scope")}
            for p in protocols]
    except (ImportError, ValueError, OSError) as exc:
        output["groups"]["protocols"] = []
        output["limitations"].append("Protocol ontology unavailable: " + type(exc).__name__)

    try:
        from .development import templates, guides
        items = templates() + guides()
        output["groups"]["development"]=[
            {"id":x["id"],"name":x["title"],"url":"/development",
             "references":x.get("references", [])[:3]}
            for x in items if _matches(" ".join((x["title"],x["id"],x.get("description", ""))),query)][:limit]
    except (ImportError, ValueError, OSError) as exc:
        output["groups"]["development"] = []
        output["limitations"].append("Development catalog unavailable: " + type(exc).__name__)

    try:
        from .protocol_lab import FORMATS
        output["groups"]["formats"] = [
            {"id":name,"name":spec["label"],"url":"/lab","reference":spec["reference"],
             "extension":spec["extension"]}
            for name,spec in FORMATS.items()
            if _matches(" ".join([name,spec["label"],spec["extension"]]), query)][:limit]
    except (ImportError, ValueError, OSError) as exc:
        output["groups"]["formats"] = []
        output["limitations"].append("Protocol Lab registry unavailable: " + type(exc).__name__)

    output["groups"]["firmware"] = []
    if firmware_ref:
        try:
            from .firmware_graph import FirmwareGraph
            graph=FirmwareGraph(db_path)
            # Do not interpret an entire natural-language question as one C symbol.
            terms=re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b",query)
            candidates=[t for t in terms if "_" in t] or terms[-1:]
            for word in candidates[:2]:
                search=graph.symbols(firmware_ref, query=word, limit=limit)
                for symbol in search["results"]:
                    output["groups"]["firmware"].append({
                        "id":symbol["id"],"name":symbol["name"],"url":symbol.get("url") or "/firmware",
                        "snapshot":search["snapshot"],"kind":symbol["kind"]})
            output["groups"]["firmware"]=output["groups"]["firmware"][:limit]
        except (ImportError, ValueError, OSError) as exc:
            output["limitations"].append("Firmware snapshot unavailable: " + type(exc).__name__)
    output["counts"] = {name:len(items) for name,items in output["groups"].items()}
    return output
