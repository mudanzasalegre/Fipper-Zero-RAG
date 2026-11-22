"""Flipper Zero Protocol Intelligence v0.6: evidence-first ontology and comparisons.

Read-only and deterministic. Distinguishes upstream *source presence*, a file-format
entry, an operation documented by the manufacturer, and a release-specific test.
Neither inherited family properties nor missing evidence certify device support.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json
import re
import unicodedata
from urllib.parse import urlsplit
from typing import Iterable, Mapping, Sequence

SCHEMA_VERSION = 1
OPERATIONS = frozenset({
    "read", "save", "decode", "parse_file", "emulate_uid", "emulate_data",
    "write", "receive", "transmit", "operate_interface", "source_identified"
})
STATUSES = frozenset({"documented", "limited", "not_supported", "unknown"})
RELATION_TYPES = frozenset({"variant_of", "layered_over", "related_to", "contrasts_with"})
DOC_SOURCE_ID = "ontologia-protocolos-v06"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,90}$")


def _fold(value: str) -> str:
    val = unicodedata.normalize("NFKD", value.casefold())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in val if not unicodedata.combining(c))).strip()


def _official_reference(value: str) -> bool:
    """Evidence URLs must be canonical official HTTPS paths without credentials."""
    if not isinstance(value, str) or len(value) > 600:
        return False
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    try:
        if parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    if parsed.hostname == "docs.flipper.net":
        return parsed.path.startswith("/zero/")
    if parsed.hostname == "developer.flipper.net":
        return parsed.path.startswith("/flipperzero/doxygen/")
    if parsed.hostname == "github.com":
        return bool(re.fullmatch(r"/flipperdevices/[a-zA-Z0-9._-]+/blob/[0-9a-f]{40}/[a-zA-Z0-9/_+.-]+", parsed.path))
    return False


def _validate_evidence(claim: Mapping, location: str) -> None:
    if not isinstance(claim, dict):
        raise ValueError(f"{location}: evidence claim must be an object")
    if not _official_reference(claim.get("reference")):
        raise ValueError(f"{location}: missing or nonofficial evidence URL")
    if claim.get("scope") not in {"protocol", "family", "file-format", "dev-snapshot", "variant"}:
        raise ValueError(f"{location}: unrecognized evidence scope")
    if not isinstance(claim.get("note"), str) or not (8 <= len(claim["note"]) <= 500):
        raise ValueError(f"{location}: evidence requires a precise explanatory note")
    if claim.get("firmware_version"):
        if not re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-rc(?:\.[0-9]+)?)?", claim["firmware_version"]):
            raise ValueError(f"{location}: invalid firmware release")
    if claim.get("scope") == "dev-snapshot" and "/blob/" not in claim["reference"]:
        raise ValueError(f"{location}: development evidence must pin the Git commit")


def validate_ontology(data: Mapping, catalog: Sequence[Mapping]) -> dict:
    """Validate data and cross-references; refuse unsupported capability assertions."""
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported ontology schema")
    if not isinstance(catalog, (list, tuple)) or not catalog:
        raise ValueError("Protocol catalog is missing")
    ids = set()
    families = set()
    for proto in catalog:
        if not isinstance(proto, dict) or not ID_PATTERN.fullmatch(str(proto.get("id", ""))):
            raise ValueError("Malformed protocol catalog identifier")
        if proto["id"] in ids:
            raise ValueError("Duplicate protocol identifier")
        ids.add(proto["id"])
        families.add(proto["family"])
    family_specs = data.get("families")
    if not isinstance(family_specs, dict) or set(family_specs) != families:
        raise ValueError("Ontology must specify exactly the catalog families")
    for family, spec in family_specs.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("label"), str) or not isinstance(spec.get("medium"), str):
            raise ValueError(f"Invalid family {family}")
        _validate_evidence(spec.get("evidence"), f"family {family}")
        if spec["evidence"]["scope"] != "family":
            raise ValueError(f"family {family}: evidence must be family scope")
        if spec.get("format") is not None and not re.fullmatch(r"\.[a-z0-9]{2,8}", spec["format"]):
            raise ValueError(f"family {family}: malformed file format")
        if spec.get("frequency_hz") is not None and (type(spec["frequency_hz"]) is not int or not (1 <= spec["frequency_hz"] <= 10_000_000_000)):
            raise ValueError(f"family {family}: invalid nominal frequency")
        if spec.get("frequency_range_hz") is not None:
            rng = spec["frequency_range_hz"]
            if not isinstance(rng, list) or len(rng) != 2 or any(type(x) is not int for x in rng) or not 0 < rng[0] < rng[1] < 10_000_000_000:
                raise ValueError(f"family {family}: invalid frequency range")
    if not isinstance(data.get("rules"), list) or not isinstance(data.get("profiles"), dict):
        raise ValueError("Ontology must contain rule list and profile map")
    seen_rules = set()
    for n, rule in enumerate(data["rules"]):
        if not isinstance(rule, dict) or rule.get("family") not in families:
            raise ValueError(f"Rule {n}: invalid family")
        if not isinstance(rule.get("evidence_scope"), str) or not rule["evidence_scope"]:
            raise ValueError(f"Rule {n}: missing evidence scope")
        key = (rule["family"], rule["evidence_scope"])
        if key in seen_rules:
            raise ValueError(f"Duplicate rule {key}")
        seen_rules.add(key)
        _validate_capabilities(rule.get("capabilities", {}), f"rule {n}")
        _validate_tags(rule.get("features", []), f"rule {n}")
    for pid, profile in data["profiles"].items():
        if pid not in ids or not isinstance(profile, dict):
            raise ValueError(f"Unknown or malformed profile: {pid}")
        _validate_capabilities(profile.get("capabilities", {}), f"profile {pid}")
        _validate_tags(profile.get("features", []), f"profile {pid}")
        if "notes" in profile and (not isinstance(profile["notes"], list) or any(not isinstance(x, str) or len(x) > 400 for x in profile["notes"])):
            raise ValueError(f"profile {pid}: invalid notes")
        if "attributes" in profile:
            if not isinstance(profile["attributes"], dict):
                raise ValueError(f"profile {pid}: invalid attributes")
            for name, attr in profile["attributes"].items():
                if not ID_PATTERN.fullmatch(name):
                    raise ValueError(f"profile {pid}: invalid attribute name")
                if not isinstance(attr, dict) or not isinstance(attr.get("value"), (str, int, float, bool)):
                    raise ValueError(f"profile {pid}: malformed attribute {name}")
                _validate_evidence(attr.get("evidence"), f"attribute {pid}.{name}")
    if not isinstance(data.get("relations"), list):
        raise ValueError("Missing relation list")
    edges = set()
    for n, edge in enumerate(data["relations"]):
        if not isinstance(edge, dict) or edge.get("source") not in ids or edge.get("target") not in ids:
            raise ValueError(f"Relation {n} references unknown protocol")
        if edge["source"] == edge["target"] or edge.get("type") not in RELATION_TYPES:
            raise ValueError(f"Relation {n}: invalid relationship")
        key = (edge["source"], edge["type"], edge["target"])
        if key in edges:
            raise ValueError(f"Relation {n}: duplicate edge")
        edges.add(key)
        _validate_evidence(edge.get("evidence"), f"relation {n}")
    # A directed layer or inheritance graph must never contain a cycle.
    follow = defaultdict(list)
    for src, rel, dst in edges:
        if rel in {"variant_of", "layered_over"}:
            follow[src].append(dst)
    visiting, visited = set(), set()
    def visit(pid: str) -> None:
        if pid in visiting:
            raise ValueError("Cyclic variant/layer relationship")
        if pid in visited:
            return
        visiting.add(pid)
        for ancestor in follow[pid]:
            visit(ancestor)
        visiting.remove(pid)
        visited.add(pid)
    for pid in ids:
        visit(pid)
    return data


def _validate_tags(tags: object, place: str) -> None:
    if not isinstance(tags, list) or len(tags) > 30 or any(not isinstance(t, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", t) for t in tags):
        raise ValueError(f"{place}: invalid tags")
    if len(set(tags)) != len(tags):
        raise ValueError(f"{place}: duplicate tags")


def _validate_capabilities(caps: object, place: str) -> None:
    if not isinstance(caps, dict):
        raise ValueError(f"{place}: capabilities must be an object")
    for op, assertion in caps.items():
        if op not in OPERATIONS or not isinstance(assertion, dict) or assertion.get("status") not in STATUSES:
            raise ValueError(f"{place}: invalid capability {op}")
        if assertion["status"] != "unknown":
            _validate_evidence(assertion.get("evidence"), f"{place}: {op}")
        elif "evidence" in assertion:
            raise ValueError(f"{place}: unknown status must not masquerade as sourced")


class ProtocolIntelligence:
    """Read-only ontology with conservative evidence and deterministic filtering."""
    def __init__(self, catalog: Sequence[Mapping], ontology: Mapping):
        self.data = validate_ontology(dict(ontology), list(catalog))
        self.catalog = {entry["id"]: dict(entry) for entry in catalog}
        self._cards = {}
        for pid, entry in self.catalog.items():
            family = entry["family"]
            caps, tags = {}, []
            for rule in self.data["rules"]:
                if rule["family"] == family and rule["evidence_scope"] == entry["evidence_scope"]:
                    caps.update(deepcopy(rule.get("capabilities", {})))
                    tags.extend(rule.get("features", []))
            profile = self.data["profiles"].get(pid, {})
            # Explicit protocol assertions override only claims having their own reference.
            caps.update(deepcopy(profile.get("capabilities", {})))
            tags.extend(profile.get("features", []))
            self._cards[pid] = {
                **deepcopy(entry), "features": sorted(set(tags)), "capabilities": caps,
                "attributes": deepcopy(profile.get("attributes", {})),
                "notes": list(profile.get("notes", [])),
                "family_context": deepcopy(self.data["families"][family]),
                "relations": [],
            }
        for edge in self.data["relations"]:
            self._cards[edge["source"]]["relations"].append(deepcopy(edge))
            # Symmetric links are discoverable from either side, but provenance remains directed.
            if edge["type"] in {"related_to", "contrasts_with"}:
                flipped = deepcopy(edge)
                flipped["source"], flipped["target"] = edge["target"], edge["source"]
                flipped["inverse_of"] = edge["source"]
                self._cards[edge["target"]]["relations"].append(flipped)
        for card in self._cards.values():
            card["relations"].sort(key=lambda x: (x["type"], x["target"]))

    def __len__(self) -> int:
        return len(self._cards)

    def resolve(self, value: str) -> str | None:
        if not isinstance(value, str) or not value.strip() or len(value) > 120:
            return None
        key = _fold(value)
        found = [p for p, c in self._cards.items() if key in {_fold(p), _fold(c["name"]), *(_fold(x) for x in c.get("aliases", []))}]
        return found[0] if len(found) == 1 else None

    def card(self, value: str, *, firmware_version: str | None = None) -> dict | None:
        pid = self.resolve(value)
        if pid is None:
            return None
        output = deepcopy(self._cards[pid])
        if firmware_version:
            from .versioning import normalize_version
            ver = normalize_version(firmware_version)
            output["requested_firmware_version"] = ver
            for cap in output["capabilities"].values():
                evidence = cap.get("evidence", {})
                verified = evidence.get("firmware_version") == ver
                cap["documentation_status"] = cap["status"]
                cap["version_compatibility"] = "documented_for_release" if verified else "not_verified_for_release"
                if not verified:
                    cap["status"] = "unknown"  # Unknown specifically for requested release, not globally.
            output["firmware_warning"] = "Las pruebas de documentación genérica o dev no certifican compatibilidad con esta release."
        return output

    def capabilities(self, protocol: str, *, firmware_version: str | None = None) -> dict[str, dict]:
        card = self.card(protocol, firmware_version=firmware_version)
        if card is None:
            raise ValueError(f"Unknown or ambiguous protocol: {protocol}")
        return {op: deepcopy(card["capabilities"].get(op, {"status": "unknown"})) for op in sorted(OPERATIONS)}

    def search(self, *, query: str = "", family: str | None = None, feature: str | None = None,
               capability: str | None = None, status: str = "documented", medium: str | None = None,
               file_format: str | None = None, frequency_hz: int | None = None,
               related_to: str | None = None, limit: int = 100) -> list[dict]:
        if len(query) > 200:
            raise ValueError("Search query too long")
        if family is not None and family not in self.data["families"]:
            raise ValueError("Unknown protocol family")
        if capability is not None and capability not in OPERATIONS:
            raise ValueError("Unknown capability")
        if status not in STATUSES.union({"any", "established"}):
            raise ValueError("Unknown status")
        if frequency_hz is not None and (type(frequency_hz) is not int or not (0 < frequency_hz < 10_000_000_000)):
            raise ValueError("Invalid frequency in Hz")
        if related_to is not None:
            target = self.resolve(related_to)
            if not target:
                raise ValueError("Unknown related protocol")
        else:
            target = None
        if file_format and not re.fullmatch(r"\.[a-z0-9]{2,8}", file_format):
            raise ValueError("Invalid file format")
        if feature and not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", feature):
            raise ValueError("Invalid feature")
        terms = _fold(query).split()
        found = []
        for pid in sorted(self._cards):
            card = self._cards[pid]
            ctx = card["family_context"]
            if family and card["family"] != family:
                continue
            if feature and feature not in card["features"]:
                continue
            if medium and _fold(ctx["medium"]) != _fold(medium):
                continue
            if file_format and ctx.get("format") != file_format:
                continue
            if frequency_hz and ctx.get("frequency_hz") != frequency_hz:
                # A *family* frequency range does not certify that every protocol
                # works on the requested particular channel.
                continue
            if target and not any(rel["target"] == target for rel in card["relations"]):
                continue
            if capability:
                assertion = card["capabilities"].get(capability, {"status": "unknown"})
                state = assertion["status"]
                if status == "established":
                    if state not in {"documented", "limited"}:
                        continue
                elif status != "any" and state != status:
                    continue
            haystack = _fold(" ".join([pid, card["name"], card["family"], card["layer"],
                                       card.get("summary", ""), *card.get("aliases", []),
                                       *card["features"], *card["notes"]]))
            if terms and not all(term in haystack for term in terms):
                continue
            found.append(deepcopy(card))
            if len(found) >= max(1, min(limit, 250)):
                break
        return found

    def compare(self, names: Sequence[str], *, firmware_version: str | None = None) -> dict:
        if not 2 <= len(names) <= 8:
            raise ValueError("Compare between 2 and 8 protocols")
        ids = [self.resolve(v) for v in names]
        if any(x is None for x in ids) or len(set(ids)) != len(ids):
            raise ValueError("Unknown, ambiguous, or duplicated protocol")
        cards = [self.card(pid, firmware_version=firmware_version) for pid in ids]
        fields = ("family", "layer", "evidence_scope")
        dimensions = {f: {c["id"]: c[f] for c in cards} for f in fields}
        dimensions["medium"] = {c["id"]: c["family_context"]["medium"] for c in cards}
        dimensions["family_frequency_hz"] = {c["id"]: c["family_context"].get("frequency_hz") for c in cards}
        dimensions["file_format"] = {c["id"]: c["family_context"].get("format") for c in cards}
        capabilities = {op: {c["id"]: deepcopy(c["capabilities"].get(op, {"status": "unknown"})) for c in cards} for op in sorted(OPERATIONS)}
        similarities = [name for name, values in dimensions.items() if len(set(map(str, values.values()))) == 1]
        differences = [name for name in dimensions if name not in similarities]
        differences.extend(op for op, values in capabilities.items() if len({c["status"] for c in values.values()}) > 1)
        return {
            "protocol_ids": ids, "dimensions": dimensions, "capabilities": capabilities,
            "similarities": similarities, "differences": differences,
            "firmware_version": firmware_version,
            "warning": "Desconocido no equivale a incompatible. Los datos de familia son contexto, no capacidades certificadas por versión.",
            "cards": cards,
        }

    def neighbors(self, protocol: str, *, depth: int = 1) -> dict:
        pid = self.resolve(protocol)
        if not pid:
            raise ValueError("Unknown or ambiguous protocol")
        if not 1 <= depth <= 3:
            raise ValueError("depth must be between 1 and 3")
        # Follow only curated protocol-to-protocol edges; avoid flooding through family hubs.
        visited = {pid}
        frontier = deque([(pid, 0)])
        edges = {}
        # Directed relationships can be inspected from either endpoint without
        # reversing the semantic direction of "layered_over" or "variant_of".
        incoming = defaultdict(list)
        for rel in self.data["relations"]:
            incoming[rel["target"]].append(rel)
        while frontier:
            node, steps = frontier.popleft()
            if steps == depth:
                continue
            candidates = [(e, e["target"], "outgoing") for e in self._cards[node]["relations"]]
            candidates.extend((e, e["source"], "incoming") for e in incoming[node])
            for edge, neighbor, direction in candidates:
                key = (edge["source"], edge["type"], edge["target"])
                edges[key] = {**deepcopy(edge), "direction_from_root": direction}
                if neighbor not in visited:
                    visited.add(neighbor)
                    frontier.append((neighbor, steps + 1))
        return {"root": pid, "depth": depth,
                "nodes": [{"id": x, "name": self._cards[x]["name"], "family": self._cards[x]["family"]} for x in sorted(visited)],
                "edges": [edges[key] for key in sorted(edges)]}

    def graph(self) -> dict:
        """Typed graph with source-level edges; no automated equivalence inference."""
        nodes, edges = [], []
        for family, spec in sorted(self.data["families"].items()):
            nodes.append({"id": f"family:{family}", "kind": "family", "name": spec["label"], "medium": spec["medium"]})
            if spec.get("format"):
                fid = f"format:{spec['format']}"
                if not any(n["id"] == fid for n in nodes):
                    nodes.append({"id": fid, "kind": "file-format", "name": spec["format"]})
                edges.append({"source": f"family:{family}", "target": fid, "type": "documents_with",
                              "evidence": spec["evidence"], "scope": "family"})
        for pid, card in sorted(self._cards.items()):
            nodes.append({"id": f"protocol:{pid}", "kind": "protocol", "name": card["name"], "family": card["family"]})
            edges.append({"source": f"protocol:{pid}", "target": f"family:{card['family']}",
                          "type": "member_of", "evidence": {"reference": card["reference"], "scope": "protocol", "note": "Clasificación del registro curado"}})
        for rel in self.data["relations"]:
            edges.append({"source": f"protocol:{rel['source']}", "target": f"protocol:{rel['target']}",
                          "type": rel["type"], "evidence": deepcopy(rel["evidence"])})
        return {"schema_version": SCHEMA_VERSION, "nodes": nodes, "edges": edges, "protocol_count": len(self)}

    def jsonld(self) -> dict:
        graph = self.graph()
        prefix = "https://github.com/mudanzasalegre/Fipper-Zero-RAG/blob/main/docs/ONTOLOGY_V06.md#"
        records = []
        for node in graph["nodes"]:
            records.append({"@id": "urn:flipper-rag:" + node["id"], "@type": prefix + node["kind"],
                            "http://www.w3.org/2000/01/rdf-schema#label": node["name"]})
        for n, edge in enumerate(graph["edges"]):
            records.append({"@id": f"urn:flipper-rag:edge:{n}", "@type": prefix + "EvidenceRelation",
                            prefix + "source": {"@id": "urn:flipper-rag:" + edge["source"]},
                            prefix + "target": {"@id": "urn:flipper-rag:" + edge["target"]},
                            prefix + "relation": edge["type"],
                            "http://www.w3.org/ns/prov#wasDerivedFrom": {"@id": edge["evidence"]["reference"]}})
        return {"@graph": records}

    def documents(self) -> Iterable:
        """Machine-readable grounding as local-trust documents with explicit evidence."""
        from .storage import Document, document_id
        for pid in sorted(self._cards):
            card = self._cards[pid]
            caps = card["capabilities"]
            summary = [f"# Ficha de protocolo: {card['name']}", f"Identificador: {pid}",
                       f"Familia: {card['family']}", f"Capa: {card['layer']}",
                       f"Interfaz: {card['family_context']['medium']} (contexto de familia, no compatibilidad certificada)",
                       f"Fuente de catálogo: {card['reference']}"]
            for op in sorted(OPERATIONS):
                claim = caps.get(op)
                if claim:
                    ev = claim.get("evidence", {})
                    summary.append(f"Operación {op}: {claim['status']} — {ev.get('note','Sin evidencia verificada')}; alcance {ev.get('scope','no documentado')}; {ev.get('reference','')}")
                else:
                    summary.append(f"Operación {op}: desconocida; no inferir capacidad")
            for rel in card["relations"]:
                summary.append(f"Relación editorial {rel['type']} -> {rel['target']}: {rel['evidence']['note']}; fuente {rel['evidence']['reference']}")
            summary.extend(card["notes"])
            summary.append("ADVERTENCIA: no se verifica compatibilidad con ninguna release específica sin prueba versionada; ni soporte físico ni legalidad de transmisiones.")
            yield Document(doc_id=document_id(DOC_SOURCE_ID, pid), source_id=DOC_SOURCE_ID,
                           title=f"Ontología / {card['family']} / {card['name']}", url=card["reference"],
                           category=card["family"], body="\n\n".join(summary), revision="v0.6-ontology-2026-11-22",
                           license="Original local curation; consult original sources", trust="local",
                           firmware_channel="unversioned")


def evaluate_ontology(engine: ProtocolIntelligence, cases: Sequence[Mapping]) -> dict:
    """Offline deterministic retrieval/capability checks; not LLM answer accuracy."""
    if not cases:
        raise ValueError("Empty ontology evaluation suite")
    details = []
    positives = 0
    hits = 0
    negatives = 0
    negative_hits = 0
    for number, case in enumerate(cases, 1):
        if not isinstance(case, dict) or not isinstance(case.get("filters"), dict):
            raise ValueError(f"Malformed ontology benchmark case {number}")
        expected = case.get("expect_ids", [])
        absent = case.get("exclude_ids", [])
        if not isinstance(expected, list) or not isinstance(absent, list):
            raise ValueError("Malformed expected/excluded protocol IDs")
        args = dict(case["filters"])
        args["limit"] = 200
        actual = [entry["id"] for entry in engine.search(**args)]
        good = all(identifier in actual for identifier in expected) and all(identifier not in actual for identifier in absent)
        if case.get("should_be_empty"):
            good = good and not actual
            negatives += 1
            negative_hits += int(not actual)
        else:
            positives += len(expected)
            hits += sum(identifier in actual for identifier in expected)
        details.append({"case": number, "question": case.get("question", ""),
                        "success": good, "expected": expected, "excluded": absent,
                        "actual": actual[:25], "matches": len(actual)})
    return {"cases": len(cases), "passed": all(case["success"] for case in details),
            "positive_recall": round(hits / positives, 4) if positives else None,
            "negative_accuracy": round(negative_hits / negatives, 4) if negatives else None,
            "successes": sum(case["success"] for case in details), "details": details,
            "limitation": "Evalúa filtros y datos curatoriales offline, no la exactitud de generación ni el firmware real"}


def load_benchmark(path) -> list[dict]:
    from pathlib import Path
    cases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases


@lru_cache(maxsize=1)
def get_intelligence() -> ProtocolIntelligence:
    # Lazy import allows deterministic unit tests with small fixtures, no DB/model.
    from .protocols import all_protocols
    data = json.loads(files("flipper_rag").joinpath("data/ontology_v06.json").read_text(encoding="utf-8"))
    return ProtocolIntelligence(list(all_protocols()), data)


def add_parser(subparsers) -> None:
    p = subparsers.add_parser("ontology", help="Protocol ontology, capabilities, comparisons and evidence graph")
    p.add_argument("action", choices=("validate", "stats", "search", "show", "compare", "related", "graph", "index", "eval"))
    p.add_argument("ids", nargs="*")
    p.add_argument("--query", default="")
    p.add_argument("--family")
    p.add_argument("--feature")
    p.add_argument("--capability", choices=sorted(OPERATIONS))
    p.add_argument("--status", choices=sorted(STATUSES | {"established", "any"}), default="established")
    p.add_argument("--medium")
    p.add_argument("--file-format")
    p.add_argument("--frequency-hz", type=int)
    p.add_argument("--related-to")
    p.add_argument("--firmware-version")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--format", choices=("json", "jsonld"), default="json")
    p.add_argument("--file", default="benchmarks/ontology_v06.jsonl", help="Offline ontology benchmark (JSONL)")


def cli_result(args, store, embedder) -> dict:
    intelligence = get_intelligence()
    if args.action == "validate":
        return {"valid": True, "protocols": len(intelligence), "profiles": len(intelligence.data["profiles"]),
                "rules": len(intelligence.data["rules"]), "relations": len(intelligence.data["relations"])}
    if args.action == "stats":
        per_family = defaultdict(int)
        for card in intelligence._cards.values():
            per_family[card["family"]] += 1
        return {"protocols": len(intelligence), "families": dict(sorted(per_family.items())),
                "profiles": len(intelligence.data["profiles"]), "relations": len(intelligence.data["relations"])}
    if args.action == "search":
        return {"results": intelligence.search(query=args.query, family=args.family, feature=args.feature,
                capability=args.capability, status=args.status, medium=args.medium,
                file_format=args.file_format, frequency_hz=args.frequency_hz,
                related_to=args.related_to, limit=args.limit)}
    if args.action == "show":
        if len(args.ids) != 1:
            raise ValueError("show requires exactly one protocol ID")
        found = intelligence.card(args.ids[0], firmware_version=args.firmware_version)
        if found is None:
            raise ValueError("Unknown or ambiguous protocol")
        return found
    if args.action == "compare":
        return intelligence.compare(args.ids, firmware_version=args.firmware_version)
    if args.action == "related":
        if len(args.ids) != 1:
            raise ValueError("related requires exactly one protocol ID")
        return intelligence.neighbors(args.ids[0], depth=args.depth)
    if args.action == "graph":
        return intelligence.jsonld() if args.format == "jsonld" else intelligence.graph()
    if args.action == "eval":
        return evaluate_ontology(intelligence, load_benchmark(args.file))
    if args.action == "index":
        from .sources import index_documents
        report = index_documents(store, intelligence.documents(), embedder)
        store.record_sync(DOC_SOURCE_ID, report)
        return {"indexed": report, "source_id": DOC_SOURCE_ID,
                "note": "Ontology documents are curated/local, not official or release-specific"}
    raise ValueError("Unknown action")
