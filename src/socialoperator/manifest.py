from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXCLUDED_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "data",
    "dist",
    "reports",
}


def build_source_manifest(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).expanduser().resolve()
    entries: list[dict[str, object]] = []
    for path in sorted(root_path.rglob("*")):
        relative = path.relative_to(root_path)
        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        if not path.is_file():
            continue
        data = path.read_bytes()
        entries.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    entries_json = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "root": ".",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "entry_count": len(entries),
        "entries_sha256": hashlib.sha256(entries_json).hexdigest(),
        "entries": entries,
    }


def write_source_manifest(root: str | Path, output: str | Path) -> Path:
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_source_manifest(root), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
