from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from socialoperator.ocr.engine import OcrEngine, TesseractOcrEngine


@dataclass(frozen=True, slots=True)
class OcrGoldenCase:
    case_id: str
    expected_terms: tuple[str, ...]
    minimum_term_recall: float = 1.0
    minimum_mean_confidence: float = 0.0
    image_path: Path | None = None
    render_text: str | None = None


def evaluate_golden_corpus(
    corpus_path: str | Path,
    *,
    engine: OcrEngine | None = None,
) -> dict[str, Any]:
    cases = load_golden_corpus(corpus_path)
    effective_engine = engine or TesseractOcrEngine()
    case_results = []
    for case in cases:
        image = _case_image(case)
        result = effective_engine.recognize(image)
        observed_terms = set(_normalized_terms(result.text))
        expected_terms = tuple(_normalized_phrase(term) for term in case.expected_terms)
        matched_terms = tuple(term for term in expected_terms if term in observed_terms)
        mean_confidence = (
            sum(token.confidence for token in result.tokens) / len(result.tokens)
            if result.tokens
            else 0.0
        )
        term_recall = len(matched_terms) / len(expected_terms) if expected_terms else 1.0
        passed = (
            not result.soft_miss
            and term_recall >= case.minimum_term_recall
            and mean_confidence >= case.minimum_mean_confidence
        )
        case_results.append(
            {
                "case_id": case.case_id,
                "passed": passed,
                "expected_terms": expected_terms,
                "matched_terms": matched_terms,
                "missing_terms": tuple(
                    term for term in expected_terms if term not in matched_terms
                ),
                "term_recall": term_recall,
                "minimum_term_recall": case.minimum_term_recall,
                "mean_confidence": mean_confidence,
                "minimum_mean_confidence": case.minimum_mean_confidence,
                "soft_miss": result.soft_miss,
                "engine": result.engine,
                "engine_version": result.engine_version,
                "recognized_text": result.text,
                "token_count": len(result.tokens),
            }
        )
    failures = tuple(case["case_id"] for case in case_results if not case["passed"])
    return {
        "schema": "socialoperator.ocr_golden_report.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus_path": str(Path(corpus_path).expanduser().resolve()),
        "case_count": len(case_results),
        "passed": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "cases": case_results,
    }


def write_golden_report(
    corpus_path: str | Path,
    output_path: str | Path,
    *,
    engine: OcrEngine | None = None,
) -> Path:
    report = evaluate_golden_corpus(corpus_path, engine=engine)
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def load_golden_corpus(corpus_path: str | Path) -> tuple[OcrGoldenCase, ...]:
    path = Path(corpus_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("OCR golden corpus must contain at least one case")
    cases: list[OcrGoldenCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("OCR golden corpus cases must be objects")
        cases.append(_load_case(path.parent, raw_case))
    return tuple(cases)


def _load_case(root: Path, raw_case: dict[str, Any]) -> OcrGoldenCase:
    case_id = str(raw_case["case_id"]).strip()
    if not case_id:
        raise ValueError("OCR golden case_id cannot be empty")
    raw_terms = raw_case.get("expected_terms")
    if not isinstance(raw_terms, list) or not raw_terms:
        raise ValueError(f"OCR golden case {case_id} must define expected_terms")
    image_path = raw_case.get("image_path")
    render_text = raw_case.get("render_text")
    if bool(image_path) == bool(render_text):
        raise ValueError(f"OCR golden case {case_id} must define exactly one image source")
    return OcrGoldenCase(
        case_id=case_id,
        expected_terms=tuple(str(term) for term in raw_terms),
        minimum_term_recall=float(raw_case.get("minimum_term_recall", 1.0)),
        minimum_mean_confidence=float(raw_case.get("minimum_mean_confidence", 0.0)),
        image_path=(root / str(image_path)).resolve() if image_path else None,
        render_text=str(render_text) if render_text else None,
    )


def _case_image(case: OcrGoldenCase) -> Image.Image:
    if case.image_path is not None:
        with Image.open(case.image_path) as image:
            return image.convert("RGB")
    assert case.render_text is not None
    lines = tuple(line for line in case.render_text.splitlines() if line.strip())
    font = _load_font()
    width = 1200
    line_height = 56
    height = max(line_height * len(lines) + 48, 120)
    rendered = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(rendered)
    for index, line in enumerate(lines):
        draw.text((24, 24 + index * line_height), line, fill="black", font=font)
    return rendered


def _load_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", 42)
    except OSError:
        return ImageFont.load_default()


def _normalized_terms(text: str) -> tuple[str, ...]:
    return tuple(
        term
        for term in (_normalized_phrase(match.group(0)) for match in re.finditer(r"\w+", text))
        if term
    )


def _normalized_phrase(text: str) -> str:
    return re.sub(r"[^\w]+", "", text.casefold())
