from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from socialoperator.browser.observer import PageObserver
from socialoperator.browser.session import BrowserSession
from socialoperator.config import load_config, load_site_policy
from socialoperator.ocr.engine import TesseractOcrEngine, crop_around_point, redact_rectangles
from socialoperator.ocr.golden import evaluate_golden_corpus
from socialoperator.types import CoordinateSpace, Rect

ROOT = Path(__file__).resolve().parents[1]


def test_pointer_crop_is_exact_and_padded() -> None:
    image = Image.new("RGB", (100, 100), "blue")
    crop = crop_around_point(image, x=0, y=0, size=400)
    assert crop.size == (400, 400)
    assert crop.getpixel((200, 200)) == (0, 0, 255)
    assert crop.getpixel((0, 0)) == (255, 255, 255)


def test_redaction_requires_screenshot_coordinates() -> None:
    image = Image.new("RGB", (50, 50), "white")
    redacted = redact_rectangles(
        image,
        (Rect(10, 10, 20, 20, CoordinateSpace.SCREENSHOT),),
    )
    assert redacted.getpixel((15, 15)) == (0, 0, 0)


def test_tesseract_reads_fixture_screenshot(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    config = load_config(ROOT / "config" / "default.toml")
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    session = BrowserSession(
        config,
        policy,
        workspace=ROOT,
        profile_dir=tmp_path / "profile",
        headless=True,
    )
    try:
        session.start(fixture_server_url)
        session.resume_after_login()
        screenshot = PageObserver().screenshot(session)
    finally:
        session.stop()
    with Image.open(BytesIO(screenshot)) as image:
        result = TesseractOcrEngine().recognize(image.convert("RGB"))
    assert not result.soft_miss
    assert "SocialOperator" in result.text
    assert "Synthetic" in result.text


def test_ocr_golden_corpus_reports_required_term_recall() -> None:
    report = evaluate_golden_corpus(ROOT / "tests" / "fixtures" / "ocr" / "golden.json")

    assert report["passed"]
    assert report["case_count"] == 2
    assert report["failure_count"] == 0
