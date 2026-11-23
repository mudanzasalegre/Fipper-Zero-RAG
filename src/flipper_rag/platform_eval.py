"""Inspectable relevance evaluation against actual indexed official source pages.

This evaluates *retrieval and citation metadata*, not LLM answer correctness.
The dataset deliberately contains no copied third-party document bodies.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from .platform import Platform, _canonical, _now


class BenchmarkIncomplete(ValueError):
    """Not enough actual official sources are indexed to claim an evaluation."""


def load_benchmark(path: Path) -> dict:
    raw = path.read_bytes()
    data = json.loads(raw)
    if data.get("schema_version") != 1 or not isinstance(data.get("sources"), list) or not isinstance(data.get("cases"), list):
        raise ValueError("Benchmark must have schema_version=1, sources and cases")
    if not data["sources"] or not data["cases"]:
        raise ValueError("Benchmark cannot be empty")
    sources = [_canonical(s) for s in data["sources"]]
    if len(set(sources)) != len(sources):
        raise ValueError("Duplicate benchmark URLs")
    known = set(sources)
    ids = set()
    positives = 0
    for case in data["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not isinstance(case.get("question"), str):
            raise ValueError("Malformed benchmark case")
        if case["id"] in ids or not 2 <= len(case["id"]) <= 80:
            raise ValueError("Duplicate/invalid case ID")
        if not 5 <= len(case["question"]) <= 300:
            raise ValueError("Question length out of range")
        ids.add(case["id"])
        relevance = case.get("relevance", {})
        if case.get("should_abstain"):
            if relevance:
                raise ValueError("Negative benchmark case cannot have relevant URLs")
        else:
            positives += 1
            if not isinstance(relevance, dict) or not relevance:
                raise ValueError("Positive benchmark case lacks relevance judgments")
            for url, grade in relevance.items():
                if url not in known or not isinstance(grade, int) or grade not in {1, 2, 3}:
                    raise ValueError("Relevance must point to listed URLs with grade 1..3")
    if not positives:
        raise ValueError("Benchmark needs at least one positive case")
    data["sha256"] = hashlib.sha256(raw).hexdigest()
    return data


def corpus_coverage(platform: Platform, benchmark: dict) -> dict:
    pages = benchmark["sources"]
    with platform.store.connect() as db:
        rows = db.execute("""SELECT url,content_sha,revision,firmware_version,indexed_at
                             FROM documents WHERE source_id='web-oficial' AND trust='official'""").fetchall()
    indexed = {row["url"]:dict(row) for row in rows}
    found = [{"url": url, "sha256": indexed[url]["content_sha"],
              "indexed_at": indexed[url]["indexed_at"]} for url in pages if url in indexed]
    missing = [url for url in pages if url not in indexed]
    return {"configured":len(pages), "indexed":len(found), "fraction":len(found)/len(pages),
            "missing":missing, "evidence":found}


def _dcg(grades: list[int]) -> float:
    return sum((2**grade-1)/math.log2(position+1)
               for position, grade in enumerate(grades,1))


def evaluate_official(platform: Platform, retriever, benchmark: dict, *, top_k: int = 6,
                      mode: str = "lexical", min_coverage: float = 1.0) -> dict:
    if not 1 <= top_k <= 20:
        raise ValueError("top_k must be 1..20")
    if not 0 <= min_coverage <= 1:
        raise ValueError("min_coverage must be within 0..1")
    if mode not in {"lexical", "hybrid", "semantic"}:
        raise ValueError("Unsupported retrieval mode")
    coverage = corpus_coverage(platform, benchmark)
    report = {"schema_version":1, "kind":"official-source-retrieval", "timestamp":_now(),
              "dataset_sha256":benchmark["sha256"], "retrieval_mode":mode, "top_k":top_k,
              "corpus":coverage, "scope":"retrieval-only; no factual answer grading"}
    if coverage["fraction"] < min_coverage or not coverage["indexed"]:
        report.update({"status":"incomplete", "metrics":None,
                       "reason":"Not enough verified official documentation pages indexed"})
        platform.save_report("evaluation", report)
        raise BenchmarkIncomplete(f"Official corpus coverage {coverage['indexed']}/{coverage['configured']}"
                                  f" is below the required {min_coverage:.0%}; sync official pages first")
    positives, negatives, success, neg_ok = 0, 0, 0, 0
    reciprocal, ndcg_total, precision_total, citation_hit, citation_count = 0.0, 0.0, 0.0, 0, 0
    timings = []
    details = []
    for case in benchmark["cases"]:
        start = time.perf_counter()
        response = retriever.search(case["question"], top_k=top_k, mode=mode,
                                    source_id="web-oficial", trust="official", expand=False)
        duration = round((time.perf_counter()-start)*1000,3)
        timings.append(duration)
        hits = response["results"]
        urls = [hit["url"] for hit in hits]
        for hit in hits:
            citation_count += 1
            if hit.get("source_id") == "web-oficial" and hit.get("trust") == "official" and \
               hit.get("url") in benchmark["sources"] and isinstance(hit.get("line_start"), int) and \
               isinstance(hit.get("line_end"), int) and hit["line_start"] <= hit["line_end"]:
                citation_hit += 1
        row = {"id":case["id"], "question":case["question"], "latency_ms":duration,
               "returned_urls":urls, "semantic_backend":response.get("semantic_backend", "not-used")}
        if case.get("should_abstain"):
            negatives += 1
            neg_ok += int(not hits)
            row.update({"kind":"negative", "success":not hits})
        else:
            positives += 1
            relevance = case["relevance"]
            rank = next((i for i,url in enumerate(urls,1) if relevance.get(url,0)>0), None)
            success += int(rank is not None)
            reciprocal += 1.0/rank if rank else 0.0
            gains = [relevance.get(url,0) for url in urls]
            ideal = _dcg(sorted(relevance.values(),reverse=True)[:top_k])
            ndcg = _dcg(gains)/ideal if ideal else 0.0
            ndcg_total += ndcg
            precision_total += sum(bool(grade) for grade in gains) / top_k
            row.update({"kind":"positive","success":rank is not None,"first_relevant_rank":rank,
                        "ndcg_at_k":round(ndcg,4)})
        details.append(row)
    report.update({"status":"complete", "metrics":{
        "positive_questions":positives, "negative_questions":negatives,
        "recall_at_k":round(success/positives,4) if positives else None,
        "mrr_at_k":round(reciprocal/positives,4) if positives else None,
        "ndcg_at_k":round(ndcg_total/positives,4) if positives else None,
        "precision_at_k":round(precision_total/positives,4) if positives else None,
        "abstention_accuracy":round(neg_ok/negatives,4) if negatives else None,
        "citation_metadata_coverage":round(citation_hit/citation_count,4) if citation_count else None,
        "median_latency_ms":round(statistics.median(timings),3) if timings else None,
        "p95_latency_ms":round(sorted(timings)[math.ceil(.95*len(timings))-1],3) if timings else None,
    }, "cases":details})
    platform.save_report("evaluation", report)
    return report
