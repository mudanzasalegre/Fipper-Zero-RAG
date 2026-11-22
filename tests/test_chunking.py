from flipper_rag.chunking import chunk_text

def test_chunks_preserve_line_ranges():
    data = "# Intro\n" + "\n".join(f"línea {i}: " + "dato "*15 for i in range(40))
    chunks = chunk_text(data, chunk_size=320, overlap=60)
    assert len(chunks) > 2
    assert chunks[0].line_start == 1
    assert all(1 <= c.line_start <= c.line_end <= 41 for c in chunks)
    assert "Intro" in chunks[0].heading

def test_empty_and_invalid():
    assert chunk_text("   \n") == []
    try:
        chunk_text("hola", chunk_size=10)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected validation error")
