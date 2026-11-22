"""Optional local CrossEncoder reranking. Never download/load a model at startup."""
from __future__ import annotations
import math
import threading
from typing import Callable


class RerankerUnavailable(RuntimeError):
    pass


class LocalReranker:
    def __init__(self, provider: str = 'none', model: str = 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1',
                 batch_size: int = 8, scorer: Callable | None = None):
        if provider not in {'none', 'cross-encoder'}:
            raise ValueError('RAG_RERANK_PROVIDER must be none or cross-encoder')
        self.provider = provider
        self.model = model
        self.batch_size = max(1, min(batch_size, 32))
        self._scorer = scorer
        self._lock = threading.RLock()
        self._instance = None

    @property
    def active(self) -> bool:
        return self.provider != 'none'

    def score(self, query: str, candidates: list[dict]) -> list[float]:
        if not self.active:
            raise RerankerUnavailable('reranker disabled')
        if not candidates:
            return []
        pairs = [(query[:1200], (c['title'] + ' | ' + c['heading'] + '\n' + c['content'])[:1800])
                 for c in candidates]
        try:
            with self._lock:
                if self._scorer is not None:
                    values = self._scorer(pairs)
                else:
                    if self._instance is None:
                        from sentence_transformers import CrossEncoder
                        self._instance = CrossEncoder(self.model, trust_remote_code=False)
                    values = self._instance.predict(pairs, batch_size=self.batch_size,
                                                    show_progress_bar=False)
            scores = [float(x) for x in values]
            if len(scores) != len(pairs) or not all(math.isfinite(x) for x in scores):
                raise RerankerUnavailable('CrossEncoder returned invalid or mismatched scores')
            return scores
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise RerankerUnavailable(f'CrossEncoder unavailable: {exc}') from exc
