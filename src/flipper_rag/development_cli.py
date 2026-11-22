"""Development assistant CLI; all builds require an explicit --execute flag."""
from __future__ import annotations

import shutil
from pathlib import Path

from .development import (build_fap, catalog, development_documents, get_template,
                          guides, scaffold, templates, validate_project)
from .firmware_graph import FirmwareGraph
from .sources import index_documents


def add_parser(subparsers):
    top = subparsers.add_parser("dev", help="Scaffold, validate, build and learn Flipper application development")
    cmds = top.add_subparsers(dest="dev_action", required=True)
    cmds.add_parser("templates", help="List Furi C and mJS example templates")
    tpl = cmds.add_parser("template", help="Display a template and its original source")
    tpl.add_argument("--id", required=True)
    cmds.add_parser("guides", help="List source-cited development guides")
    guide = cmds.add_parser("guide", help="Show one development guide")
    guide.add_argument("--id", required=True)
    sc = cmds.add_parser("scaffold", help="Create a new app project from a vetted tutorial template")
    sc.add_argument("--template", required=True)
    sc.add_argument("--appid", required=True)
    sc.add_argument("--output", type=Path, required=True)
    sc.add_argument("--name", default="")
    val = cmds.add_parser("validate", help="Static check: FAM, Furi C or native mJS")
    val.add_argument("--project", type=Path, required=True)
    val.add_argument("--kind", choices=("auto", "fap", "mjs"), default="auto")
    val.add_argument("--firmware-ref", default="", help="Optional previously indexed firmware ref for FAP export checks")
    build = cmds.add_parser("build", help="Plan or opt-in execute an offline-from-device uFBT FAP build")
    build.add_argument("--project", type=Path, required=True)
    build.add_argument("--execute", action="store_true", help="Actually run local ufbt (may fetch SDK and execute build hooks)")
    build.add_argument("--ufbt-path", default="ufbt", help="Exact path to uFBT executable (default system ufbt)")
    build.add_argument("--timeout", type=int, default=600)
    build.add_argument("--firmware-ref", default="")
    smoke = cmds.add_parser("smoke", help="Scaffold and optionally compile 3 packaged FAP test apps")
    smoke.add_argument("--output", type=Path, required=True, help="Existing empty directory for disposable test projects")
    smoke.add_argument("--execute", action="store_true")
    smoke.add_argument("--ufbt-path", default="ufbt")
    smoke.add_argument("--timeout", type=int, default=600)
    cmds.add_parser("doctor", help="Check local toolchain availability (without downloading SDK)")
    cmds.add_parser("index", help="Index editorial development guides into existing local RAG")
    return top


def run(args, store, embedder) -> dict:
    action = args.dev_action
    if action == "templates":
        return {"templates": templates(), "count": len(templates())}
    if action == "template":
        return get_template(args.id)
    if action == "guides":
        return {"guides": guides(), "count": len(guides())}
    if action == "guide":
        item = next((x for x in guides() if x["id"] == args.id), None)
        if not item:
            raise ValueError("Unknown development guide")
        return item
    if action == "scaffold":
        return scaffold(args.template, args.appid, args.output, name=args.name)
    if action == "doctor":
        binary = shutil.which("ufbt")
        return {"ufbt_installed": bool(binary), "ufbt_binary": binary,
                "sdk_state_expected": str(Path.home() / ".ufbt"),
                "source_catalog_valid": len(catalog()["templates"]) >= 3,
                "note": "SDK channel/version and actual compiler availability are verified only during a real build."}
    if action == "index":
        return index_documents(store, development_documents(), embedder)
    if action in ("validate", "build"):
        graph = FirmwareGraph(store.path) if args.firmware_ref else None
        if action == "validate":
            return validate_project(args.project, kind=args.kind, firmware_ref=args.firmware_ref, graph=graph)
        return build_fap(args.project, execute=args.execute, ufbt_binary=args.ufbt_path,
                         timeout=args.timeout, firmware_ref=args.firmware_ref, graph=graph)
    if action == "smoke":
        directory = args.output
        if not directory.is_dir() or any(directory.iterdir()) or directory.is_symlink():
            raise ValueError("Smoke-test output must exist, be empty and not be a symlink")
        results = []
        for template, app_id in (("furi-dialog", "rag_dialog"),
                                 ("furi-viewport", "rag_viewport"),
                                 ("furi-log", "rag_log")):
            project = directory / app_id
            created = scaffold(template, app_id, project)
            result = build_fap(project, execute=args.execute, ufbt_binary=args.ufbt_path,
                               timeout=args.timeout)
            results.append({"template": template, "project": created, "build": result})
        return {"status": "passed" if args.execute and all(r["build"]["status"] == "passed" for r in results)
                else "dry-run" if not args.execute else "failed", "results": results}
    raise ValueError("Unknown development command")
