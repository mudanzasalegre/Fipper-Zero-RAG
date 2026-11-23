"""Offline, read-only Flipper file inspection with privacy-preserving diagnostics.

No radio operations, keys, payload reproduction, eval/exec, subprocess or network.
Documentation sources are curated per format; this is a structural linter, not a
firmware emulator, cryptographic validator or compatibility certification.
"""
from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass, field
from html import escape as html_escape
from pathlib import Path
import json
import os
import re
from typing import Any

MAX_BYTES = 2_000_000
MAX_LINES = 30_000
MAX_FIELDS = 35_000
MAX_BATCH = 200

FORMATS = {
    "sub": {"extension": ".sub", "label": "Sub-GHz (Key/RAW/BinRAW)",
            "reference": "https://developer.flipper.net/flipperzero/doxygen/subghz_file_format.html"},
    "nfc": {"extension": ".nfc", "label": "NFC", "reference": "https://developer.flipper.net/flipperzero/doxygen/nfc_file_format.html"},
    "rfid": {"extension": ".rfid", "label": "LF RFID", "reference": "https://developer.flipper.net/flipperzero/doxygen/lfrfid_file_format.html"},
    "ir": {"extension": ".ir", "label": "Infrared", "reference": "https://developer.flipper.net/flipperzero/doxygen/infrared_file_format.html"},
    "irtest": {"extension": ".irtest", "label": "Infrared test fixtures", "reference": "https://developer.flipper.net/flipperzero/doxygen/infrared_file_format.html"},
    "ibtn": {"extension": ".ibtn", "label": "iButton", "reference": "https://developer.flipper.net/flipperzero/doxygen/ibutton_file_format.html"},
    "fam": {"extension": ".fam", "label": "Application manifest", "reference": "https://developer.flipper.net/flipperzero/doxygen/app_manifests.html"},
    "proto": {"extension": ".proto", "label": "Protocol Buffers schema", "reference": "https://protobuf.dev/programming-guides/proto3/"},
    "badusb": {"extension": ".txt", "label": "BadUSB static syntax (explicit opt-in)",
               "reference": "https://developer.flipper.net/flipperzero/doxygen/badusb_file_format.html"},
}
AUTO_EXTENSIONS = {v["extension"]: k for k, v in FORMATS.items() if k != "badusb"}
IR_PROTOCOLS = set("NEC NECext NEC42 NEC42ext Samsung32 RC6 RC5 RC5X SIRC SIRC15 SIRC20 Kaseikyo RCA".split())
RFID_TYPES = {"EM4100", "EM4100/32", "EM4100/16", "H10301", "Idteck", "Indala26", "IOProxXSF", "AWID", "FDX-A", "FDX-B", "HIDProx", "HIDExt", "Pyramid", "Viking", "Jablotron", "Paradox", "PAC/Stanley", "Keri", "Gallagher", "GProxII"}
SUB_KNOWN = {"RAW", "BinRAW", "Princeton", "CAME", "Nice FLO", "KeeLoq", "Linear", "Holtek"}
PRESETS = {"FuriHalSubGhzPresetOok270Async", "FuriHalSubGhzPresetOok650Async",
           "FuriHalSubGhzPreset2FSKDev238Async", "FuriHalSubGhzPreset2FSKDev12KAsync",
           "FuriHalSubGhzPreset2FSKDev476Async", "FuriHalSubGhzPresetCustom"}
IBUTTON_PROT = set("DS1990 DS1992 DS1996 DS1971 DSGeneric Cyfral Metakom".split())
KEY_LIKE = re.compile(r"(?:key|uid|secret|password|private|pin|sector|block|data|rom|sram|eeprom|address|command|auth|token|credential)", re.I)
SAFE_TERM = re.compile(r"^[a-zA-Z0-9_./+ -]{1,64}$")
FF_KEY = re.compile(r"^[\w /.-]{1,80}$", re.ASCII)
HEX_BYTES = re.compile(r"[0-9a-fA-F]{2}(?:\s+[0-9a-fA-F]{2})*")


def _safe_term(s: str, *, whitelist: set[str] | None = None) -> str | None:
    s = s.strip()
    if len(s) > 64 or not SAFE_TERM.fullmatch(s):
        return None
    if whitelist is not None and s not in whitelist:
        return None
    return s


def _int(s: str) -> int | None:
    if re.fullmatch(r"[0-9]{1,13}", s.strip()):
        return int(s.strip())
    return None


def _hex_length(s: str) -> int | None:
    s = s.strip()
    if HEX_BYTES.fullmatch(s) and len(s) <= MAX_BYTES:
        return len(s.split())
    return None


@dataclass(frozen=True)
class Record:
    key: str
    value: str
    line: int


@dataclass
class Diagnostic:
    code: str
    severity: str
    message: str
    line: int | None = None
    remediation: str = ""

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "message": self.message,
                "line": self.line, "remediation": self.remediation}


@dataclass
class Analysis:
    format: str
    label: str
    reference: str
    source: str
    bytes: int
    lines: int
    metadata: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    findings: list[Diagnostic] = field(default_factory=list)
    sensitive_fields_detected: bool = False
    limitations: list[str] = field(default_factory=lambda: [
        "Validación estructural y documental offline; no valida autenticación, RF, firmware instalado ni funcionamiento físico.",
        "Los valores de identificadores, claves, comandos y muestras de señal nunca se incluyen en el informe."])

    def issue(self, code: str, severity: str, message: str, line: int | None = None,
              remediation: str = "") -> None:
        self.findings.append(Diagnostic(code, severity, message, line, remediation))

    def as_dict(self) -> dict:
        counts = Counter(x.severity for x in self.findings)
        status = "invalid" if counts["error"] else ("warnings" if counts["warning"] else "valid")
        return {"schema_version": 1, "format": self.format, "label": self.label,
                "source": self.source, "official_reference": self.reference,
                "status": status, "file_size_bytes": self.bytes, "line_count": self.lines,
                "metadata": dict(sorted(self.metadata.items())), "counts": dict(sorted(self.counts.items())),
                "findings": [x.as_dict() for x in self.findings[:250]],
                "finding_totals": {"errors": counts["error"], "warnings": counts["warning"], "info": counts["info"]},
                "findings_truncated": len(self.findings) > 250,
                "sensitive_fields_detected": self.sensitive_fields_detected,
                "data_policy": "redacted; payload values never exported; no persistence unless explicitly requested",
                "limitations": self.limitations}


def _records(text: str, out: Analysis) -> list[Record]:
    result: list[Record] = []
    for no, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("-----"):
            continue
        if ":" not in s:
            out.issue("FF_MALFORMED_LINE", "warning", "Línea sin separador de campo ':'.", no)
            continue
        key, value = s.split(":", 1)
        key = key.strip()
        if not FF_KEY.fullmatch(key):
            out.issue("FF_MALFORMED_FIELD", "warning", "Nombre de campo no conforme al formato de texto.", no)
            continue
        result.append(Record(key, value.strip(), no))
        if len(result) >= MAX_FIELDS:
            out.issue("FF_LIMIT", "error", "Se superó el límite de campos examinables.")
            break
    out.counts["fields"] = len(result)
    out.sensitive_fields_detected = any(KEY_LIKE.search(r.key) for r in result)
    return result


def _one(records: list[Record], key: str, out: Analysis, *, required: bool = True) -> Record | None:
    matches = [r for r in records if r.key.casefold() == key.casefold()]
    if not matches:
        if required:
            out.issue("FIELD_REQUIRED", "error", f"Falta el campo obligatorio '{key}'.")
        return None
    if len(matches) > 1:
        out.issue("FIELD_DUPLICATE", "warning", f"El campo '{key}' aparece repetido.", matches[1].line)
    return matches[0]


def _hex_record(r: Record | None, out: Analysis, *, sizes: set[int] | None = None) -> int | None:
    if not r:
        return None
    n = _hex_length(r.value)
    if n is None:
        out.issue("HEX_INVALID", "error", "Campo hexadecimal mal formado; debe contener bytes de dos dígitos.", r.line)
    elif sizes and n not in sizes:
        out.issue("HEX_LENGTH", "error", f"Longitud inesperada: se esperan {sorted(sizes)} bytes.", r.line)
    return n


def _version(records: list[Record], out: Analysis, expected: set[int]) -> int | None:
    v = _one(records, "Version", out)
    if not v:
        return None
    n = _int(v.value)
    if n is None:
        out.issue("VERSION_INVALID", "error", "La versión debe ser un entero no negativo.", v.line)
    else:
        out.metadata["file_version"] = n
        if n not in expected:
            out.issue("VERSION_UNVERIFIED", "warning", "Versión fuera de las documentadas para este analizador; no se presupone incompatibilidad.", v.line)
    return n


def _header(records: list[Record], out: Analysis, allowed: set[str], versions: set[int]) -> None:
    ft = _one(records, "Filetype", out)
    if ft and ft.value not in allowed:
        out.issue("FILETYPE_MISMATCH", "error", "Cabecera Filetype no corresponde a la extensión elegida.", ft.line)
    elif ft:
        out.metadata["filetype"] = ft.value  # fixed allowlist only
    _version(records, out, versions)


def _sub(records: list[Record], out: Analysis) -> None:
    _header(records, out, {"Flipper SubGhz Key File", "Flipper SubGhz RAW File"}, {1})
    freq = _one(records, "Frequency", out)
    if freq:
        n = _int(freq.value)
        if n is None or n == 0:
            out.issue("FREQUENCY_INVALID", "error", "Frecuencia debe ser un entero positivo en Hz.", freq.line)
        else:
            out.metadata["frequency_hz"] = n
            if n < 100_000_000 or n > 1_000_000_000:
                out.issue("FREQUENCY_REVIEW", "warning", "Frecuencia inusual; verifica especificaciones y normativa local.", freq.line)
    preset = _one(records, "Preset", out)
    if preset:
        p = _safe_term(preset.value)
        if not p:
            out.issue("PRESET_INVALID", "error", "Nombre de preset no reconocido sintácticamente.", preset.line)
        elif p not in PRESETS:
            out.issue("PRESET_UNVERIFIED", "warning", "Preset desconocido para esta versión del analizador; validar con firmware específico.", preset.line)
        else:
            out.metadata["preset"] = p
            if p == "FuriHalSubGhzPresetCustom":
                mod = _one(records, "Custom_preset_module", out)
                custom = _one(records, "Custom_preset_data", out)
                if mod and mod.value != "CC1101":
                    out.issue("CUSTOM_MODULE", "warning", "El preset personalizado no identifica el módulo CC1101.", mod.line)
                _hex_record(custom, out)
    proto = _one(records, "Protocol", out)
    if not proto:
        return
    p = _safe_term(proto.value)
    if not p:
        out.issue("PROTOCOL_VALUE", "error", "Valor de protocolo no reconocido sintácticamente.", proto.line)
        return
    if p in SUB_KNOWN:
        out.metadata["protocol"] = p
    else:
        # Do not propagate arbitrary untrusted field contents into reports/embeddings.
        out.issue("SUB_PROTOCOL_UNVERIFIED", "warning", "Protocolo presente, pero su nombre no está verificado en este catálogo de laboratorio.", proto.line)
    if p == "RAW":
        lines = [r for r in records if r.key == "RAW_Data"]
        if not lines:
            out.issue("RAW_REQUIRED", "error", "RAW requiere al menos un campo RAW_Data.")
        out.counts["raw_lines"] = len(lines)
        count = 0
        last_sign = 0
        for r in lines:
            vals = r.value.split()
            count += len(vals)
            if not vals or len(vals) > 512:
                out.issue("RAW_LINE_COUNT", "error", "Cada línea RAW_Data requiere entre 1 y 512 intervalos.", r.line)
            for v in vals[:512]:
                if not re.fullmatch(r"[+-]?[0-9]{1,10}", v) or int(v) == 0:
                    out.issue("RAW_PULSE_INVALID", "error", "Duración RAW no válida; debe ser un entero distinto de cero.", r.line)
                    break
                sign = 1 if int(v) > 0 else -1
                if sign == last_sign:
                    out.issue("RAW_POLARITY", "warning", "Hay intervalos de igual signo consecutivos; revisar captura RAW.", r.line)
                    last_sign = sign
                    break
                last_sign = sign
        out.counts["raw_intervals"] = count
    elif p == "BinRAW":
        bit = _one(records, "Bit", out)
        te = _one(records, "TE", out)
        if bit:
            n = _int(bit.value)
            if n is None or not 1 <= n <= 4096:
                out.issue("BINRAW_BITS", "error", "BinRAW requiere longitud Bit entre 1 y 4096.", bit.line)
        if te and (_int(te.value) is None or _int(te.value) == 0):
            out.issue("BINRAW_TE", "error", "BinRAW requiere TE positivo en microsegundos.", te.line)
        groups = [r for r in records if r.key in {"Bit_RAW", "Data_RAW"}]
        if not groups or len(groups) % 2:
            out.issue("BINRAW_GROUPS", "error", "BinRAW requiere parejas Bit_RAW / Data_RAW.")
        for a, b in zip(groups[::2], groups[1::2]):
            if (a.key,b.key) != ("Bit_RAW","Data_RAW"):
                out.issue("BINRAW_ORDER", "error", "El orden de bloques BinRAW no coincide con el formato.", a.line)
            bits = _int(a.value)
            length = _hex_record(b, out)
            if bits is None or bits < 1 or bits > 4096 or (length is not None and length * 8 < bits):
                out.issue("BINRAW_LENGTH", "error", "Longitud Bit_RAW no coincide con Data_RAW.", a.line)
        out.counts["binraw_blocks"] = len(groups) // 2
    else:
        bit = _one(records, "Bit", out, required=False)
        if bit and (_int(bit.value) is None or not 1 <= _int(bit.value) <= 4096):
            out.issue("BIT_INVALID", "error", "Longitud Bit incorrecta.", bit.line)
        key = _one(records, "Key", out, required=False)
        if key:
            _hex_record(key, out)


def _nfc(records: list[Record], out: Analysis) -> None:
    _header(records, out, {"Flipper NFC device"}, {1,2,3,4})
    typ = _one(records, "Device type", out)
    if typ:
        allowed = {"ISO14443-3A", "ISO14443-3B", "ISO14443-4A", "NTAG/Ultralight", "Mifare Classic", "Mifare DESFire", "ISO15693", "FeliCa"}
        if _safe_term(typ.value, whitelist=allowed):
            out.metadata["device_type"] = typ.value
        else:
            out.issue("NFC_DEVICE_UNVERIFIED", "warning", "Tipo NFC no cubierto en el catálogo de reglas; validar con firmware específico.", typ.line)
    uid = _one(records, "UID", out)
    count = _hex_record(uid, out)
    if count is not None:
        out.counts["uid_bytes"] = count
        if typ and typ.value == "ISO14443-3A" and count not in {4,7}:
            out.issue("NFC_UID_LENGTH", "error", "ISO14443-3A requiere UID de 4 o 7 bytes según documentación.", uid.line)
    for key, sizes in (("ATQA", {2}), ("SAK", {1})):
        _hex_record(_one(records, key, out, required=False), out, sizes=sizes)
    out.counts["additional_fields"] = sum(r.key not in {"Filetype","Version","Device type","UID","ATQA","SAK"} for r in records)
    if out.metadata.get("file_version") in {1,2}:
        out.issue("NFC_LEGACY", "warning", "Formato histórico NFC: puede necesitar migración para firmware reciente.")


def _rfid(records: list[Record], out: Analysis) -> None:
    _header(records, out, {"Flipper RFID key"}, {1})
    key = _one(records, "Key type", out)
    if key:
        val = _safe_term(key.value)
        if val and val in RFID_TYPES:
            out.metadata["key_type"] = val
        else:
            out.issue("RFID_KEY_TYPE", "warning", "El identificador de formato RFID requiere comprobación.", key.line)
    n = _hex_record(_one(records, "Data", out), out)
    if n is not None:
        out.counts["data_bytes"] = n
        if key and key.value == "EM4100" and n != 5:
            out.issue("RFID_EM4100_LENGTH", "warning", "EM4100 suele usar 5 bytes en el formato de archivo; revisar origen.")


def _ibtn(records: list[Record], out: Analysis) -> None:
    _header(records, out, {"Flipper iButton key"}, {1,2})
    version = out.metadata.get("file_version")
    if version == 1:
        out.issue("IBTN_LEGACY", "warning", "Formato iButton v1 obsoleto; el firmware puede convertirlo al guardar.")
        _one(records, "Key type", out)
        _hex_record(_one(records, "Data", out), out)
        return
    p = _one(records, "Protocol", out)
    if not p:
        return
    if p.value not in IBUTTON_PROT:
        out.issue("IBTN_PROTOCOL_UNVERIFIED", "warning", "Protocolo fuera de la lista documentada; validar contra el firmware.", p.line)
    else:
        out.metadata["protocol"] = p.value
    if p.value.startswith("DS"):
        _hex_record(_one(records, "Rom Data", out), out, sizes={8})
        if p.value in {"DS1992", "DS1996"}:
            _hex_record(_one(records, "Sram Data", out, required=False), out)
        if p.value == "DS1971":
            _hex_record(_one(records, "Eeprom Data", out, required=False), out)
    elif p.value in {"Cyfral", "Metakom"}:
        _hex_record(_one(records, "Data", out), out)


def _ir(records: list[Record], out: Analysis, *, is_test: bool = False) -> None:
    expected = {"IR signals file", "IR library file", "IR test file"} if is_test else {"IR signals file", "IR library file"}
    _header(records, out, expected, {1})
    groups: list[list[Record]] = []
    for r in records:
        if r.key == "name":
            groups.append([r])
        elif groups and r.key not in {"Filetype", "Version"}:
            groups[-1].append(r)
    out.counts["signals"] = len(groups)
    if not groups:
        out.issue("IR_EMPTY", "error", "No se encontraron señales/botones de infrarrojos.")
    for group in groups:
        name = group[0]
        if not re.fullmatch(r"[\x20-\x7e]{1,80}", name.value):
            out.issue("IR_NAME_INVALID", "error", "El nombre debe estar formado por caracteres ASCII imprimibles.", name.line)
        kind = _one(group, "type", out)
        if not kind:
            continue
        if kind.value == "parsed" or (is_test and kind.value == "parsed_array"):
            prot = _one(group, "protocol", out)
            if prot and prot.value not in IR_PROTOCOLS:
                out.issue("IR_PROTOCOL_UNVERIFIED", "warning", "Protocolo no incluido en la lista oficial verificada.", prot.line)
            _hex_record(_one(group, "address", out), out, sizes={4})
            _hex_record(_one(group, "command", out), out, sizes={4})
            if is_test:
                count = _one(group, "count", out)
                if count and (_int(count.value) is None or _int(count.value) < 1):
                    out.issue("IRTEST_COUNT", "error", "count debe ser un entero positivo.", count.line)
        elif kind.value == "raw":
            freq = _one(group, "frequency", out)
            if freq and (_int(freq.value) is None or _int(freq.value) == 0):
                out.issue("IR_FREQUENCY", "error", "Portadora infrarroja debe ser frecuencia positiva.", freq.line)
            duty = _one(group, "duty_cycle", out)
            if duty:
                try:
                    d = float(duty.value)
                    if not 0.0 < d <= 1.0 or d != d:
                        raise ValueError
                except ValueError:
                    out.issue("IR_DUTY", "error", "Duty cycle fuera del rango (0,1].", duty.line)
            samples = _one(group, "data", out)
            if samples:
                vals = samples.value.split()
                if not 1 <= len(vals) <= 1024 or any(not re.fullmatch(r"\d{1,10}", z) or int(z)==0 for z in vals):
                    out.issue("IR_TIMINGS", "error", "RAW exige entre 1 y 1024 duraciones enteras positivas.", samples.line)
                else:
                    out.counts["raw_intervals"] = out.counts.get("raw_intervals", 0) + len(vals)
        else:
            out.issue("IR_TYPE", "error", "La señal debe ser parsed o raw (parsed_array en irtest).", kind.line)
    out.counts["parsed_signals"] = sum(any(r.key == "type" and r.value.startswith("parsed") for r in g) for g in groups)
    out.counts["raw_signals"] = sum(any(r.key == "type" and r.value == "raw" for r in g) for g in groups)


def _fam(text: str, out: Analysis) -> None:
    """Parse Python AST without evaluating a manifest; reject executable statements."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        out.issue("FAM_SYNTAX", "error", "El manifiesto no tiene sintaxis Python válida.", exc.lineno)
        return
    apps = []
    for node in tree.body:
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and
                isinstance(node.value.func, ast.Name) and node.value.func.id == "App"):
            out.issue("FAM_EXECUTABLE", "warning", "Se detecta código ajeno a una declaración App(): no se ejecuta.", getattr(node,"lineno",None))
            continue
        call = node.value
        kwargs = {k.arg: k.value for k in call.keywords if k.arg}
        if any(k.arg is None for k in call.keywords) or call.args:
            out.issue("FAM_DYNAMIC", "warning", "App() contiene parámetros dinámicos no evaluables de forma segura.", node.lineno)
        appid = kwargs.get("appid")
        apptype = kwargs.get("apptype")
        if not isinstance(appid, ast.Constant) or not isinstance(appid.value, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", appid.value):
            out.issue("FAM_APPID", "error", "App() requiere appid literal con letras minúsculas, números o '_'.", node.lineno)
        if not (isinstance(apptype, ast.Attribute) and isinstance(apptype.value, ast.Name) and
                apptype.value.id == "FlipperAppType" and
                apptype.attr in {"SERVICE","SYSTEM","APP","PLUGIN","DEBUG","ARCHIVE","SETTINGS","STARTUP","EXTERNAL","METAPACKAGE"}):
            out.issue("FAM_APPTYPE", "error", "App() requiere apptype=FlipperAppType.<tipo válido>.", node.lineno)
        if "fap_extbuild" in kwargs:
            out.issue("FAM_EXTERNAL_BUILD", "warning", "El manifiesto declara comandos de compilación externos; no se ejecutan ni se validan aquí.", node.lineno)
        if apptype and isinstance(apptype, ast.Attribute) and apptype.attr == "EXTERNAL":
            out.counts["external_apps"] = out.counts.get("external_apps",0)+1
        apps.append(node)
    out.counts["applications"] = len(apps)
    if not apps:
        out.issue("FAM_NO_APPS", "error", "No se encontraron definiciones App() válidas.")
    out.sensitive_fields_detected = True  # Manifest may include URLs, commands, source paths, etc.
    out.limitations.append("El analizador solo interpreta el AST y no ejecuta manifests ni expresiones; requiere uFBT para validación final.")


def _proto(text: str, out: Analysis) -> None:
    cleaned = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    cleaned = re.sub(r"//[^\n]*", "", cleaned)
    cleaned = re.sub(r'"(?:\\.|[^"\\])*"', '""', cleaned)
    depth = 0
    for ch in cleaned:
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                out.issue("PROTO_BRACES", "error", "Llaves de cierre sin apertura en esquema protobuf.")
                break
    if depth > 0:
        out.issue("PROTO_BRACES", "error", "Llaves sin cerrar en esquema protobuf.")
    syntax = re.search(r'^\s*syntax\s*=\s*"([A-Za-z0-9]+)"\s*;', text, re.M)
    if syntax and syntax.group(1) in {"proto2", "proto3"}:
        out.metadata["syntax"] = syntax.group(1)
    else:
        out.issue("PROTO_SYNTAX", "warning", "No se ha encontrado una declaración syntax proto2/proto3 válida.")
    out.counts["messages"] = len(re.findall(r"\bmessage\s+[A-Za-z_]\w*\s*{", cleaned))
    out.counts["enums"] = len(re.findall(r"\benum\s+[A-Za-z_]\w*\s*{", cleaned))
    out.counts["services"] = len(re.findall(r"\bservice\s+[A-Za-z_]\w*\s*{", cleaned))
    out.counts["imports"] = len(re.findall(r"\bimport\s+(?:public\s+|weak\s+)?\"", text))
    # Inspect only direct message-field lines (no compiler, preprocessor, RPC, oneof or imports).
    # Avoid including message/field names in diagnostics: project schemas may be proprietary.
    seen_tags: dict[str, set[int]] = {}
    message_stack: list[tuple[str, int]] = []
    brace_depth = 0
    for line_no, line in enumerate(cleaned.splitlines(),1):
        match = re.search(r"\bmessage\s+([A-Za-z_]\w*)\s*{", line)
        if match:
            message_stack.append((match.group(1), brace_depth+line.count("{")-line.count("}")))
        if message_stack:
            field = re.match(r"\s*(?:(?:optional|required|repeated)\s+)?[.A-Za-z_]\w*\s+[A-Za-z_]\w*\s*=\s*(\d+)\s*(?:[;\[])", line)
            if field:
                tag = int(field.group(1))
                scope = "/".join(name for name,_ in message_stack)
                if tag in seen_tags.setdefault(scope,set()):
                    out.issue("PROTO_DUPLICATE_TAG", "error", "Número de campo duplicado en el mismo mensaje.", line_no)
                seen_tags[scope].add(tag)
                if not 1 <= tag < 536870912 or 19000 <= tag <= 19999:
                    out.issue("PROTO_FIELD_NUMBER", "error", "Número de campo protobuf fuera del rango permitido o reservado.",line_no)
        brace_depth += line.count("{") - line.count("}")
        while message_stack and brace_depth < message_stack[-1][1]:
            message_stack.pop()
    out.counts["simple_field_declarations"] = sum(len(tags) for tags in seen_tags.values())
    out.limitations.append("Comprobación parcial de estructura y numeración directa; no sustituye protoc ni resuelve imports, opciones o nested types complejos.")
    out.sensitive_fields_detected = True  # potentially private message names


def _badusb(text: str, out: Analysis) -> None:
    allowed = {"REM", "DELAY", "DEFAULT_DELAY", "DEFAULTDELAY", "STRING", "STRINGLN", "STRING_DELAY", "STRINGDELAY", "REPEAT", "HOLD", "RELEASE", "ID", "BLE_ID", "BT_ID", "WAIT_FOR_BUTTON_PRESS", "MEDIA", "ALTCHAR", "ALTSTRING", "ALTCODE", "MOUSEMOVE", "MOUSE_MOVE", "MOUSESCROLL", "MOUSE_SCROLL", "LEFTCLICK", "RIGHTCLICK", "LEFT_CLICK", "RIGHT_CLICK", "SYSRQ", "GLOBE"}
    out.counts["commands"] = 0
    unknown = 0
    for no, line in enumerate(text.splitlines(),1):
        s = line.strip()
        if not s:
            continue
        key = s.split(maxsplit=1)[0].upper()
        out.counts["commands"] += 1
        if key not in allowed and not re.fullmatch(r"(?:CTRL|CONTROL|ALT|SHIFT|GUI|WINDOWS)(?:[-+].+)?|F(?:[1-9]|1[0-2])|[A-Z]{1,16}", key):
            unknown += 1
        if key in {"DELAY", "DEFAULT_DELAY", "DEFAULTDELAY"}:
            parts=s.split(maxsplit=1)
            if len(parts)!=2 or _int(parts[1]) is None:
                out.issue("BADUSB_DELAY", "warning", "Duración DELAY no numérica.", no)
    if unknown:
        out.issue("BADUSB_UNKNOWN", "warning", "Se detectaron comandos no reconocidos por la comprobación superficial.")
    out.sensitive_fields_detected = bool(out.counts["commands"])
    out.limitations.append("Solo cuenta comandos y comprueba sintaxis básica; nunca ejecuta scripts HID ni valida su seguridad.")


def analyze_text(text: str, *, filename: str = "sample.sub", file_format: str | None = None,
                 size_bytes: int | None = None) -> dict:
    if not isinstance(text, str):
        raise ValueError("Text input expected")
    nbytes = len(text.encode("utf-8")) if size_bytes is None else size_bytes
    if nbytes > MAX_BYTES:
        raise ValueError("Input exceeds the maximum allowed size")
    if "\x00" in text:
        raise ValueError("Binary/NUL content is not accepted")
    line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    if line_count > MAX_LINES:
        raise ValueError("Input exceeds line limit")
    fmt = file_format or AUTO_EXTENSIONS.get(Path(filename).suffix.lower())
    if fmt not in FORMATS:
        raise ValueError("Unsupported format: select a supported extension or explicit format")
    result = Analysis(format=fmt, label=FORMATS[fmt]["label"], reference=FORMATS[fmt]["reference"],
                      source=f"archivo {FORMATS[fmt]['extension']}", bytes=nbytes, lines=line_count)
    if not text.strip():
        result.issue("EMPTY_FILE", "error", "El archivo está vacío.")
        return result.as_dict()
    if fmt == "fam":
        _fam(text, result)
    elif fmt == "proto":
        _proto(text, result)
    elif fmt == "badusb":
        _badusb(text, result)
    else:
        records = _records(text, result)
        parser = {"sub": _sub, "nfc": _nfc, "rfid": _rfid, "ir": _ir,
                  "irtest": lambda items,out: _ir(items,out,is_test=True), "ibtn": _ibtn}[fmt]
        parser(records, result)
    return result.as_dict()


def analyze_bytes(data: bytes, *, filename: str = "sample.sub", file_format: str | None = None) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("File exceeds maximum allowed size")
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Only UTF-8 text files are supported") from exc
    return analyze_text(text, filename=filename, file_format=file_format, size_bytes=len(data))


def analyze_file(path: Path, *, file_format: str | None = None) -> dict:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Input must be a regular file, not a symlink")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("File exceeds maximum allowed size")
    with path.open("rb") as f:
        data = f.read(MAX_BYTES + 1)
    return analyze_bytes(data, filename=path.name, file_format=file_format)


def analyze_directory(directory: Path, *, limit: int = MAX_BATCH) -> list[dict]:
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("A non-symlink directory is required")
    limit = max(1, min(MAX_BATCH, int(limit)))
    items: list[dict] = []
    visited = 0
    # Bounded walk without following linked directories or materializing huge tree listings.
    for root, dirs, names in os.walk(directory, topdown=True, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {".git", ".venv", "node_modules", "__pycache__"}
                         and not (Path(root)/d).is_symlink())
        for filename in sorted(names):
            visited += 1
            if visited > 5000 or len(items) >= limit:
                return items
            p = Path(root)/filename
            if p.is_symlink() or not p.is_file() or p.suffix.lower() not in AUTO_EXTENSIONS:
                continue
            try:
                items.append(analyze_file(p))
            except (ValueError, OSError):
                # No filename/path/data in error, for privacy.
                items.append({"schema_version":1,"source":f"archivo {p.suffix.lower()}","format":AUTO_EXTENSIONS[p.suffix.lower()],
                              "status":"invalid", "metadata":{},"counts":{},"findings": [
                                  {"code":"FILE_UNREADABLE","severity":"error","message":"No se pudo analizar archivo de entrada.","line":None,"remediation":"Compruebe tamaño, permisos y UTF-8."}],
                              "data_policy":"redacted"})
        if visited > 5000 or len(items) >= limit:
            break
    return items


def compare_results(left: dict, right: dict) -> dict:
    keys = set(left.get("metadata",{})) | set(right.get("metadata",{}))
    counts = set(left.get("counts",{})) | set(right.get("counts",{}))
    return {"schema_version": 1, "before_format":left.get("format"), "after_format":right.get("format"),
            "before_status":left.get("status"),"after_status":right.get("status"),
            "metadata_changes": {k:{"before":left.get("metadata",{}).get(k), "after":right.get("metadata",{}).get(k)}
                                for k in sorted(keys) if left.get("metadata",{}).get(k)!=right.get("metadata",{}).get(k)},
            "metric_changes": {k:{"before":left.get("counts",{}).get(k), "after":right.get("counts",{}).get(k)}
                               for k in sorted(counts) if left.get("counts",{}).get(k)!=right.get("counts",{}).get(k)},
            "added_diagnostic_codes": sorted({d["code"] for d in right.get("findings",[])} - {d["code"] for d in left.get("findings",[])}),
            "resolved_diagnostic_codes": sorted({d["code"] for d in left.get("findings",[])} - {d["code"] for d in right.get("findings",[])}),
            "data_policy":"redacted; content and payload values never compared"}


def render_report(report: dict, *, output: str = "markdown") -> str:
    """Serialize *only* the sanitized analysis object. Callers never pass input text."""
    if output == "json":
        return json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)
    if output not in {"markdown", "html"}:
        raise ValueError("Report must be markdown, html or json")
    # Key/value safety is enforced again at export boundary, including injected callers.
    safe = json.loads(json.dumps(report, ensure_ascii=False))
    if not isinstance(safe, dict) or safe.get("schema_version") != 1:
        raise ValueError("Invalid report schema")
    # Revalidate metadata allowlist at output boundary (no raw payload from user).
    safe_meta = {k:v for k,v in safe.get("metadata",{}).items()
                 if k in {"file_version", "filetype", "frequency_hz", "preset", "protocol", "device_type", "key_type", "syntax"}
                 and (isinstance(v, int) or (isinstance(v, str) and _safe_term(v)))}
    safe_counts = {k:v for k,v in safe.get("counts",{}).items() if re.fullmatch(r"[a-z_]{1,32}",k) and type(v) is int and 0<=v<=MAX_FIELDS*10}
    # Fixed formatter vocabulary for any other field supplied by untrusted analysis.
    findings = [x for x in safe.get("findings",[]) if isinstance(x,dict)
                and re.fullmatch(r"[A-Z_]{3,45}",str(x.get("code","")))][:250]
    base=[f"# Flipper Zero · Protocol Lab ({safe.get('format','unknown') if safe.get('format') in FORMATS else 'unknown'})", "",
          f"Estado: {safe.get('status') if safe.get('status') in {'valid','invalid','warnings'} else 'unknown'}", "",
          "## Metadatos estructurales", ""]
    for k,v in sorted(safe_meta.items()):
        base.append(f"- {k}: {v}")
    base.extend(["", "## Métricas", ""])
    for k,v in sorted(safe_counts.items()):
        base.append(f"- {k}: {v}")
    base.extend(["", "## Diagnósticos", ""])
    for d in findings:
        code=d.get("code", "")
        # Message is from our fixed parsers; when rendering arbitrary supplied reports, never export string from caller.
        severity=d.get("severity") if d.get("severity") in {"error","warning","info"} else "info"
        lineno=d.get("line") if type(d.get("line")) is int and 0 < d["line"] <= MAX_LINES else None
        message=d.get("message","")
        message=re.sub(r"[\r\n|<>`]+", " ", message)[:200] if isinstance(message,str) else ""
        base.append(f"- [{severity}] {code} (línea {lineno or '-' }): {message}")
    base.extend(["", "## Fuentes y límites", "", "Este análisis es estático y offline. No verifica funcionamiento real, permisos de transmisión ni autenticación.",
                 "Nunca contiene claves, UIDs, tramas, comandos de señal ni datos originales."])
    ref = FORMATS.get(safe.get("format"),{}).get("reference")
    if ref:
        base.append("Referencia oficial: " + ref)
    body="\n".join(base).rstrip()+"\n"
    if output == "markdown":
        return body
    # Minimal offline HTML with a no-scripts policy and escaped contents.
    escaped=html_escape(body)
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
            '<title>Informe Protocol Lab</title><style>body{font:16px/1.55 system-ui;margin:2rem auto;max-width:900px;padding:0 1rem}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f5f7;padding:1.25rem;border-radius:10px}</style>'
            '</head><body><pre>' + escaped + '</pre></body></html>')


def privacy_summary(result: dict) -> str:
    """Text safe to embed into RAG. Never includes raw content or source filenames."""
    meta = result.get("metadata",{})
    stats = result.get("finding_totals",{})
    allowed = {k:meta[k] for k in ("file_version", "filetype", "protocol", "device_type", "key_type", "syntax") if k in meta}
    codes = sorted({item["code"] for item in result.get("findings",[]) if item.get("code")})
    return (f"# Diagnóstico Protocol Lab {result.get('format')}\nEstado: {result.get('status')}\n"
            f"Metadatos estructurales: {json.dumps(allowed,ensure_ascii=False)}\n"
            f"Errores: {stats.get('errors',0)}; avisos: {stats.get('warnings',0)}\n"
            f"Códigos de diagnóstico: {', '.join(codes)}\n"
            f"Referencia: {FORMATS[result['format']]['reference']}\n"
            "Fuentes: interpretación estática local; no verifica compatibilidad con firmware instalado.\n")


def _plain_html(body: str) -> str:
    """Render static, escaped text: no script, remote resources or dynamic markup."""
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
            '<title>Informe Protocol Lab</title><style>body{font:16px/1.55 system-ui;margin:2rem auto;max-width:900px;padding:0 1rem}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f5f7;padding:1.25rem;border-radius:10px}</style>'
            '</head><body><pre>' + html_escape(body) + '</pre></body></html>')


def render_batch_report(report: dict, *, output: str = "json") -> str:
    """Aggregate report format. Individual file names and payloads are not included."""
    if output == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    if output not in {"markdown", "html"}:
        raise ValueError("Unsupported batch report type")
    totals = report.get("totals", {})
    lines = ["# Informe de lote · Flipper Zero Protocol Lab", "",
             "Resultado agregado de diagnósticos documentales estáticos.", "",
             f"- Archivos inspeccionados: {min(MAX_BATCH, max(0,int(report.get('files_analyzed',0))))}",
             f"- Válidos: {int(totals.get('valid',0))}",
             f"- Con advertencias: {int(totals.get('warnings',0))}",
             f"- Inválidos: {int(totals.get('invalid',0))}", "", "## Diagnósticos por archivo", ""]
    for n, result in enumerate(report.get("reports", [])[:MAX_BATCH],1):
        fmt = result.get("format") if result.get("format") in FORMATS else "unknown"
        status=result.get("status") if result.get("status") in {"valid","warnings","invalid"} else "unknown"
        codes=sorted({d.get("code") for d in result.get("findings",[]) if isinstance(d,dict) and
                      isinstance(d.get("code"),str) and re.fullmatch(r"[A-Z_]{3,45}",d["code"])})
        lines.append(f"- Archivo {n} ({fmt}): {status}; códigos: {', '.join(codes) if codes else 'ninguno'}")
    lines.extend(["", "Informes redactados: no contienen rutas, capturas, identificadores ni claves."])
    body="\n".join(lines)+"\n"
    return body if output=="markdown" else _plain_html(body)


def render_comparison(report: dict, *, output: str = "json") -> str:
    if output == "json":
        return json.dumps(report, indent=2, ensure_ascii=False)
    if output not in {"markdown", "html"}:
        raise ValueError("Unsupported comparison report type")
    lines = ["# Comparación estructural · Protocol Lab", "",
             "No compara el contenido original de capturas o credenciales.", ""]
    for label in ("before_format", "after_format", "before_status", "after_status"):
        value=report.get(label)
        if value in FORMATS or value in {"valid","invalid","warnings"}:
            lines.append(f"- {label}: {value}")
    for title,key in (("Metadatos","metadata_changes"),("Métricas","metric_changes")):
        lines.extend(["",f"## {title}",""])
        for field, pair in sorted(report.get(key,{}).items()):
            if not re.fullmatch(r"[a-z_]{1,32}",field):
                continue
            before,after=pair.get("before"),pair.get("after")
            def fmt(value):
                if isinstance(value,int):return str(value)
                if isinstance(value,str) and _safe_term(value):return value
                return "no divulgado"
            lines.append(f"- {field}: {fmt(before)} → {fmt(after)}")
    lines.extend(["", "## Códigos de diagnóstico", ""])
    for k in ("added_diagnostic_codes","resolved_diagnostic_codes"):
        codes=[c for c in report.get(k,[]) if isinstance(c,str) and re.fullmatch(r"[A-Z_]{3,45}",c)]
        lines.append(f"- {k}: {', '.join(codes) if codes else 'ninguno'}")
    body="\n".join(lines)+"\n"
    return body if output=="markdown" else _plain_html(body)
