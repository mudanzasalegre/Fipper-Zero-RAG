"""CLI integration for the offline, read-only Protocol Lab v0.9."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .protocol_lab import (FORMATS, analyze_file, analyze_directory, compare_results,
                           render_report, render_batch_report, render_comparison, privacy_summary, MAX_BATCH)


def add_parser(sub) -> None:
    p = sub.add_parser("lab", help="Offline Flipper file diagnostics and redacted reports")
    subcmd = p.add_subparsers(dest="action", required=True)
    subcmd.add_parser("formats", help="List supported formats and official references")
    analyze = subcmd.add_parser("analyze", help="Read a single file without executing it")
    analyze.add_argument("--file", type=Path, required=True)
    analyze.add_argument("--type", choices=sorted(FORMATS), help="Override file extension (required for BadUSB .txt)")
    analyze.add_argument("--report", choices=("json", "markdown", "html"), default="json")
    analyze.add_argument("--output", type=Path, help="Save sanitized report (no secrets)")
    analyze.add_argument("--index-redacted", action="store_true", help="Explicitly index sanitized summary in local RAG")
    analyze.add_argument("--overwrite", action="store_true", help="Allow replacing existing report")
    batch = subcmd.add_parser("batch", help="Inspect supported files in a directory (bounded, no symlinks)")
    batch.add_argument("--directory", type=Path, required=True)
    batch.add_argument("--limit", type=int, default=MAX_BATCH)
    batch.add_argument("--report", choices=("json", "markdown", "html"), default="json")
    batch.add_argument("--output", type=Path, help="Write aggregate redacted report")
    batch.add_argument("--index-redacted", action="store_true")
    batch.add_argument("--overwrite", action="store_true")
    compare = subcmd.add_parser("compare", help="Compare two files structurally, never comparing payload bytes")
    compare.add_argument("--before", type=Path, required=True)
    compare.add_argument("--after", type=Path, required=True)
    compare.add_argument("--report", choices=("json", "markdown", "html"), default="json")
    compare.add_argument("--output", type=Path)
    compare.add_argument("--overwrite", action="store_true")


def _write_report(dest: Path, contents: str, input_paths: list[Path], overwrite: bool = False) -> None:
    dst = dest.expanduser().resolve()
    if any(dst == p.expanduser().resolve() for p in input_paths):
        raise ValueError("Report destination cannot overwrite any source file")
    if dst.exists() and not overwrite:
        raise ValueError("Report destination already exists; use --overwrite explicitly")
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Do not create executable permissions; never write raw input data.
    dst.write_text(contents, encoding="utf-8")


def _index_redacted(items: list[dict], store, embedder) -> dict:
    from .sources import index_documents
    from .storage import Document, document_id
    docs = []
    for item in items:
        if item.get("format") not in FORMATS or "finding_totals" not in item:
            continue
        safe = privacy_summary(item)
        tag = hashlib.sha256(safe.encode("utf-8")).hexdigest()[:20]
        docs.append(Document(doc_id=document_id("protocol-lab-redacted",tag),
                             source_id="protocol-lab-redacted", title=f"Protocol Lab / {item['format']} / diagnóstico local",
                             url=f"local://protocol-lab/{tag}", category="protocol-lab", body=safe,
                             revision="v0.9-redacted",trust="local",license="Generated diagnostic summary",
                             firmware_channel="unversioned"))
    return index_documents(store, iter(docs), embedder)


def run(args, store=None, embedder=None) -> int:
    if args.action == "formats":
        print(json.dumps({"formats": FORMATS,"offline":True,"execution":False}, ensure_ascii=False, indent=2))
        return 0
    try:
        if args.action == "analyze":
            result = analyze_file(args.file,file_format=args.type)
            if args.index_redacted:
                if store is None or embedder is None:
                    raise ValueError("Local store and embedding provider are required for --index-redacted")
                result["indexing"] = _index_redacted([result], store, embedder)
            content = render_report(result, output=args.report)
            if args.output:
                _write_report(args.output, content, [args.file], args.overwrite)
                print(json.dumps({"output":"saved", "status":result["status"],"redacted":True},ensure_ascii=False))
            else:
                print(content)
            return 2 if result["status"] == "invalid" else 0
        if args.action == "batch":
            results = analyze_directory(args.directory,limit=args.limit)
            if args.index_redacted:
                if store is None or embedder is None:
                    raise ValueError("Local store and embedding provider are required for --index-redacted")
                indexing = _index_redacted(results, store, embedder)
            else:
                indexing = None
            totals = {"valid":sum(r.get("status")=="valid" for r in results),
                      "warnings":sum(r.get("status")=="warnings" for r in results),
                      "invalid":sum(r.get("status")=="invalid" for r in results)}
            report = {"schema_version":1,"kind":"batch", "files_analyzed":len(results),
                      "totals":totals, "reports":results,"redacted":True,
                      "data_policy":"No paths, credentials, identifiers or payload values exported"}
            if indexing is not None:
                report["indexing"] = indexing
            body=render_batch_report(report,output=args.report)
            if args.output:
                _write_report(args.output,body,[],args.overwrite)
                print(json.dumps({"output":"saved","totals":totals},ensure_ascii=False))
            else:
                print(body)
            return 2 if totals["invalid"] else 0
        if args.action == "compare":
            first=analyze_file(args.before)
            second=analyze_file(args.after)
            result=compare_results(first,second)
            contents=render_comparison(result,output=args.report)
            if args.output:
                _write_report(args.output,contents,[args.before,args.after],args.overwrite)
                print('{"output":"saved","redacted":true}')
            else:
                print(contents)
            return 0
        raise ValueError("Unknown Protocol Lab action")
    except (ValueError,OSError) as exc:
        # Never print the raw file content, identifiers or absolute paths from errors.
        print(json.dumps({"error":"Protocol Lab could not complete the request.",
                          "reason":"invalid input, destination, or unsupported format"},ensure_ascii=False))
        return 2
