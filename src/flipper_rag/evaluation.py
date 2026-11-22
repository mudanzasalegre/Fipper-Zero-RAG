"""Reproducible document-retrieval evaluations; no generative model required."""
from __future__ import annotations
import json
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
        if "must_contain_url" not in case and "expected_urls_any" not in case and not case.get("should_abstain"):
            raise ValueError(f"Invalid benchmark case at line {n}: missing expectation")
        items.append(case)
    return items


def evaluate(retriever: Retriever, cases: Iterable[dict], *, top_k: int = 6,
             mode: str = "lexical") -> dict:
    positive = negatives = hits = negative_passes = 0
    reciprocal = 0.0
    details = []
    for case in cases:
        question = case["question"]
        found = retriever.search(question, top_k=top_k, mode=mode,
                                 trust=case.get("trust"), source_id=case.get("source_id"),
                                 category=case.get("category"))["results"]
        if case.get("should_abstain", False):
            negatives += 1
            success = not found
            negative_passes += int(success)
            position = None
        else:
            positive += 1
            urls = case.get("expected_urls_any") or [case["must_contain_url"]]
            if not isinstance(urls, list) or not urls:
                raise ValueError("expected_urls_any must be a non-empty list")
            position = next((i for i, hit in enumerate(found, 1)
                             if any(expected in hit["url"] for expected in urls)), None)
            success = position is not None
            hits += int(success)
            reciprocal += 1.0 / position if position else 0.0
        details.append({"question": question, "success": success, "rank": position,
                        "top_url": found[0]["url"] if found else None})
    return {
        "top_k": top_k, "mode": mode, "positives": positive, "negatives": negatives,
        "recall_at_k": hits / positive if positive else 0.0,
        "mrr": reciprocal / positive if positive else 0.0,
        "abstention_accuracy": negative_passes / negatives if negatives else None,
        "total": positive + negatives, "details": details,
    }
