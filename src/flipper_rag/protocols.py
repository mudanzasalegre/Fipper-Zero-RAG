"""Curated, inspectable protocol registry. Names are not a device capability matrix.

Only official Flipper Devices documentation and a specific upstream firmware-dev
registry are accepted as references. This module performs no radio operations,
key recovery, or active device interaction.
"""
from __future__ import annotations

from importlib.resources import files
from functools import lru_cache
from urllib.parse import urlsplit
import json
import re
import unicodedata

from .storage import Document, document_id

FAMILIES = frozenset({"nfc", "lf-rfid", "sub-ghz", "infrared", "ibutton", "gpio",
                      "expansion", "bluetooth", "usb"})
SOURCE_ID = "catalogo-protocolos"


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return re.sub(r"[^a-z0-9]+", " ", "".join(x for x in value if not unicodedata.combining(x))).strip()


def _valid_reference(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query:
        return False
    if parsed.hostname in {"docs.flipper.net", "developer.flipper.net"}:
        return (parsed.path.startswith("/zero/") or parsed.path == "/zero") if parsed.hostname == "docs.flipper.net" else parsed.path.startswith("/flipperzero/doxygen/")
    return (parsed.hostname == "github.com" and parsed.path.startswith(
        "/flipperdevices/flipperzero-firmware/blob/dev/lib/subghz/protocols/")
        and parsed.path.endswith(".c"))


def validate_registry(data: dict) -> list[dict]:
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError("Unsupported or malformed protocol registry")
    ids: set[str] = set()
    for item in data["entries"]:
        if not isinstance(item, dict):
            raise ValueError("Protocol entry must be an object")
        required = ("id", "name", "family", "layer", "evidence_scope", "aliases", "reference", "summary")
        if any(key not in item for key in required):
            raise ValueError("Missing protocol entry fields")
        if not isinstance(item["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,90}", item["id"]):
            raise ValueError("Invalid protocol identifier")
        if item["id"] in ids:
            raise ValueError(f"Duplicate protocol id: {item['id']}")
        ids.add(item["id"])
        if item["family"] not in FAMILIES:
            raise ValueError("Unknown protocol family")
        if any(not isinstance(item[key], str) or not (1 <= len(item[key]) <= 800) for key in ("name", "layer", "evidence_scope", "summary")):
            raise ValueError("Malformed descriptive protocol field")
        if not isinstance(item["aliases"], list) or len(item["aliases"]) > 12 or any(not isinstance(a, str) or not (1 <= len(a) <= 80) for a in item["aliases"]):
            raise ValueError("Malformed protocol aliases")
        if not isinstance(item["reference"], str) or not _valid_reference(item["reference"]):
            raise ValueError("Non-official protocol reference")
    if not ids:
        raise ValueError("Protocol registry is empty")
    return data["entries"]


@lru_cache(maxsize=1)
def all_protocols() -> tuple[dict, ...]:
    path = files("flipper_rag").joinpath("data/protocols.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(validate_registry(data))


def get_protocol(value: str) -> dict | None:
    """Exact canonical ID/name/alias lookup; reject ambiguous aliases."""
    if not isinstance(value, str) or len(value) > 120 or not value.strip():
        return None
    term = _fold(value)
    matches = [p for p in all_protocols() if term in {_fold(p['id']), _fold(p['name']), *(_fold(a) for a in p['aliases'])}]
    return matches[0] if len(matches) == 1 else None


def search_protocols(*, family: str | None = None, query: str = "", limit: int = 200) -> list[dict]:
    if family and family not in FAMILIES:
        raise ValueError(f"Unknown protocol family: {family}")
    if len(query) > 200:
        raise ValueError("Protocol query is too long")
    q = _fold(query)
    words = q.split()
    hits = []
    for protocol in all_protocols():
        if family and protocol['family'] != family:
            continue
        full = _fold(" ".join([protocol['name'], protocol['id'], *protocol['aliases'], protocol['family'], protocol['summary']]))
        if words and not all(word in full for word in words):
            continue
        hits.append(protocol)
    return sorted(hits, key=lambda p: (p['family'], p['name'].casefold()))[:max(1, min(limit, 250))]


def protocol_documents():
    """Index own explanatory abstracts, not original upstream material.

    These abstracts are 'local' trust, even though their evidence URLs refer to
    Flipper Devices. An unversioned abstract NEVER certifies firmware support.
    """
    family_context = {
        'infrared': 'Señal infrarroja: trama digital de mando IR, representable como parsed o RAW; no confundir código de protocolo con frecuencia de portadora.',
        'ibutton': 'Comparación iButton: Dallas 1-Wire, Cyfral y Metakom son familias distintas. La lectura de una ROM no significa escritura o emulación de memoria.',
        'lf-rfid': 'RFID de baja frecuencia: 125 kHz; distinguir ASK, PSK, trama, identificador y compatibilidad con el lector.',
        'nfc': 'NFC: 13,56 MHz; distinguir ISO 14443 y ISO 15693, UID, protocolos y autenticación de aplicaciones.',
        'sub-ghz': 'Sub-GHz: distinguir transceptor CC1101, modulación, código fijo frente a dinámico, descodificación y región de transmisión.',
    }
    for p in all_protocols():
        text = (f"# {p['name']} — protocolo {p['family']}\n\n"
                f"Identificador: {p['id']}\n"
                f"Familia: {p['family']}\n"
                f"Capa: {p['layer']}\n"
                f"Ámbito documental: {p['evidence_scope']}\n"
                f"Sinónimos: {', '.join(p['aliases']) or 'ninguno'}\n\n"
                f"{p['summary']}\n\n"
                f"{family_context.get(p['family'], '')}\n\n"
                "Alcance y compatibilidad: esta ficha curada no certifica comportamiento en "
                "una versión concreta del firmware ni autoriza transmitir, leer ni emular "
                "sistemas de terceros. Contrasta la documentación con una release oficial.\n\n"
                f"Referencia técnica oficial: {p['reference']}\n")
        yield Document(doc_id=document_id(SOURCE_ID, p['id']), source_id=SOURCE_ID,
                       title=f"Protocolos / {p['family']} / {p['name']}", url=p['reference'],
                       category=p['family'], body=text, revision="2026-11-22-curated-v1",
                       trust="local", license="Original technical summary; follow upstream licensing",
                       firmware_channel="unversioned")
