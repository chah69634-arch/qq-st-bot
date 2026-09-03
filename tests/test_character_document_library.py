from core.character_document_library import (
    delete,
    observability,
    read,
    search,
    store_upload,
)


def test_character_document_library_is_scoped_and_bounded(sandbox):
    first = store_upload(
        uid="owner-a",
        char_id="char-a",
        filename="notes.txt",
        media_type="text/plain",
        sha256="a" * 64,
        searchable_text="alpha " * 5000,
        source="upload_file",
        raw_bytes=b"secret",
    )
    assert first == "doc_" + "a" * 24
    assert search("owner-a", "char-a", "alpha")[0]["document_id"] == first
    assert search("owner-a", "char-b", "alpha") == []
    assert search("owner-b", "char-a", "alpha") == []
    page = read("owner-a", "char-a", first)
    assert page is not None
    assert len(page["content"]) <= 2000
    assert page["next_offset"] == 2000
    assert read("owner-a", "char-b", first) is None
    stats = observability("owner-a", "char-a")
    assert stats["count"] == 1
    assert stats["retention"]["derived_only"] == 1
    assert "searchable_text" not in stats

    assert delete("owner-a", "char-a", first)
    assert search("owner-a", "char-a", "alpha") == []
    assert read("owner-a", "char-a", first) is None
    assert observability("owner-a", "char-a")["deleted"] == 1
