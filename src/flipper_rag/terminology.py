"""Small, auditable Spanish/English terminology bridge for technical searches.

This is keyword expansion, not translation of retrieved evidence. Synonyms are
only introduced when an exact word or phrase is present in the user query.
"""
from __future__ import annotations
import re
import unicodedata

# Search aliases are derived from documented Flipper terminology. Keep this
# dictionary short and inspectable; synonyms must not change the user's intent.
ALIASES: dict[str, str] = {
    "uso responsable": "autorizacion permiso buenas practicas",
    "consentimiento": "autorizacion permiso",
    "infrarrojos": "infrared ir remote",
    "mando a distancia": "infrared remote",
    "radiofrecuencia": "subghz frequency",
    "sub ghz": "subghz sub-ghz",
    "tarjeta micro sd": "sd card",
    "tarjeta sd": "sd card",
    "depurar": "debug logs uart",
    "depuracion": "debug logs",
    "aplicacion externa": "fap application.fam ufbt",
    "aplicaciones externas": "fap application.fam ufbt",
    "compilar": "build fbt ufbt",
    "firmware personalizado": "custom firmware",
    "firmware alternativo": "community firmware",
    "actualizar firmware": "firmware update",
    "registro de eventos": "logs logging",
    "puerto serie": "serial uart",
    "modulo gpio": "gpio expansion",
    "placa wifi": "devboard wifi",
    "tarjeta nfc": "nfc tag",
    "rfid baja frecuencia": "lfrfid 125 khz",
    "formato de archivos": "file format",
    "formato archivo": "file format",
    "protocolo de expansion": "expansion protocol",
    "controlador": "driver hal",
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return re.sub(r"\s+", " ", "".join(ch for ch in decomposed if not unicodedata.combining(ch)))


def expand_query(query: str) -> str:
    """Return unique contextual aliases, not the original query (for lower-weight RRF)."""
    normal = _normalize(query)
    matches = []
    for phrase, alternate in ALIASES.items():
        if re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", normal):
            matches.extend(alternate.split())
    return " ".join(dict.fromkeys(matches))[:300]
