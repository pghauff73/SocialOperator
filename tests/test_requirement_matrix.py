import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_requirement_matrix_covers_every_plan_requirement() -> None:
    pattern = r"\b(?:FR|SP)-\d{2}\b"
    plan = set(re.findall(pattern, (ROOT / "IMPLEMENTATION_PLAN.md").read_text()))
    matrix = set(
        re.findall(pattern, (ROOT / "docs" / "REQUIREMENT_EVIDENCE_MATRIX.md").read_text())
    )
    assert len(plan) == 39
    assert matrix == plan
