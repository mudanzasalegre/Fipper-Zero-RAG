"""Reproducible document-retrieval evaluations; no generative model required."""
from __future__ import annotations
import json
import time
import statistics
from pathlib import Path
from typing import Iterable
from .retrieval import Retriever


def load_cases(path: Path) -> list[dict]:
    items = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        if not isinstance(case, dict) or not isinstance(case.get("question"), str):
            raise ValueError(f"Invalid benchmark case at line {n}: missing question")
        if not any(k in case for k in ("must_contain_url", "expected_urls_any", "must_contain_title")) and not case.get("should_abstain"):
            raise ValueError(f"Invalid benchmark case at line {n}: missing expectation")
        items.append(case)
    return items


def evaluate(retriever: Retriever, cases: Iterable[dict], *, top_k: int = 6,
             mode: str = "lexical", firmware_version: str | None = None,
             version_policy: str = 'include-unversioned', rerank: bool = False) -> dict:
    positive = negatives = hits = negative_passes = 0
    reciprocal = 0.0
    details = []
    timings = []
    backends = {}
    for case in cases:
        question = case["question"]
        start = time.perf_counter()
        response = retriever.search(question, top_k=top_k, mode=mode,
                                    trust=case.get("trust"), source_id=case.get("source_id"),
                                    category=case.get("category"),
                                    firmware_version=case.get('firmware_version', firmware_version),
                                    version_policy=version_policy, rerank=rerank)
        duration = (time.perf_counter() - start) * 1000
        timings.append(duration)
        backend = response.get('semantic_backend', 'not-used')
        backends[backend] = backends.get(backend, 0) + 1
        found = response['results']
        if case.get("should_abstain", False):
            negatives += 1
            success = not found
            negative_passes += int(success)
            position = None
        else:
            positive += 1
            urls = case.get("expected_urls_any") or ([case["must_contain_url"]] if "must_contain_url" in case else [])
            if not isinstance(urls, list):
                raise ValueError("expected_urls_any must be a list")
            title = case.get("must_contain_title", "")
            if not urls and not title:
                raise ValueError("Benchmark needs a URL or a title expectation")
            position = next((i for i, hit in enumerate(found, 1)
                             if (not urls or any(expected in hit["url"] for expected in urls))
                             and (not title or title.casefold() in hit["title"].casefold())), None)
            success = position is not None
            hits += int(success)
            reciprocal += 1.0 / position if position else 0.0
        details.append({"question": question, "success": success, "rank": position,
                        "latency_ms": round(duration, 3), "semantic_backend": backend,
                        "top_url": found[0]["url"] if found else None})
    return {
        "top_k": top_k, "mode": mode, "firmware_version": firmware_version,
        "version_policy": version_policy, "rerank": rerank,
        "latency_ms": {'mean': round(statistics.mean(timings), 2) if timings else 0,
                       'median': round(statistics.median(timings), 2) if timings else 0,
                       'max': round(max(timings), 2) if timings else 0},
        "semantic_backends": backends,
        "positives": positive, "negatives": negatives,
        "recall_at_k": hits / positive if positive else 0.0,
        "mrr": reciprocal / positive if positive else 0.0,
        "abstention_accuracy": negative_passes / negatives if negatives else None,
        "total": positive + negatives, "details": details,
    }
