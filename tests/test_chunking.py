from graphkit.compiler import chunk_text_spans


def test_text_chunks_preserve_exact_source_spans_and_overlap() -> None:
    text = "First paragraph with evidence.\n\nSecond paragraph with more evidence."

    chunks = chunk_text_spans(text, target_size=40, overlap=8)

    assert len(chunks) == 2
    assert all(text[start:end] == chunk for chunk, start, end in chunks)
    assert chunks[1][1] < chunks[0][2]
