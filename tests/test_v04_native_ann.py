"""Real USearch integration. Skips locally without optional [ann], runs in CI."""
from pathlib import Path
import pytest
from flipper_rag.ann import ANNIndex
from flipper_rag.storage import Store, Document
from flipper_rag.chunking import chunk_text


def test_native_usearch_persist_search_and_invalidate(tmp_path):
    pytest.importorskip('usearch.index')
    db = Store(tmp_path / 'index.sqlite3')
    for id, vec in [('nfc', [1., 0., 0.]), ('gpio', [0., 1., 0.]), ('ir', [0., 0., 1.])]:
        doc = Document(id, 'official', id, 'https://example.org/'+id, id,
                       id+' device documentation', trust='official')
        db.upsert(doc, chunk_text(doc.body), [vec], 'native-test')
    cache = ANNIndex(db)
    report = cache.build('native-test')
    assert report['indexed'] == 3
    assert cache.status('native-test').state == 'ready'
    assert cache.search([1., 0., 0.], 'native-test', 2)[0][0] == 'nfc:0'
    assert ANNIndex(db).search([0., 1., 0.], 'native-test', 2)[0][0] == 'gpio:0'
    db.update_embeddings(['nfc:0'], [[0., 0.5, 0.5]], 'native-test')
    assert cache.status('native-test').state == 'stale'
