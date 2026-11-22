"""Conservative firmware provenance. Unversioned sources are never certified compatible."""
from __future__ import annotations
import re
from dataclasses import dataclass

VERSION_RE = re.compile(r"v?(\d{1,3})\.(\d{1,3})(?:\.(\d{1,3}))?(?:-(rc(?:\.\d+)?))?", re.I)


def normalize_version(value: str) -> str:
    """Accept a release or RC tag, not arbitrary Git refs or version ranges."""
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise ValueError("Firmware version must be a release tag, e.g. 1.5.1 or 1.5.1-rc")
    a, b, c, rc = match.groups()
    version = f"{int(a)}.{int(b)}.{int(c or 0)}"
    return version + (f"-{rc.lower()}" if rc else "")


def channel_for_ref(ref: str) -> str:
    if ref.lower() == "dev":
        return "dev"
    try:
        return "rc" if "-rc" in normalize_version(ref) else "release"
    except ValueError:
        return "unversioned"


def firmware_source_for_ref(spec: dict, ref: str) -> dict:
    """Keep tagged firmware snapshots separate from moving dev snapshots."""
    if spec.get("id") != "firmware-oficial":
        raise ValueError("Versioned sync is only supported for official firmware")
    normalized = normalize_version(ref)
    # The upstream tag may have a leading v; keep exactly what Git expects.
    suffix = re.sub(r"[^a-zA-Z0-9_-]", "_", normalized)
    return {**spec, "id": f"firmware-oficial-v{suffix}", "branch": ref,
            "firmware_version": normalized, "firmware_channel": channel_for_ref(ref)}


@dataclass(frozen=True)
class Compatibility:
    status: str
    note: str


def compatibility(document_version: str, document_channel: str, requested_version: str | None) -> Compatibility:
    if not requested_version:
        return Compatibility("not_checked", "No firmware version requested")
    target = normalize_version(requested_version)
    if document_version:
        try:
            if normalize_version(document_version) == target:
                return Compatibility("exact_snapshot", "Source explicitly indexed for this firmware release")
        except ValueError:
            pass
        return Compatibility("different_version", "Source targets a different firmware version")
    if document_channel == "dev":
        return Compatibility("unverified", "Moving development branch; not verified for the requested release")
    return Compatibility("unverified", "Source does not specify firmware compatibility")
