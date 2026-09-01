from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def identifiers(path: Path, pattern: str) -> set[str]:
    return set(re.findall(pattern, path.read_text(encoding="utf-8")))


def main() -> int:
    plan = identifiers(ROOT / "IMPLEMENTATION_PLAN.md", r"\b(?:FR|SP)-\d{2}\b")
    matrix = identifiers(ROOT / "docs" / "REQUIREMENT_EVIDENCE_MATRIX.md", r"\b(?:FR|SP)-\d{2}\b")
    missing = sorted(plan - matrix)
    extra = sorted(matrix - plan)
    print(
        {
            "plan_count": len(plan),
            "matrix_count": len(matrix),
            "missing": missing,
            "extra": extra,
            "ok": not missing and not extra,
        }
    )
    return 0 if not missing and not extra else 1


raise SystemExit(main())
