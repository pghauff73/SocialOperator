from __future__ import annotations

import re


def normalize_search_text(value: str) -> str:
    """Normalize search text by lowercasing and extracting alphanumeric runs.

    Lowercases the input, keeps contiguous ASCII a-z and 0-9 runs,
    and joins those runs with one space.
    """
    lowered = value.lower()
    runs = re.findall(r"[a-z0-9]+", lowered)
    return " ".join(runs)
