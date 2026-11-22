"""Persistent optional USearch HNSW index over the SQLite embedding source of truth.

The ANN file is a disposable cache. An SQLite epoch, model name and dimension
must match its manifest. Any mutation invalidates it; callers fall back to the
filtered exact scan until explicitly rebuilt. No implicit downloads or writes.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from dataclasses import dataclass
from typing import Sequence
from .storage import Store


class ANNUnavailable(RuntimeError):
    pass


def _import_usearch():
    try:
        import numpy as np
        from usearch.index import Index
    except ImportError as exc:
        raise ANNUnavailable('ANN requires: pip install -e ".[ann]"') from exc
    return np, Index


def _key(chunk_id: str) -> int:
    return int.from_bytes(hashlib.blake2b(chunk_id.encode('utf-8'), digest_size=8,
                                      person=b'fzrag-ann').digest(), 'big')


@dataclass(frozen=True)
class ANNStatus:
    state: str
    count: int = 0
    model: str = ''
    dimension: int = 0
    reason: str = ''

    def as_dict(self) -> dict:
        return vars(self).copy()


class ANNIndex:
    def __init__(self, store: Store, index_path: Path | str | None = None):
        self.store = store
        self.path = Path(index_path) if index_path else store.path.with_suffix('.usearch')
        self.manifest_path = Path(str(self.path) + '.json')
        self._loaded = None
        self._loaded_key = None

    def _manifest(self) -> dict:
        try:
            return json.loads(self.manifest_path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return {}

    def status(self, model: str) -> ANNStatus:
        manifest = self._manifest()
        if not manifest or not self.path.is_file():
            return ANNStatus('missing', model=model, reason='run flipper-rag ann build')
        if manifest.get('schema') != 1 or manifest.get('model') != model:
            return ANNStatus('stale', model=model, reason='embedding model or format changed')
        if manifest.get('epoch') != self.store.vector_epoch():
            return ANNStatus('stale', model=model, reason='SQLite vectors changed; rebuild index')
        if not isinstance(manifest.get('dimension'), int) or manifest['dimension'] <= 0:
            return ANNStatus('invalid', model=model, reason='invalid dimension')
        return ANNStatus('ready', count=manifest.get('count', 0), model=model,
                         dimension=manifest['dimension'])

    def build(self, model: str) -> dict:
        np, Index = _import_usearch()
        start_epoch = self.store.vector_epoch()
        vectors: list[list[float]] = []
        ids: dict[int, str] = {}
        dimension = None
        skipped = 0
        for cid, vec in self.store.iter_embeddings(model):
            if (not isinstance(vec, list) or not vec or
                    any(not isinstance(v, (float, int)) or not math.isfinite(v) for v in vec)):
                skipped += 1
                continue
            if dimension is None:
                dimension = len(vec)
            if len(vec) != dimension or not any(v != 0 for v in vec):
                skipped += 1
                continue
            key = _key(cid)
            if key in ids and ids[key] != cid:
                raise ANNUnavailable('64-bit chunk-key collision; contact maintainers')
            ids[key] = cid
            vectors.append(vec)
        if not vectors:
            raise ANNUnavailable('No valid vectors for selected embedding model. Run reembed first.')
        index = Index(ndim=dimension, metric='cos', dtype='f32',
                      connectivity=16, expansion_add=128, expansion_search=96)
        keys = np.asarray(list(ids), dtype=np.uint64)
        index.add(keys, np.asarray(vectors, dtype=np.float32))
        if self.store.vector_epoch() != start_epoch:
            raise ANNUnavailable('SQLite embeddings changed during build; retry')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Unique files avoid interleaved writes. Publish metadata last. Readers
        # validate both epoch and file, so a partial build cannot be used.
        with tempfile.TemporaryDirectory(dir=self.path.parent, prefix='.ann-build-') as tmp:
            next_index = Path(tmp) / 'new.usearch'
            next_meta = Path(tmp) / 'new.json'
            index.save(str(next_index))
            next_meta.write_text(json.dumps({'schema': 1, 'model': model, 'epoch': start_epoch,
                'dimension': dimension, 'count': len(ids),
                'key_to_chunk': {str(k): cid for k, cid in ids.items()}},
                ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            if self.store.vector_epoch() != start_epoch:
                raise ANNUnavailable('SQLite embeddings changed during build; retry')
            os.replace(next_index, self.path)
            os.replace(next_meta, self.manifest_path)
        self._loaded = None
        self._loaded_key = None
        return {'model': model, 'dimensions': dimension, 'indexed': len(ids),
                'skipped_invalid': skipped, 'path': str(self.path), 'epoch': start_epoch}

    def search(self, vector: Sequence[float], model: str, limit: int = 160) -> list[tuple[str, float]]:
        np, Index = _import_usearch()
        status = self.status(model)
        if status.state != 'ready':
            raise ANNUnavailable(status.reason)
        if len(vector) != status.dimension or any(not math.isfinite(x) for x in vector):
            raise ANNUnavailable('Query embedding dimensions or values do not match ANN index')
        manifest = self._manifest()
        if len(manifest.get('key_to_chunk', {})) != status.count:
            raise ANNUnavailable('ANN key mapping is inconsistent; rebuild index')
        # Cache one per process, refreshing on epoch/model/file changes.
        load_key = (model, manifest['epoch'], self.path.stat().st_mtime_ns)
        if self._loaded_key != load_key:
            loaded = Index(ndim=status.dimension, metric='cos', dtype='f32')
            loaded.load(str(self.path))
            self._loaded, self._loaded_key = loaded, load_key
        matches = self._loaded.search(np.asarray(vector, dtype=np.float32),
                                      min(max(1, limit), status.count))
        ids = manifest['key_to_chunk']
        return [(ids[str(int(m.key))], max(0., 1. - float(m.distance)))
                for m in matches if str(int(m.key)) in ids]
