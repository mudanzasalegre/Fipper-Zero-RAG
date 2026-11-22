from flipper_rag.sources import TextHTMLParser, local_documents, _canonical_doc_link


def test_html_excludes_script_and_nav():
    parser = TextHTMLParser()
    parser.feed("<html><head><title>Demo</title></head><body><nav>Menu</nav><main><h1>GPIO</h1><p>LED pin 5</p></main><script>alert(1)</script></body></html>")
    assert "GPIO" in parser.text()
    assert "LED pin 5" in parser.text()
    assert "alert" not in parser.text()
    assert "Menu" not in parser.text()


def test_local_ingestion(tmp_path):
    (tmp_path / "guide.md").write_text("# Flipper\nPrueba de documentos", encoding="utf-8")
    (tmp_path / "secret.exe").write_bytes(b"ignore")
    docs = list(local_documents(tmp_path))
    assert len(docs) == 1
    assert docs[0].url.startswith("file://")


def test_link_discovery_limited_to_official_docs():
    base = "https://docs.flipper.net/zero/sub-ghz"
    assert _canonical_doc_link(base, "/zero/nfc?utm=test") == "https://docs.flipper.net/zero/nfc"
    assert _canonical_doc_link(base, "https://evil.com/malicious") is None
    assert _canonical_doc_link(base, "/zero/assets/pinout.pdf") is None
    parser = TextHTMLParser()
    parser.feed('<a href="/zero/nfc">NFC</a>')
    assert parser.links == ["/zero/nfc"]
