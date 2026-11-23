"""Ingest/update/query/evaluate via `flipper-rag` or `python -m flipper_rag.cli`."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .config import Settings
from .models import Embedder, ChatModel, ModelUnavailable
from .storage import Store
from .sources import load_catalog, index_documents, local_documents, web_documents, git_documents
from .retrieval import Retriever
from .protocol_intelligence import add_parser as add_ontology_parser, cli_result as ontology_cli_result
from .firmware_cli import add_parser as add_firmware_parser, run as run_firmware_cli
from .development_cli import add_parser as add_development_parser, run as run_development_cli
from .lab_cli import add_parser as add_lab_parser, run as run_lab_cli
from .service import RAGService
from .protocols import all_protocols, get_protocol, search_protocols, protocol_documents, SOURCE_ID


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="flipper-rag", description="Flipper Zero RAG local")
    sub = p.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="Index Markdown/text/code from a local directory")
    ingest.add_argument("--path", type=Path, default=Path("knowledge/starter"))
    ingest.add_argument("--source-id", default="notas-locales")
    ingest.add_argument("--force", action="store_true", help="Reindex unchanged files")
    ingest.add_argument("--firmware-version", help="Associate local documents with an explicit firmware release tag")
    ingest.add_argument("--pdf", action="store_true", help="Index text PDFs by page (pip install -e '.[pdf]')")
    ingest.add_argument("--prune", action="store_true", help="Remove no-longer-present local files after successful scan")

    sync = sub.add_parser("sync", help="Retrieve and index permitted official sources")
    sync.add_argument("--catalog-file", type=Path, default=Path("sources.json"))
    sync.add_argument("--web", action="store_true", help="Fetch curated official documentation pages")
    sync.add_argument("--protocols", action="store_true", help="Index locally curated, cited protocol descriptions")
    sync.add_argument("--firmware-ref", help="Index an official firmware release tag (e.g. 1.5.1), retaining other snapshots")
    sync.add_argument("--firmware", action="store_true", help="Clone/index official firmware docs")
    sync.add_argument("--apps", action="store_true", help="Clone/index official app catalog")
    sync.add_argument("--all", action="store_true", help="All official sources, excluding community")
    sync.add_argument("--tools", action="store_true", help="Official development tools: uFBT, RPC, qFlipper, FAP examples")
    sync.add_argument("--community", action="store_true", help="Opt-in community docs; explicitly nonofficial")
    sync.add_argument("--with-code", action="store_true", help="Index firmware C/header files (larger corpus)")
    sync.add_argument("--force", action="store_true")
    sync.add_argument("--prune", action="store_true", help="Remove absent Git documents only after full successful scan; never prunes web")
    sync.add_argument("--crawl", action="store_true", help="Follow official documentation links")
    sync.add_argument("--max-pages", type=int, default=250)
    sync.add_argument("--depth", type=int, default=2)
    sync.add_argument("--delay", type=float, default=0.6, help="Pause seconds between web fetches")

    proto = sub.add_parser("protocols", help="Explore, validate or index the 118 protocol entries")
    proto.add_argument("action", nargs="?", choices=("list", "validate", "index"), default="list")
    proto.add_argument("--family", help="Protocol family filter")
    proto.add_argument("--query", default="", help="Search IDs, names and aliases")
    proto.add_argument("--limit", type=int, default=200)
    sub.add_parser("stats", help="Index and embedding coverage")
    runs = sub.add_parser("runs", help="Recent sync results per source")
    runs.add_argument("--limit", type=int, default=30)
    audit = sub.add_parser("audit", help="Inspect source catalog and index integrity")
    audit.add_argument("--catalog-file", type=Path, default=Path("sources.json"))
    sources = sub.add_parser("sources", help="List and validate the allowlisted sources")
    sources.add_argument("--catalog-file", type=Path, default=Path("sources.json"))
    sub.add_parser("doctor", help="Check local prerequisites and configuration")
    reembed = sub.add_parser("reembed", help="Fill missing vectors with Ollama")
    reembed.add_argument("--batch", type=int, default=16)
    reembed.add_argument("--build-ann", action="store_true", help="Build optional ANN cache after embedding")
    ann = sub.add_parser("ann", help="Manage persistent USearch HNSW index")
    ann.add_argument("action", choices=("status", "build"))
    search = sub.add_parser("search", help="Hybrid lexical + semantic retrieval")
    search.add_argument("question", nargs="+")
    search.add_argument("--top-k", type=int, default=6)
    search.add_argument("--mode", choices=("hybrid", "lexical", "semantic"), default="hybrid")
    search.add_argument("--trust", choices=("official", "community", "local"))
    search.add_argument("--category")
    search.add_argument("--source-id")
    search.add_argument("--protocol", help="Exact protocol registry ID or known alias")
    search.add_argument("--no-expand", action="store_true")
    search.add_argument("--firmware-version", help="Filter by exact firmware release with optional unversioned sources")
    search.add_argument("--version-policy", choices=("strict", "include-unversioned"), default="include-unversioned")
    search.add_argument("--rerank", action="store_true", help="Enable configured local reranker")
    ask = sub.add_parser("ask", help="Grounded LLM question-answering")
    ask.add_argument("question", nargs="+")
    ask.add_argument("--top-k", type=int, default=6)
    ask.add_argument("--mode", choices=("hybrid", "lexical", "semantic"), default="hybrid")
    ask.add_argument("--trust", choices=("official", "community", "local"))
    ask.add_argument("--category")
    ask.add_argument("--source-id")
    ask.add_argument("--protocol", help="Exact protocol registry ID or known alias")
    ask.add_argument("--no-expand", action="store_true")
    ask.add_argument("--firmware-version")
    ask.add_argument("--version-policy", choices=("strict", "include-unversioned"), default="include-unversioned")
    ask.add_argument("--rerank", action="store_true")
    evaluate = sub.add_parser("eval", help="Recall@k on benchmark questions")
    evaluate.add_argument("--file", type=Path, default=Path("benchmarks/questions.jsonl"))
    evaluate.add_argument("--top-k", type=int, default=6)
    evaluate.add_argument("--mode", choices=("lexical", "hybrid", "semantic"), default="lexical")
    evaluate.add_argument("--firmware-version")
    evaluate.add_argument("--version-policy", choices=("strict", "include-unversioned"), default="include-unversioned")
    evaluate.add_argument("--rerank", action="store_true")
    evaluate.add_argument("--json-output", type=Path, help="Write complete machine-readable report")
    evaluate.add_argument("--min-recall", type=float, default=0.0,
                          help="Fail when recall is below threshold (0..1)")
    add_ontology_parser(sub)
    add_firmware_parser(sub)
    add_development_parser(sub)
    add_lab_parser(sub)
    args = p.parse_args(argv)
    settings = Settings()
    store = Store(settings.db_path)
    embedder = Embedder(settings)
    retriever = Retriever(store, embedder)

    if args.command == "lab":
        code = run_lab_cli(args, store, embedder)
        if code:
            raise SystemExit(code)
    elif args.command == "protocols":
        if args.action == "validate":
            print(json.dumps({"valid": True, "count": len(all_protocols())}, indent=2))
        elif args.action == "index":
            result = index_documents(store, protocol_documents(), embedder)
            store.record_sync(SOURCE_ID, result)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            try:
                found = search_protocols(family=args.family, query=args.query, limit=args.limit)
            except ValueError as exc:
                p.error(str(exc))
            print(json.dumps({"count": len(found), "protocols": found}, indent=2, ensure_ascii=False))
    elif args.command == "ingest":
        if not args.path.is_dir():
            p.error(f"Directory not found: {args.path}")
        seen: set[str] = set()
        result = index_documents(store, local_documents(args.path, source_id=args.source_id,
                                 include_pdf=args.pdf, firmware_version=args.firmware_version or ''),
                                 embedder, force=args.force, seen_ids=seen)
        removed = 0
        if args.prune and result["failed"] == 0 and seen:
            removed = store.prune_source(args.source_id, seen)
        result["removed"] = removed
        store.record_sync(args.source_id, result, removed=removed)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "sync":
        if not any((args.web, args.protocols, args.firmware, args.firmware_ref, args.apps, args.tools, args.community, args.all)):
            p.error("Select at least one: --web, --firmware, --apps, --tools, --community, --all")
        catalog = load_catalog(args.catalog_file)
        overall = []
        if args.protocols or args.all:
            result = index_documents(store, protocol_documents(), embedder, force=args.force)
            store.record_sync(SOURCE_ID, result)
            overall.append((SOURCE_ID, result))
        if args.web or args.all:
            web_report: dict = {}
            result = index_documents(store, web_documents(catalog, args.delay, crawl=args.crawl,
                                    max_pages=max(1, min(args.max_pages, 2000)),
                                    max_depth=max(0, min(args.depth, 5)), report=web_report),
                                    embedder, force=args.force)
            result.update(web_report)
            store.record_sync("web-oficial", result)
            overall.append(("web", result))
        names = ({"firmware-oficial"} if args.firmware or args.firmware_ref else set()) | ({"apps-catalogo-oficial"} if args.apps else set())
        tool_ids = {"ufbt-oficial", "protobuf-oficial", "qflipper-oficial", "good-faps-oficial"}
        if args.tools:
            names |= tool_ids
        if args.community:
            names |= {spec["id"] for spec in catalog["git"] if spec.get("tier") == "community"}
        if args.all:
            names |= {spec["id"] for spec in catalog["git"] if spec.get("tier", "official") == "official"}
        for spec in catalog["git"]:
            if spec["id"] not in names:
                continue
            if spec['id'] == 'firmware-oficial' and args.firmware_ref:
                from .versioning import firmware_source_for_ref
                try:
                    spec = firmware_source_for_ref(spec, args.firmware_ref)
                except ValueError as exc:
                    p.error(str(exc))
            try:
                docs = git_documents(spec, Path("data/git-cache"), include_code=args.with_code)
                seen: set[str] = set()
                result = index_documents(store, docs, embedder, force=args.force, seen_ids=seen)
                # A capped scan cannot safely delete prior documents.
                removed = 0
                if args.prune and result["failed"] == 0 and seen and len(seen) < min(int(spec.get("max_files", 1200)), 5000):
                    removed = store.prune_source(spec["id"], seen)
                elif args.prune:
                    result["prune_skipped"] = "empty, partial or capped scan"
                result["removed"] = removed
                store.record_sync(spec["id"], result, removed=removed)
                overall.append((spec["id"], result))
            except Exception as exc:
                print(f"[ERROR] Source {spec['id']} unavailable: {exc}")
                error = {"error": str(exc)}
                store.record_sync(spec["id"], error)
                overall.append((spec["id"], error))
        print(json.dumps(dict(overall), indent=2, ensure_ascii=False))
    elif args.command == "dev":
        try:
            result = run_development_cli(args, store, embedder)
        except ValueError as exc:
            p.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.dev_action in {"validate", "build", "smoke"} and (
                ("valid" in result and not result["valid"])
                or result.get("status") in {"invalid", "failed", "timeout", "no-artifact"}):
            raise SystemExit(1)
    elif args.command == "firmware":
        try:
            result = run_firmware_cli(args, store, embedder)
        except ValueError as exc:
            p.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "ontology":
        try:
            result = ontology_cli_result(args, store, embedder)
        except ValueError as exc:
            p.error(str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.action == "eval" and not result["passed"]:
            raise SystemExit(1)
    elif args.command == "stats":
        print(json.dumps(store.stats(), indent=2, ensure_ascii=False))
    elif args.command == "runs":
        print(json.dumps(store.source_runs(args.limit), indent=2, ensure_ascii=False))
    elif args.command == "audit":
        from .audit import audit_catalog, audit_store
        report = {"catalog": audit_catalog(args.catalog_file), "index": audit_store(store)}
        print(json.dumps(report, indent=2, ensure_ascii=False))
        raise SystemExit(0 if report["catalog"]["valid"] and report["index"]["valid"] else 1)
    elif args.command == "sources":
        catalog = load_catalog(args.catalog_file)
        print(json.dumps({"web_seeds": len(catalog["web"]), "git": [
            {"id": spec["id"], "url": spec["url"], "branch": spec["branch"],
             "tier": spec.get("tier", "official"), "category": spec.get("category")}
            for spec in catalog["git"]]}, indent=2, ensure_ascii=False))
    elif args.command == "doctor":
        import shutil
        import sqlite3
        report = {"python": __import__("sys").version.split()[0],
                  "git_available": bool(shutil.which("git")),
                  "sqlite_fts5": "FTS5" in " ".join(row[0] for row in sqlite3.connect(":memory:").execute("PRAGMA compile_options")),
                  "chat_provider": settings.chat_provider, "embedding_provider": settings.embed_provider,
                  "db_path": str(settings.db_path), "documents": store.stats()["documents"],
                  "ann": retriever.ann.status(settings.embed_model).as_dict() if retriever.ann else {"state": "disabled"},
                  "reranker": settings.rerank_provider}
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.command == "ann":
        from .ann import ANNIndex, ANNUnavailable
        index = ANNIndex(store, settings.ann_path)
        try:
            report = index.build(settings.embed_model) if args.action == 'build' else index.status(settings.embed_model).as_dict()
        except ANNUnavailable as exc:
            p.error(str(exc))
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.command == "reembed":
        if not embedder.active:
            p.error("Set RAG_EMBED_PROVIDER=ollama or openai for reembed")
        updated = 0
        batch = max(1, min(args.batch, 64))
        while True:
            missing = store.missing_embeddings(settings.embed_model, batch)
            if not missing:
                break
            ids, texts = zip(*missing)
            try:
                vectors = embedder.embed(list(texts))
            except ModelUnavailable as exc:
                p.error(str(exc))
            store.update_embeddings(ids, vectors, settings.embed_model)
            updated += len(ids)
            if updated % (batch * 10) == 0:
                print(f"Embeddings calculated: {updated}")
        print(f"OK: {updated} vectors created/updated")
        if args.build_ann:
            from .ann import ANNIndex, ANNUnavailable
            try:
                print(json.dumps(ANNIndex(store, settings.ann_path).build(settings.embed_model), indent=2))
            except ANNUnavailable as exc:
                p.error(str(exc))
    elif args.command == "search":
        data = retriever.search(" ".join(args.question), args.top_k, category=args.category,
                                mode=args.mode, trust=args.trust, source_id=args.source_id,
                                expand=not args.no_expand,
                                firmware_version=args.firmware_version, version_policy=args.version_policy,
                                rerank=args.rerank, protocol=args.protocol)
        for i, hit in enumerate(data["results"], 1):
            print(f"[{i}] {hit['title']} ({hit['category']})\n    {hit['url']}\n    {hit['content'][:350]}\n")
        print("Semantic backend:", data['semantic_backend'], "| Rerank:", data['reranker_status'])
    elif args.command == "ask":
        data = RAGService(retriever, ChatModel(settings), settings).ask(
            " ".join(args.question), category=args.category, top_k=args.top_k,
            mode=args.mode, trust=args.trust, source_id=args.source_id,
            expand=not args.no_expand, firmware_version=args.firmware_version,
            version_policy=args.version_policy, rerank=args.rerank, protocol=args.protocol)
        print(data["answer"])
        for s in data["sources"]:
            print(f"[{s['citation']}] {s['title']} — {s['url']}")
    elif args.command == "eval":
        from .evaluation import evaluate, load_cases
        if not args.file.exists():
            p.error(f"Benchmark file not found: {args.file}")
        report = evaluate(retriever, load_cases(args.file), top_k=args.top_k, mode=args.mode,
                          firmware_version=args.firmware_version,
                          version_policy=args.version_policy, rerank=args.rerank)
        for case in report["details"]:
            status = "PASS" if case["success"] else "MISS"
            print(f"{status}: {case['question']}" + (f" (rank {case['rank']})" if case["rank"] else ""))
        print(f"Recall@{args.top_k}: {report['recall_at_k']:.1%} | MRR: {report['mrr']:.3f}"
              + (f" | Abstention: {report['abstention_accuracy']:.1%}"
                 if report["abstention_accuracy"] is not None else "")
              + f" | Median {report['latency_ms']['median']} ms | Backends {report['semantic_backends']}")
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        raise SystemExit(0 if report["recall_at_k"] >= args.min_recall else 1)

if __name__ == "__main__":
    main()
