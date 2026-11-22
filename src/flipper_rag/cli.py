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
from .service import RAGService


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="flipper-rag", description="Flipper Zero RAG local")
    sub = p.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="Index Markdown/text/code from a local directory")
    ingest.add_argument("--path", type=Path, default=Path("knowledge/starter"))
    ingest.add_argument("--source-id", default="notas-locales")
    ingest.add_argument("--force", action="store_true", help="Reindex unchanged files")

    sync = sub.add_parser("sync", help="Retrieve and index permitted official sources")
    sync.add_argument("--catalog-file", type=Path, default=Path("sources.json"))
    sync.add_argument("--web", action="store_true", help="Fetch curated official documentation pages")
    sync.add_argument("--firmware", action="store_true", help="Clone/index official firmware docs")
    sync.add_argument("--apps", action="store_true", help="Clone/index official app catalog")
    sync.add_argument("--all", action="store_true", help="All official sources, excluding community")
    sync.add_argument("--tools", action="store_true", help="Official development tools: uFBT, RPC, qFlipper, FAP examples")
    sync.add_argument("--community", action="store_true", help="Opt-in community docs; explicitly nonofficial")
    sync.add_argument("--with-code", action="store_true", help="Index firmware C/header files (larger corpus)")
    sync.add_argument("--force", action="store_true")
    sync.add_argument("--crawl", action="store_true", help="Follow official documentation links")
    sync.add_argument("--max-pages", type=int, default=250)
    sync.add_argument("--depth", type=int, default=2)
    sync.add_argument("--delay", type=float, default=0.6, help="Pause seconds between web fetches")

    sub.add_parser("stats", help="Index and embedding coverage")
    audit = sub.add_parser("audit", help="Inspect source catalog and index integrity")
    audit.add_argument("--catalog-file", type=Path, default=Path("sources.json"))
    sources = sub.add_parser("sources", help="List and validate the allowlisted sources")
    sources.add_argument("--catalog-file", type=Path, default=Path("sources.json"))
    sub.add_parser("doctor", help="Check local prerequisites and configuration")
    reembed = sub.add_parser("reembed", help="Fill missing vectors with Ollama")
    reembed.add_argument("--batch", type=int, default=16)
    search = sub.add_parser("search", help="Hybrid lexical + semantic retrieval")
    search.add_argument("question", nargs="+")
    search.add_argument("--top-k", type=int, default=6)
    search.add_argument("--mode", choices=("hybrid", "lexical", "semantic"), default="hybrid")
    search.add_argument("--trust", choices=("official", "community", "local"))
    ask = sub.add_parser("ask", help="Grounded LLM question-answering")
    ask.add_argument("question", nargs="+")
    ask.add_argument("--top-k", type=int, default=6)
    ask.add_argument("--mode", choices=("hybrid", "lexical", "semantic"), default="hybrid")
    ask.add_argument("--trust", choices=("official", "community", "local"))
    evaluate = sub.add_parser("eval", help="Recall@k on benchmark questions")
    evaluate.add_argument("--file", type=Path, default=Path("benchmarks/questions.jsonl"))
    evaluate.add_argument("--top-k", type=int, default=6)
    evaluate.add_argument("--min-recall", type=float, default=0.0,
                          help="Fail when recall is below threshold (0..1)")
    args = p.parse_args(argv)
    settings = Settings()
    store = Store(settings.db_path)
    embedder = Embedder(settings)
    retriever = Retriever(store, embedder)

    if args.command == "ingest":
        if not args.path.is_dir():
            p.error(f"Directory not found: {args.path}")
        result = index_documents(store, local_documents(args.path, source_id=args.source_id), embedder,
                                 force=args.force)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "sync":
        if not any((args.web, args.firmware, args.apps, args.tools, args.community, args.all)):
            p.error("Select at least one: --web, --firmware, --apps, --tools, --community, --all")
        catalog = load_catalog(args.catalog_file)
        overall = []
        if args.web or args.all:
            overall.append(("web", index_documents(store, web_documents(catalog, args.delay, crawl=args.crawl,
                                     max_pages=max(1,min(args.max_pages,2000)), max_depth=max(0,min(args.depth,5))), embedder,
                                                    force=args.force)))
        names = ({"firmware-oficial"} if args.firmware else set()) | ({"apps-catalogo-oficial"} if args.apps else set())
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
            try:
                docs = git_documents(spec, Path("data/git-cache"), include_code=args.with_code)
                result = index_documents(store, docs, embedder, force=args.force)
                overall.append((spec["id"], result))
            except Exception as exc:
                print(f"[ERROR] Source {spec['id']} unavailable: {exc}")
                overall.append((spec["id"], {"error": str(exc)}))
        print(json.dumps(dict(overall), indent=2, ensure_ascii=False))
    elif args.command == "stats":
        print(json.dumps(store.stats(), indent=2, ensure_ascii=False))
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
                  "db_path": str(settings.db_path), "documents": store.stats()["documents"]}
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
    elif args.command == "search":
        data = retriever.search(" ".join(args.question), args.top_k, mode=args.mode, trust=args.trust)
        for i, hit in enumerate(data["results"], 1):
            print(f"[{i}] {hit['title']} ({hit['category']})\n    {hit['url']}\n    {hit['content'][:350]}\n")
        print("Semantic retrieval:", data["semantic_available"])
    elif args.command == "ask":
        data = RAGService(retriever, ChatModel(settings), settings).ask(" ".join(args.question), top_k=args.top_k, mode=args.mode, trust=args.trust)
        print(data["answer"])
        for s in data["sources"]:
            print(f"[{s['citation']}] {s['title']} — {s['url']}")
    elif args.command == "eval":
        if not args.file.exists():
            p.error(f"Benchmark file not found: {args.file}")
        cases = [json.loads(line) for line in args.file.read_text(encoding="utf-8").splitlines() if line.strip()]
        scores = []
        reciprocal = []
        for case in cases:
            found = retriever.search(case["question"], args.top_k)["results"]
            expected = case["must_contain_url"]
            hit = next((i for i, row in enumerate(found, 1) if expected in row["url"]), None)
            scores.append(bool(hit))
            reciprocal.append(1.0 / hit if hit else 0.0)
            print(f"{'PASS' if hit else 'MISS'}: {case['question']}" + (f" (rank {hit})" if hit else ""))
        rate = sum(scores) / len(scores) if scores else 0
        mrr = sum(reciprocal) / len(reciprocal) if reciprocal else 0
        print(f"Recall@{args.top_k}: {rate:.1%} ({sum(scores)}/{len(scores)}) | MRR: {mrr:.3f}")
        raise SystemExit(0 if rate >= args.min_recall else 1)

if __name__ == "__main__":
    main()
