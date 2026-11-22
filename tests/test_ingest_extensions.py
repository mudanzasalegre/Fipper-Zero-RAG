from flipper_rag.sources import local_documents, TextHTMLParser


def test_local_protobuf_and_fam(tmp_path):
    (tmp_path/"application.fam").write_text('App(appid="demo", apptype=FlipperAppType.EXTERNAL)')
    (tmp_path/"rpc.proto").write_text('syntax = "proto3";')
    (tmp_path/"example.js").write_text('print("hi")')
    d = list(local_documents(tmp_path))
    assert len(d) == 3
    assert {doc.title for doc in d} == {"application.fam", "rpc.proto", "example.js"}


def test_html_skips_nested_tags():
    p = TextHTMLParser()
    p.feed('<main><nav><div>bad <span>bad</span></div></nav><p>good</p></main>')
    assert 'bad' not in p.text()
    assert 'good' in p.text()
