"""v0.3 acceptance tests: evidence quality, filtering, corpus lifecycle and local PDF."""
import json
from pathlib import Path
import sys
import types
from flipper_rag.storage import Document, Store
from flipper_rag.chunking import chunk_text
from flipper_rag.sources import TextHTMLParser, index_documents, local_documents, load_catalog
from flipper_rag.models import Embedder
from flipper_rag.config import Settings
from flipper_rag.retrieval import Retriever
from flipper_rag.terminology import expand_query
from flipper_rag.evaluation import evaluate, load_cases


class Offline(Embedder):
    @property
    def active(self):
        return False


def test_source_filter_runs_in_fts_before_limit(tmp_path):
    db = Store(tmp_path / 'filtered.sqlite')
    for n in range(170):
        doc = Document(f'doc{n}', 'community', f'Furi {n}', f'https://example.org/{n}',
                       'furi', 'Furi functions', trust='community')
        db.upsert(doc, chunk_text(doc.body))
    official = Document('official', 'official-src', 'Furi', 'https://docs.flipper.net/zero/development',
                        'furi', 'Furi functions', trust='official')
    db.upsert(official, chunk_text(official.body))
    r = Retriever(db, Offline(Settings()))
    hit = r.search('Furi functions', top_k=3, trust='official', source_id='official-src', mode='lexical')
    assert [x['title'] for x in hit['results']] == ['Furi']
    assert db.lexical('Furi functions', 2, trust='official') == ['official:0']
    assert db.lexical('Furi functions', 2, source_id='missing') == []


def test_semantic_source_filter(tmp_path):
    db = Store(tmp_path / 'v.sqlite')
    first = Document('f', 'official-src', 'Official', 'https://example.org/f', 'gpio', 'A GPIO reference', trust='official')
    second = Document('c', 'community-src', 'Community', 'https://example.org/c', 'gpio', 'A GPIO note', trust='community')
    db.upsert(first, chunk_text(first.body), [[1., 0.]], 'fixture')
    db.upsert(second, chunk_text(second.body), [[0., 1.]], 'fixture')
    assert [cid for cid, _ in db.iter_embeddings('fixture', trust='community')] == ['c:0']
    assert [cid for cid, _ in db.iter_embeddings('fixture', source_id='official-src')] == ['f:0']


def test_html_nested_void_tags_do_not_leak_boilerplate():
    parser = TextHTMLParser()
    parser.feed('''<header><input type="hidden"><script>steal()</script><h2>Secret navigation</h2></header>
        <main><h1>GPIO</h1><pre>int main(){\n  return 1;\n}</pre></main>
        <nav><br><a href="/zero/nfc">NFC</a><p>noise</p></nav><article>Firmware code</article>''')
    text = parser.text()
    assert 'GPIO' in text and 'int main()' in text and 'Firmware code' in text
    assert 'steal()' not in text and 'noise' not in text and 'Secret navigation' not in text
    assert '/zero/nfc' in parser.links


def test_no_unsupported_generic_fallback(tmp_path):
    db = Store(tmp_path / 'idx.db')
    doc = Document('d', 'starter', 'NFC', 'https://example.org/nfc', 'nfc', 'NFC supports smart cards.')
    db.upsert(doc, chunk_text(doc.body))
    retriever = Retriever(db, Offline(Settings()))
    assert not retriever.search('¿Qué implica la inteligencia de rinocerontes marcianos cristalinos?', mode='lexical')['results']
    assert retriever.search('¿Qué es NFC?', mode='lexical')['results']
    assert expand_query('¿Cómo usar una placa wifi?')
    assert not expand_query('¿Qué es NFC?')


def test_prune_is_explicit_and_logged(tmp_path):
    db = Store(tmp_path / 'index.sqlite')
    root = tmp_path / 'documents'
    root.mkdir()
    (root / 'a.md').write_text('GPIO module', encoding='utf-8')
    (root / 'b.md').write_text('Furi HAL', encoding='utf-8')
    seen = set()
    result = index_documents(db, local_documents(root, source_id='local-test'), Offline(Settings()), seen_ids=seen)
    assert result['documents_seen'] == 2
    assert db.stats()['documents'] == 2
    (root / 'b.md').unlink()
    seen.clear()
    index_documents(db, local_documents(root, source_id='local-test'), Offline(Settings()), seen_ids=seen)
    assert db.stats()['documents'] == 2  # explicit prune required
    removed = db.prune_source('local-test', seen)
    db.record_sync('local-test', result, removed=removed)
    assert removed == 1 and db.stats()['documents'] == 1
    assert db.source_runs(1)[0]['removed'] == 1
    db.record_sync('web-oficial', {'web_fetch_failed': 2, 'documents_seen': 10})
    assert db.source_runs(1)[0]['status'] == 'partial'


def test_opt_in_pdf_extraction_keeps_page_references(tmp_path, monkeypatch):
    pdf_path = tmp_path / 'lab.pdf'
    pdf_path.write_bytes(b'%PDF simulated with injectable reader')
    class FakePage:
        def extract_text(self, **kwargs):
            return 'Authorized GPIO and expansion hardware handbook, for laboratory research.'
    class FakeReader:
        def __init__(self, path, strict=False):
            self.is_encrypted = False
            self.pages = [FakePage(), FakePage()]
    monkeypatch.setitem(sys.modules, 'pypdf', types.SimpleNamespace(PdfReader=FakeReader))
    assert not list(local_documents(tmp_path))
    docs = list(local_documents(tmp_path, source_id='papers', include_pdf=True))
    assert len(docs) == 2
    assert docs[0].url.endswith('.pdf#page=1')
    assert docs[1].doc_id != docs[0].doc_id


def test_offline_benchmark_is_reproducible(tmp_path):
    base = Path(__file__).resolve().parents[1]
    db = Store(tmp_path / 'idx.sqlite')
    index_documents(db, local_documents(base / 'knowledge/starter', source_id='starter'), Offline(Settings()))
    report = evaluate(Retriever(db, Offline(Settings())), load_cases(base / 'benchmarks/offline.jsonl'), mode='lexical')
    assert report['positives'] >= 10
    assert report['recall_at_k'] >= 0.85
    assert report['abstention_accuracy'] == 1.0


def test_curated_documentation_seed_count():
    catalog = load_catalog(Path(__file__).resolve().parents[1] / 'sources.json')
    assert len(catalog['web']) >= 60
    assert any(s['url'].endswith('/js_gpio.html') for s in catalog['web'])
