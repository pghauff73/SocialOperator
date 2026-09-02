from __future__ import annotations

from socialoperator.text import normalize_search_text


def test_normalize_search_text() -> None:
    assert normalize_search_text("  Open_Project-42!  ") == "open project 42"
    assert normalize_search_text("a  b   c") == "a b c"
    assert normalize_search_text("!!!") == ""
