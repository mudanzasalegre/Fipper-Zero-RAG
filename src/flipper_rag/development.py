"""Flipper Zero development assistant (v0.8).

Provides curated examples, static project validation and an explicitly opt-in,
local uFBT build runner. Never executes application.fam while validating, never
flashes/launches devices and never accepts arbitrary build commands via HTTP.
"""
from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import time
from typing import Iterable
from urllib.parse import urlsplit

from .storage import Document, document_id

APP_ID = re.compile(r"[a-z][a-z0-9_]{2,31}\Z")
ENTRY_POINT = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{0,79}\Z")
MAX_PROJECT_FILES = 100
MAX_SOURCE_BYTES = 256_000
MAX_OUTPUT_CHARS = 12_000
DEV_SOURCE_ID = "development-v08"
KNOWN_MJS_MODULES = frozenset({
    "badusb", "event_loop", "flipper", "gpio", "gui", "math",
    "notification", "serial", "storage",
})
SAFE_ORIGINS = frozenset({"developer.flipper.net", "github.com"})
SAFE_FAM_FIELDS = frozenset({"appid", "apptype", "name", "entry_point", "stack_size", "sources",
                              "fap_category", "fap_description", "fap_version", "fap_author", "fap_weburl"})


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    path: str = ""
    line: int = 0
    reference: str = ""

    def as_dict(self):
        return asdict(self)


def diagnostic(severity: str, code: str, message: str, *, path: str = "", line: int = 0,
               reference: str = "") -> Diagnostic:
    return Diagnostic(severity, code, message, path, line, reference)


def valid_relative_path(name: str) -> bool:
    if not isinstance(name, str) or not name or len(name) > 160 or "\\" in name or "\x00" in name:
        return False
    pure = PurePosixPath(name)
    return (not pure.is_absolute() and name == str(pure) and
            all(p not in {"", ".", ".."} for p in pure.parts) and
            all(len(p) <= 80 for p in pure.parts) and
            all(not p.startswith(".") for p in pure.parts))


@lru_cache(maxsize=1)
def catalog() -> dict:
    obj = json.loads(files("flipper_rag").joinpath("data/development_catalog.json").read_text("utf-8"))
    if obj.get("schema_version") != 1:
        raise ValueError("Unsupported development catalog schema")
    for field in ("templates", "guides"):
        ids: set[str] = set()
        if not isinstance(obj.get(field), list):
            raise ValueError("Malformed catalog")
        for item in obj[field]:
            if not isinstance(item, dict) or not re.fullmatch(r"[a-z][a-z0-9-]{2,64}", item.get("id", "")):
                raise ValueError("Invalid catalog entry")
            if item["id"] in ids:
                raise ValueError("Duplicate catalog id")
            ids.add(item["id"])
            if not isinstance(item.get("title"), str) or not isinstance(item.get("references"), list):
                raise ValueError("Invalid catalog metadata")
            for url in item["references"]:
                parsed = urlsplit(url)
                if parsed.scheme != "https" or parsed.hostname not in SAFE_ORIGINS or parsed.username:
                    raise ValueError("Catalog reference is not an allowed official source")
    return obj


def templates() -> list[dict]:
    return catalog()["templates"]


def guides() -> list[dict]:
    return catalog()["guides"]


def get_template(template_id: str) -> dict:
    item = next((t for t in templates() if t["id"] == template_id), None)
    if item is None:
        raise ValueError("Unknown development template")
    directory = files("flipper_rag").joinpath("data/dev_templates", item["id"])
    parts = sorted(p for p in directory.iterdir() if p.is_file())
    if not parts or len(parts) > 12:
        raise ValueError("Template has no files or too many files")
    assets = {}
    for p in parts:
        if not valid_relative_path(p.name.replace("{{APP_ID}}", "sample_app")):
            raise ValueError("Invalid packaged template filename")
        value = p.read_text("utf-8")
        if len(value) > 20000:
            raise ValueError("Template file too large")
        assets[p.name] = value
    return item | {"files": assets}


def scaffold(template_id: str, app_id: str, output: Path, *, name: str = "") -> dict:
    if not APP_ID.fullmatch(app_id):
        raise ValueError("App ID must be 3-32 lowercase letters, digits or underscores, starting with a letter")
    title = name or app_id.replace("_", " ").title()
    if not isinstance(title, str) or not 1 <= len(title) <= 45 or not title.isprintable() or '"' in title or '\\' in title:
        raise ValueError("Invalid app name")
    target = Path(output)
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise ValueError("Destination must not exist or must be an empty directory, without symlinks")
    parent = target.parent
    if not parent.is_dir():
        raise ValueError("Destination parent must already exist")
    spec = get_template(template_id)
    if target.exists() and not target.is_dir():
        raise ValueError("Destination is not a directory")
    substitutions = {"{{APP_ID}}": app_id, "{{ENTRY}}": f"{app_id}_app", "{{APP_NAME}}": title}
    created = []
    target.mkdir(exist_ok=True)
    for filename, content in spec["files"].items():
        for needle, replace in substitutions.items():
            filename = filename.replace(needle, replace)
            content = content.replace(needle, replace)
        if not valid_relative_path(filename) or (target / filename).exists():
            raise ValueError("Unsafe or duplicate template file")
        (target / filename).write_text(content, encoding="utf-8")
        created.append(filename)
    meta = {"schema": 1, "template": template_id, "app_id": app_id,
            "template_sources": spec["references"], "disclaimer": "Project not built or tested on device"}
    (target / ".flipper-rag-project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"template": template_id, "directory": str(target.resolve()),
            "files": created, "verified": "static template rendering only",
            "references": spec["references"]}


def _scan_project(path: Path) -> dict[str, str]:
    if not path.is_dir() or path.is_symlink():
        raise ValueError("Project directory not found or is a symlink")
    sources = {}
    count = 0
    for p in path.rglob("*"):
        # No symlinks, including nested directories. Do not follow into linked trees.
        if p.is_symlink():
            raise ValueError(f"Symlink in project: {p.name}")
        if not p.is_file():
            continue
        rel = p.relative_to(path).as_posix()
        if rel.startswith(".") or any(x.startswith(".") for x in p.relative_to(path).parts):
            continue
        if not valid_relative_path(rel):
            raise ValueError("Unsafe path in project")
        if len(p.relative_to(path).parts) > 5 or p.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Project file exceeds limits")
        if p.suffix not in {".c", ".h", ".cpp", ".fam", ".js", ".md", ".txt"}:
            continue
        count += 1
        if count > MAX_PROJECT_FILES:
            raise ValueError("Too many files in project")
        sources[rel] = p.read_text("utf-8")
    return sources


def parse_fam(content: str) -> dict:
    """Only inspect the Python AST. Explicitly NEVER eval/exec/import the FAM."""
    tree = ast.parse(content, filename="application.fam")
    if len(tree.body) != 1:
        raise ValueError("Expected exactly one App(...) declaration; no other Python statements")
    statement = tree.body[0]
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        raise ValueError("Manifest must contain one App(...) expression")
    call = statement.value
    if not isinstance(call.func, ast.Name) or call.func.id != "App" or call.args:
        raise ValueError("Only a keyword-only App(...) declaration is allowed")
    values = {}
    for kw in call.keywords:
        if kw.arg is None or kw.arg in values:
            raise ValueError("Duplicate or expanded manifest arguments not supported")
        if kw.arg == "apptype" and isinstance(kw.value, ast.Attribute) and isinstance(kw.value.value, ast.Name) and kw.value.value.id == "FlipperAppType":
            values[kw.arg] = kw.value.attr
        else:
            try:
                values[kw.arg] = ast.literal_eval(kw.value)
            except (ValueError, TypeError, RecursionError, MemoryError, SyntaxError) as exc:
                raise ValueError(f"Dynamic or executable manifest field rejected: {kw.arg}") from exc
    return values


def _line(text: str, needle: str) -> int:
    index = text.find(needle)
    return text.count("\n", 0, index) + 1 if index >= 0 else 0


def validate_fap(source: dict[str, str], firmware_graph=None, firmware_ref: str = "") -> list[Diagnostic]:
    issues = []
    fam = source.get("application.fam")
    if fam is None:
        return [diagnostic("error", "fam.missing", "Missing application.fam", path="application.fam")]
    try:
        obj = parse_fam(fam)
    except (ValueError, SyntaxError) as exc:
        return [diagnostic("error", "fam.invalid", str(exc), path="application.fam")]
    for key in obj:
        if key not in SAFE_FAM_FIELDS:
            issues.append(diagnostic("error", "fam.unapproved_field",
                                     f"Manifest field {key} is not supported by the restricted educational build runner",
                                     path="application.fam"))
    appid, entry = obj.get("appid"), obj.get("entry_point")
    if not isinstance(appid, str) or not APP_ID.fullmatch(appid):
        issues.append(diagnostic("error", "fam.appid", "App ID must be a valid lowercase identifier", path="application.fam"))
    if obj.get("apptype") != "EXTERNAL":
        issues.append(diagnostic("error", "fam.apptype", "External FAPs require FlipperAppType.EXTERNAL", path="application.fam"))
    if not isinstance(entry, str) or not ENTRY_POINT.fullmatch(entry):
        issues.append(diagnostic("error", "fam.entry_point", "Missing or invalid C entry_point", path="application.fam"))
    if any(name in obj for name in ("fap_extbuild", "fap_private_libs")):
        issues.append(diagnostic("error", "fam.custom_build", "Custom build hooks/private libraries are not supported in this safe test runner", path="application.fam"))
    stack = obj.get("stack_size", 2048)
    if not isinstance(stack, int) or not 1024 <= stack <= 32768:
        issues.append(diagnostic("error", "fam.stack_size", "stack_size must be 1024..32768 bytes", path="application.fam"))
    sources = obj.get("sources", ["*.c*"])
    if not isinstance(sources, (list,tuple)) or not sources or any(not isinstance(p, str) or not valid_relative_path(p) for p in sources):
        issues.append(diagnostic("error", "fam.sources", "Sources must be safe relative glob patterns", path="application.fam"))
        sources = []
    from fnmatch import fnmatch
    files_c = {p: text for p, text in source.items() if p.endswith((".c", ".cpp"))}
    selected = {p: text for p, text in files_c.items() if any(fnmatch(p, pat) for pat in sources)}
    if not selected:
        issues.append(diagnostic("error", "fap.no_sources", "No C/C++ source matches the manifest", path="application.fam"))
    if isinstance(entry, str) and ENTRY_POINT.fullmatch(entry):
        pattern = re.compile(r"\b(?:int32_t|int)\s+" + re.escape(entry) + r"\s*\(")
        if not any(pattern.search(text) for text in selected.values()):
            issues.append(diagnostic("error", "c.entry_missing", f"Entry point {entry} not found in selected C sources"))
    for filename, text in selected.items():
        if text.count("furi_record_open(") > text.count("furi_record_close("):
            issues.append(diagnostic("warning", "furi.unclosed_record", "More furi_record_open calls than closes; inspect lifecycle", path=filename,
                                     reference="https://developer.flipper.net/flipperzero/doxygen/app_dev_furi_api.html"))
        if "strcpy(" in text or "gets(" in text:
            issues.append(diagnostic("warning", "c.unsafe_string", "Review unchecked string operations", path=filename))
    if firmware_ref:
        if firmware_graph is None:
            issues.append(diagnostic("error", "api.no_index", "Firmware graph is required to check release exports"))
        else:
            try:
                exports = firmware_graph.exports(firmware_ref, limit=500)
                if not exports["results"]:
                    issues.append(diagnostic("warning", "api.missing_exports", "Snapshot contains no export table: API compatibility unknown"))
                else:
                    exported = {x["name"] for x in exports["results"] if x["status"] == "+"}
                    other = {x["name"] for x in exports["results"] if x["status"] != "+"}
                    for filename, text in selected.items():
                        funcs = set(re.findall(r"\b((?:furi|furi_string|view_port|dialog_message|canvas|gui)_[a-zA-Z0-9_]+)\s*\(", text))
                        for func in sorted(funcs - exported):
                            severity = "warning"
                            code = "api.not_exported" if func in other else "api.unverified"
                            issues.append(diagnostic(severity, code, f"{func}: not confirmed as '+' export in this SDK snapshot", path=filename))
            except ValueError as exc:
                issues.append(diagnostic("error", "api.snapshot", str(exc)))
    return issues


def _masked_js(text: str) -> str:
    """Erase comments and strings, retaining newlines and offsets for diagnostics."""
    chars = list(text)
    i = 0
    state = "code"
    while i < len(text):
        c = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code" and c in "'\"`":
            state = c
            chars[i] = " "
        elif state == "code" and c == "/" and nxt == "/":
            state = "line"
            chars[i] = chars[i + 1] = " "
            i += 1
        elif state == "code" and c == "/" and nxt == "*":
            state = "block"
            chars[i] = chars[i + 1] = " "
            i += 1
        elif state == "line":
            if c == "\n": state = "code"
            else: chars[i] = " "
        elif state == "block":
            if c == "*" and nxt == "/":
                chars[i] = chars[i + 1] = " "
                i += 1
                state = "code"
            elif c != "\n": chars[i] = " "
        elif state in {"'", '"', "`"}:
            if c == "\\" and nxt:
                chars[i] = chars[i+1] = " "
                i += 1
            elif c == state:
                chars[i] = " "
                state = "code"
            elif c != "\n": chars[i] = " "
        i += 1
    return "".join(chars)


def validate_mjs(source: dict[str, str]) -> list[Diagnostic]:
    issues: list[Diagnostic] = []
    scripts = {p: x for p, x in source.items() if p.endswith(".js")}
    if not scripts:
        return [diagnostic("error", "js.missing", "No .js Flipper scripts found")]
    if any(p.endswith(".ts") for p in source):
        issues.append(diagnostic("error", "js.ts_sdk", "Raw TypeScript requires the official JS SDK transpiler"))
    for filename, text in scripts.items():
        masked = _masked_js(text)
        stack: list[tuple[str, int]] = []
        closing = {")": "(", "]": "[", "}": "{"}
        for index, ch in enumerate(masked):
            if ch in "([{":
                stack.append((ch,index))
            elif ch in closing:
                if not stack or stack[-1][0] != closing[ch]:
                    issues.append(diagnostic("error", "js.brackets", "Unbalanced delimiter", path=filename,
                                             line=text.count("\n", 0, index)+1))
                    break
                stack.pop()
        else:
            if stack:
                issues.append(diagnostic("error", "js.brackets", "Unclosed delimiter", path=filename,
                                         line=text.count("\n", 0, stack[-1][1])+1))
        for pattern, code, message in (
            (r"\b(?:import|export)\s+(?:\{|\*|const|let|function|default|from|[a-zA-Z_$])", "js.esmodule", "Native mJS scripts use require(), not ESM import/export"),
            (r"\b(?:window|document|process|Buffer|fetch|localStorage)\s*(?:\.|\[|\()", "js.browser_node", "Browser/Node global is not available in Flipper mJS"),
            (r"\b(?:eval|Function)\s*\(", "js.dynamic_code", "Dynamic code generation is not supported by this validator"),
        ):
            m = re.search(pattern, masked)
            if m:
                issues.append(diagnostic("error", code, message, path=filename,
                                         line=text.count("\n", 0, m.start())+1))
        modules = list(re.finditer(r"\brequire\s*\(\s*(['\"])([^'\"\n]+)\1\s*\)", text))
        for m in modules:
            if m.group(2) not in KNOWN_MJS_MODULES:
                issues.append(diagnostic("warning", "js.unknown_module", f"Unverified firmware module: {m.group(2)}", path=filename,
                                         line=text.count("\n", 0, m.start())+1))
        if re.search(r"\brequire\s*\(", masked) and not modules:
            issues.append(diagnostic("warning", "js.dynamic_require", "Dynamic require() cannot be verified", path=filename))
        event_pos = next((m.start() for m in modules if m.group(2) == "event_loop"), -1)
        gpio_positions = [m.start() for m in modules if m.group(2) in {"gpio", "gui"}]
        if gpio_positions and (event_pos < 0 or event_pos > min(gpio_positions)):
            issues.append(diagnostic("error", "js.event_order", "Import event_loop before gpio/gui", path=filename,
                                     reference="https://developer.flipper.net/flipperzero/doxygen/js_gpio.html"))
        if "=>" in masked:
            issues.append(diagnostic("warning", "js.arrow", "Confirm arrow functions are supported by the targeted mJS runtime", path=filename))
        if not text.strip():
            issues.append(diagnostic("warning", "js.empty", "Script is empty", path=filename))
    return issues


def validate_project(path: str | Path, *, kind: str = "auto", firmware_ref: str = "",
                     graph=None) -> dict:
    if kind not in {"auto", "fap", "mjs"}:
        raise ValueError("Unknown project kind")
    source = _scan_project(Path(path))
    actual = "fap" if "application.fam" in source else "mjs"
    if kind == "fap" and actual != "fap":
        issues = [diagnostic("error", "fap.not_found", "FAP manifest missing")]
    elif kind == "mjs" and actual == "fap":
        issues = [diagnostic("error", "js.fap_found", "FAP manifest found; select FAP validator")]
    elif actual == "fap":
        issues = validate_fap(source, firmware_graph=graph, firmware_ref=firmware_ref)
    else:
        issues = validate_mjs(source)
    return {"valid": not any(x.severity == "error" for x in issues),
            "kind": actual, "files_checked": len(source),
            "diagnostics": [x.as_dict() for x in issues],
            "validation": "static, not a compiler or mJS runtime",
            "firmware_ref": firmware_ref or None}


def _safe_log(text: str) -> str:
    text = re.sub(r"(?i)\b(token|password|secret|api[_-]?key)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    return text[-MAX_OUTPUT_CHARS:]


def build_fap(path: str | Path, *, execute: bool = False, ufbt_binary: str = "ufbt",
              timeout: int = 600, firmware_ref: str = "", graph=None) -> dict:
    """Compile locally using exact ['ufbt'] argv; never launch, flash, or run device commands.

    Does NOT provide a sandbox. SDK/bootstrap and app build scripts may execute
    code and fetch dependencies; callers must trust the project and toolchain.
    """
    if not 30 <= timeout <= 900:
        raise ValueError("Build timeout must be between 30 and 900 seconds")
    project = Path(path).resolve(strict=True)
    report = validate_project(project, kind="fap", firmware_ref=firmware_ref, graph=graph)
    if not report["valid"]:
        return {"status": "invalid", "validation": report, "executed": False}
    if not execute:
        return {"status": "dry-run", "executed": False, "command": [ufbt_binary],
                "cwd": str(project), "validation": report,
                "warning": "Real build requires --execute and trusted source; may download SDK and execute build scripts. No flash/launch."}
    if os.sep in ufbt_binary or (os.altsep and os.altsep in ufbt_binary):
        binary = Path(ufbt_binary).resolve(strict=True)
        if not binary.is_file():
            raise ValueError("uFBT binary path is not a file")
    else:
        if ufbt_binary != "ufbt":
            raise ValueError("Only ufbt command name is allowed, or specify an explicit executable path")
        found = shutil.which("ufbt")
        if not found:
            raise ValueError("uFBT not installed: python -m pip install ufbt")
        binary = Path(found).resolve()
    if (project / "dist").is_symlink():
        raise ValueError("Build output directory must not be a symlink")
    previous = {}
    for p in (project / "dist").rglob("*.fap") if (project / "dist").is_dir() else []:
        if p.is_file() and not p.is_symlink():
            previous[str(p.relative_to(project))] = sha256(p.read_bytes()).hexdigest()
    env = {k: v for k, v in os.environ.items() if not re.search(r"(?:TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY)", k, re.I)}
    env.pop("PYTHONPATH", None)
    start = time.monotonic()
    try:
        outcome = subprocess.run([str(binary)], cwd=str(project), env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        return {"status": "timeout", "executed": True, "duration_s": round(time.monotonic()-start, 2),
                "output": _safe_log(str(exc.stdout or "")), "artifacts": [], "validation": report}
    artifacts = []
    for p in (sorted((project / "dist").rglob("*.fap"))[:100] if (project / "dist").is_dir() else []):
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 100_000_000:
            continue
        relative = str(p.relative_to(project))
        digest = sha256(p.read_bytes()).hexdigest()
        artifacts.append({"path": relative, "sha256": digest, "size": p.stat().st_size,
                          "content_changed": previous.get(relative) != digest})
    return {"status": "passed" if outcome.returncode == 0 and artifacts else
                      "failed" if outcome.returncode else "no-artifact",
            "executed": True, "returncode": outcome.returncode,
            "duration_s": round(time.monotonic()-start, 2), "artifacts": artifacts,
            "output": _safe_log(outcome.stdout), "validation": report,
            "note": "Build result only. No device execution, firmware flashing or runtime compatibility verification."}


def development_documents() -> Iterable[Document]:
    """Original editorial summaries with official links; always local/unversioned provenance."""
    for item in guides():
        body = (f"# {item['title']}\n\nTopics: {', '.join(item['tags'])}\n\n"
                f"{item['summary']}\n\nOfficial sources:\n" + "\n".join(item["references"]))
        yield Document(doc_id=document_id(DEV_SOURCE_ID, item["id"]), source_id=DEV_SOURCE_ID,
                       title="Development / " + item["title"], url=item["references"][0],
                       category="development", body=body, revision="0.8.0", trust="local",
                       license="Original technical summary; verify official SDK documentation",
                       firmware_channel="unversioned")
    for item in templates():
        body = (f"# Example: {item['title']}\n\nLanguage: {item['language']}\n"
                f"Project type: {item['kind']}\n\n{item['description']}\n\n"
                f"CLI: flipper-rag dev scaffold --template {item['id']} --appid demo_app --output ./demo_app\n"
                "This is an original demonstration template; not compiled or tested on device by indexing it.\n"
                "Sources:\n" + "\n".join(item["references"]))
        yield Document(doc_id=document_id(DEV_SOURCE_ID, "template-" + item["id"]),
                       source_id=DEV_SOURCE_ID, title="Development example / " + item["title"],
                       url=item["references"][0], category="development", body=body,
                       revision="0.8.0", trust="local", firmware_channel="unversioned",
                       license="Original example; verify upstream API before deployment")
