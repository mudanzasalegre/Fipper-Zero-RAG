"""v1.0 CLI integration. All network and indexing operations require a CLI command."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from .platform import Platform
from .platform_eval import BenchmarkIncomplete, evaluate_official, load_benchmark
from .sources import load_catalog


def add_parser(subparsers):
    p = subparsers.add_parser("platform", help="Unified v1.0 status, incremental sync and real-source evaluation")
    actions = p.add_subparsers(dest="action", required=True)
    status = actions.add_parser("status", help="Read-only source quality and platform status")
    status.add_argument("--stale-days", type=int, default=14)
    audit = actions.add_parser("audit", help="Check FTS integrity and source freshness")
    audit.add_argument("--stale-days", type=int, default=14)
    sync = actions.add_parser("sync", help="Incrementally index explicit official and local sources")
    sync.add_argument("--web", action="store_true", help="Curated official documentation with HTTP ETag/304 cache")
    sync.add_argument("--git", action="store_true", help="Configured official Git documentation")
    sync.add_argument("--local", action="store_true", help="Curated knowledge/ directories")
    sync.add_argument("--internal", action="store_true", help="Index protocol ontology and development summaries")
    sync.add_argument("--with-code", action="store_true", help="Explicitly opt into larger firmware code corpus")
    sync.add_argument("--catalog-file", type=Path, default=Path("sources.json"))
    sync.add_argument("--git-cache", type=Path, default=Path("data/upstream"))
    sync.add_argument("--max-pages", type=int, default=100)
    sync.add_argument("--delay", type=float, default=0.35)
    sync.add_argument("--force", action="store_true", help="Reindex even unchanged content")
    bench = actions.add_parser("evaluate", help="Grade retrieval on actually indexed official pages")
    bench.add_argument("--file", type=Path, default=Path("benchmarks/real_official_v1.json"))
    bench.add_argument("--fetch", action="store_true", help="Fetch official benchmark pages before evaluating")
    bench.add_argument("--delay", type=float, default=0.35)
    bench.add_argument("--top-k", type=int, default=6)
    bench.add_argument("--mode", choices=["lexical", "hybrid", "semantic"], default="lexical")
    bench.add_argument("--min-coverage", type=float, default=1.0)
    bench.add_argument("--min-recall", type=float, default=0.0)
    bench.add_argument("--json-output", type=Path)
    report = actions.add_parser("report", help="Write source status and evaluation summary")
    report.add_argument("--format", choices=["json", "markdown"], default="json")
    report.add_argument("--output", type=Path)
    return p


def _emit(payload: dict, path: Path | None = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)


def _md(platform: Platform) -> str:
    status = platform.status()
    lines = ["# Flipper Knowledge Platform — estado", "", f"Generado: {status['at']}", "",
             "## Índice", "",
             f"- Documentos: {status['index']['documents']}",
             f"- Fragmentos: {status['index']['chunks']}",
             f"- Cobertura embeddings: {status['index']['embedding_coverage']:.1%}", "",
             "## Sincronizaciones", "",
             "| Fuente | Estado | Documentos | Última revisión |", "|---|---|---:|---|"]
    for row in status["source_health"]:
        # Source ids are bounded by upstream validation, not user supplied HTML.
        lines.append(f"| {row['id']} | {row['state']} | {row['documents']} | {row['last_run'] or 'Sin datos'} |")
    ev = status["latest_evaluation"]
    lines.extend(["", "## Evaluación de fuentes oficiales", ""])
    if not ev:
        lines.append("No ejecutada: no hay métricas verificadas sobre páginas reales.")
    else:
        report = ev["report"]
        lines.append(f"Estado: **{report['status']}**; dataset SHA-256: `{report['dataset_sha256']}`")
        lines.append(f"Cobertura: {report['corpus']['indexed']}/{report['corpus']['configured']}")
        for key, value in (report.get('metrics') or {}).items():
            lines.append(f"- {key}: {value}")
    lines.append("\nLas métricas son de recuperación documental; no verifican la exactitud de respuestas generadas ni compatibilidad de hardware.\n")
    return "\n".join(lines)


def run(args: argparse.Namespace, store, embedder, retriever) -> dict:
    platform = Platform(store)
    if args.action == "status":
        return platform.status(stale_days=args.stale_days)
    if args.action == "audit":
        return platform.audit(stale_days=args.stale_days)
    if args.action == "sync":
        if not (args.web or args.git or args.local or args.internal):
            raise ValueError("Select --web, --git, --local or --internal; no implicit background download")
        catalog = load_catalog(args.catalog_file) if args.web or args.git else {}
        result: dict = {}
        if args.web:
            result["web"] = platform.sync_web(catalog["web"], embedder,
                             max_pages=args.max_pages, delay=args.delay, force=args.force)
        if args.git:
            result["git"] = platform.sync_git(catalog, embedder, args.git_cache,
                                                with_code=args.with_code, force=args.force)
        if args.local:
            base = Path("knowledge")
            roots = [(name, base/name) for name in ("starter","protocols","protocol_lab","platform")
                     if (base/name).is_dir()]
            result["local"] = platform.sync_local(roots, embedder, force=args.force)
        if args.internal:
            result["internal"] = platform.sync_internal(embedder, force=args.force)
        return result
    if args.action == "evaluate":
        benchmark = load_benchmark(args.file)
        if args.fetch:
            result = platform.sync_web([{"url": url, "category": "official-benchmark"}
                                        for url in benchmark["sources"]], embedder,
                                        max_pages=len(benchmark["sources"]), delay=args.delay)
            if result["failed"]:
                print(f"[WARN] {result['failed']} official benchmark pages failed to fetch")
        try:
            result = evaluate_official(platform, retriever, benchmark, top_k=args.top_k,
                                       mode=args.mode, min_coverage=args.min_coverage)
        except BenchmarkIncomplete as exc:
            failure = platform.reports("evaluation", 1)[0]["report"]
            if args.json_output:
                args.json_output.parent.mkdir(parents=True, exist_ok=True)
                args.json_output.write_text(json.dumps(failure, indent=2, ensure_ascii=False) + "\n")
            raise ValueError(str(exc)) from exc
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if result["metrics"]["recall_at_k"] < args.min_recall:
            raise ValueError(f"Recall below requested threshold {args.min_recall}")
        return result
    if args.action == "report":
        output = {"status": platform.status(), "audit": platform.audit()}
        if args.format == "markdown":
            text = _md(platform)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(text, encoding="utf-8")
            print(text)
            return {}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return output
    raise ValueError("Unknown platform command")
