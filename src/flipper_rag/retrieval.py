"""Hybrid retrieval: SQLite FTS5 (BM25) + Ollama embeddings, fused with RRF.

Query results include original URLs, source identity, revision, trust tier and
source-relative line numbers. The service never executes retrieved code.
"""
from __future__ import annotations
import math
import heapq
from .storage import Store
from .models import Embedder, ModelUnavailable


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a or not b:
        return 0.0
    aa = sum(x * x for x in a)
    bb = sum(y * y for y in b)
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(aa * bb) if aa and bb else 0.0


class Retriever:
    def __init__(self, store: Store, embedder: Embedder):
        self.store = store
        self.embedder = embedder

    def search(self, query: str, top_k: int = 6, category: str | None = None,
               mode: str = "hybrid", trust: str | None = None) -> dict:
        if mode not in {"hybrid", "lexical", "semantic"}:
            raise ValueError("mode must be hybrid, lexical or semantic")
        if trust not in {None, "official", "community", "local"}:
            raise ValueError("invalid trust level")
        if not query.strip():
            return {"results": [], "semantic_available": False, "retrieval_mode": mode}
        lexical = self.store.lexical(query, 160) if mode != "semantic" else []
        semantic: list[str] = []
        semantic_available = False
        if mode != "lexical" and self.embedder.active:
            try:
                query_embedding = self.embedder.embed([query])[0]
                # Exact similarity scan, streamed from SQLite with O(k) ranking memory.
                # For very large corpora, a dedicated ANN index is a future option.
                ranked = heapq.nlargest(
                    160,
                    ((cosine(query_embedding, vec), cid) for cid, vec in
                     self.store.iter_embeddings(self.embedder.settings.embed_model)),
                )
                semantic = [cid for score, cid in ranked if score > 0.10]
                semantic_available = bool(semantic)
            except ModelUnavailable:
                pass  # Explicit FTS5-only degradation when Ollama is offline.
        ranks: dict[str, float] = {}
        for weight, seq in ((1.2, lexical), (1.0, semantic)):
            for rank, cid in enumerate(seq, start=1):
                ranks[cid] = ranks.get(cid, 0.0) + weight / (60 + rank)
        rows = self.store.get_chunks(list(ranks))
        for cid in list(ranks):
            if cid not in rows or (category and rows[cid]["category"] != category) or \
                    (trust and rows[cid]["trust"] != trust):
                del ranks[cid]
        scored = sorted(ranks.items(), key=lambda item: item[1], reverse=True)
        selected: list[dict] = []
        per_doc: dict[str, int] = {}
        for cid, score in scored:
            doc_id = cid.split(":", 1)[0]
            if per_doc.get(doc_id, 0) >= 2:
                continue
            per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
            item = dict(rows[cid], score=round(score, 6))
            if item["url"].startswith("https://github.com/"):
                item["url"] += f"#L{item['line_start']}-L{item['line_end']}"
            selected.append(item)
            if len(selected) >= max(1, min(top_k, 20)):
                break
        return {"results": selected, "semantic_available": semantic_available,
                "retrieval_mode": mode}
