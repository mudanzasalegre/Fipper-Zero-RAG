"""Local hybrid retrieval with optional ANN, CrossEncoder and version-aware provenance.

SQLite remains the source of truth. A missing/stale ANN cache never silently
hides data: exact cosine is the deterministic fallback. Rerank is opt-in.
"""
from __future__ import annotations
import heapq
import math
from .ann import ANNIndex, ANNUnavailable
from .models import Embedder, ModelUnavailable
from .reranking import LocalReranker, RerankerUnavailable
from .storage import Store
from .terminology import expand_query
from .protocols import get_protocol
from .versioning import compatibility, normalize_version


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a or not b:
        return 0.0
    if not all(math.isfinite(x) for x in a + b):
        return 0.0
    aa, bb = sum(x * x for x in a), sum(y * y for y in b)
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(aa * bb) if aa and bb else 0.0


class Retriever:
    def __init__(self, store: Store, embedder: Embedder,
                 ann: ANNIndex | None = None, reranker: LocalReranker | None = None):
        self.store = store
        self.embedder = embedder
        settings = embedder.settings
        self.ann = ann if ann is not None else (ANNIndex(store, settings.ann_path) if settings.ann_enabled else None)
        self.reranker = reranker if reranker is not None else LocalReranker(settings.rerank_provider,
                                                settings.rerank_model, settings.rerank_batch_size)

    def _exact(self, query_embedding: list[float], filters: dict) -> list[str]:
        return [cid for score, cid in heapq.nlargest(160, (
            (cosine(query_embedding, vec), cid)
            for cid, vec in self.store.iter_embeddings(self.embedder.settings.embed_model, **filters)
        )) if score > 0.10]

    def _semantic(self, query_embedding: list[float], filters: dict, top_k: int) -> tuple[list[str], str, str]:
        if self.ann:
            try:
                results = self.ann.search(query_embedding, self.embedder.settings.embed_model,
                                          limit=max(160, top_k * 20))
                ids = [cid for cid, score in results if score > 0.10]
                if any(filters[key] for key in ("category", "trust", "source_id", "firmware_version")):
                    allowed = self.store.eligible_chunk_ids(ids, **filters)
                    ids = [cid for cid in ids if cid in allowed]
                    # Highly selective filters can starve ANN candidates; use an
                    # exact filtered scan instead of incorrect incomplete results.
                    if len(ids) < max(top_k * 2, 12):
                        return self._exact(query_embedding, filters), 'exact-filtered', 'ANN underfilled after filters'
                return ids[:160], 'ann', ''
            except (ANNUnavailable, OSError, ValueError, RuntimeError) as exc:
                return self._exact(query_embedding, filters), 'exact', str(exc)
        return self._exact(query_embedding, filters), 'exact', 'ANN disabled'

    def search(self, query: str, top_k: int = 6, category: str | None = None,
               mode: str = 'hybrid', trust: str | None = None, source_id: str | None = None,
               expand: bool = True, firmware_version: str | None = None,
               version_policy: str = 'include-unversioned', rerank: bool | None = None,
               protocol: str | None = None) -> dict:
        if mode not in {'hybrid', 'lexical', 'semantic'}:
            raise ValueError('mode must be hybrid, lexical or semantic')
        if trust not in {None, 'official', 'community', 'local'}:
            raise ValueError('invalid trust level')
        if version_policy not in {'strict', 'include-unversioned'}:
            raise ValueError('invalid version policy')
        chosen_protocol = get_protocol(protocol) if protocol else None
        if protocol and chosen_protocol is None:
            raise ValueError('Unknown or ambiguous protocol id; use flipper-rag protocols list')
        if firmware_version:
            firmware_version = normalize_version(firmware_version)
        if not query.strip():
            return {'results': [], 'semantic_available': False, 'retrieval_mode': mode,
                    'semantic_backend': 'not-used', 'reranker_status': 'not-used'}
        limit = max(1, min(top_k, 20))
        filters = {'category': category, 'trust': trust, 'source_id': source_id,
                   'firmware_version': firmware_version, 'version_policy': version_policy}
        lexical = self.store.lexical(query, 160, **filters) if mode != 'semantic' else []
        expanded = []
        if mode != 'semantic' and expand:
            extra = expand_query(query)
            if extra:
                expanded = self.store.lexical(extra, 80, **filters)
        protocol_hits = []
        if mode != 'semantic' and chosen_protocol:
            terms = chosen_protocol['name'] + ' ' + chosen_protocol['id'].replace('-', ' ')
            protocol_hits = self.store.lexical(terms, 80, **filters)
        semantic: list[str] = []
        semantic_backend, semantic_reason = 'not-used', ''
        if mode != 'lexical' and self.embedder.active:
            try:
                query_embedding = self.embedder.embed([query])[0]
                semantic, semantic_backend, semantic_reason = self._semantic(query_embedding, filters, limit)
            except ModelUnavailable as exc:
                semantic_backend, semantic_reason = 'unavailable', str(exc)
        ranks: dict[str, float] = {}
        signals: dict[str, list[str]] = {}
        for weight, label, seq in ((1.2, 'lexical', lexical), (0.45, 'terminology', expanded),
                                   (0.85, 'protocol', protocol_hits), (1.0, 'semantic', semantic)):
            for rank, cid in enumerate(seq, start=1):
                ranks[cid] = ranks.get(cid, 0.0) + weight / (60 + rank)
                signals.setdefault(cid, []).append(label)
        rows = self.store.get_chunks(list(ranks))
        for cid in list(ranks):
            if cid not in rows:
                del ranks[cid]
        if trust is None:
            for cid in ranks:
                if rows[cid]['trust'] == 'official':
                    ranks[cid] *= 1.025
        initial = sorted(ranks, key=lambda cid: (-ranks[cid], cid))
        shortlist = initial[:max(24, limit * 4)]
        rerank_scores: dict[str, float] = {}
        rerank_status = 'disabled'
        wants_rerank = self.reranker.active if rerank is None else bool(rerank and self.reranker.active)
        if wants_rerank and shortlist:
            try:
                values = self.reranker.score(query, [rows[cid] for cid in shortlist])
                rerank_scores = dict(zip(shortlist, values))
                shortlist.sort(key=lambda cid: (-rerank_scores[cid], -ranks[cid], cid))
                rerank_status = 'active'
            except RerankerUnavailable as exc:
                rerank_status = f'unavailable: {exc}'
        shortlisted = set(shortlist)
        ordered = shortlist + [cid for cid in initial if cid not in shortlisted]
        selected: list[dict] = []
        per_doc: dict[str, int] = {}
        for cid in ordered:
            doc_id = rows[cid]['doc_id']
            if per_doc.get(doc_id, 0) >= 2:
                continue
            per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
            item = dict(rows[cid], score=round(ranks[cid], 6),
                        retrieval_signals=signals[cid])
            if cid in rerank_scores:
                item['rerank_score'] = round(rerank_scores[cid], 6)
            if firmware_version:
                claim = compatibility(item.get('firmware_version', ''),
                                      item.get('firmware_channel', 'unversioned'), firmware_version)
                item['compatibility'] = claim.status
                item['compatibility_note'] = claim.note
            if item['url'].startswith('https://github.com/') and item['source_id'] != 'catalogo-protocolos' and '#' not in item['url']:
                item['url'] += f"#L{item['line_start']}-L{item['line_end']}"
            selected.append(item)
            if len(selected) >= limit:
                break
        return {'results': selected, 'semantic_available': bool(semantic),
                'retrieval_mode': mode, 'semantic_backend': semantic_backend,
                'semantic_reason': semantic_reason, 'reranker_status': rerank_status,
                'firmware_version': firmware_version, 'version_policy': version_policy,
                'terminology_expanded': bool(expanded),
                'protocol': chosen_protocol}
