from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

import pytesseract
from PIL import Image, ImageDraw
from pytesseract import Output

from socialoperator.types import CoordinateSpace, Rect


@dataclass(frozen=True, slots=True)
class OcrToken:
    text: str
    confidence: float
    rect: Rect


@dataclass(frozen=True, slots=True)
class OcrResult:
    text: str
    tokens: tuple[OcrToken, ...]
    engine: str
    engine_version: str
    soft_miss: bool


class OcrEngine(Protocol):
    def recognize(self, image: Image.Image) -> OcrResult: ...


class TesseractOcrEngine:
    def __init__(self, *, language: str = "eng", page_segmentation_mode: int = 6) -> None:
        self.language = language
        self.page_segmentation_mode = page_segmentation_mode

    def recognize(self, image: Image.Image) -> OcrResult:
        data = pytesseract.image_to_data(
            image,
            lang=self.language,
            config=f"--psm {self.page_segmentation_mode}",
            output_type=Output.DICT,
        )
        tokens: list[OcrToken] = []
        for index, raw_text in enumerate(data["text"]):
            text = str(raw_text).strip()
            if not text:
                continue
            confidence = float(data["conf"][index])
            if confidence < 0:
                continue
            tokens.append(
                OcrToken(
                    text=text,
                    confidence=confidence,
                    rect=Rect(
                        x=float(data["left"][index]),
                        y=float(data["top"][index]),
                        width=max(float(data["width"][index]), 1.0),
                        height=max(float(data["height"][index]), 1.0),
                        space=CoordinateSpace.SCREENSHOT,
                    ),
                )
            )
        text = " ".join(token.text for token in tokens)
        return OcrResult(
            text=text,
            tokens=tuple(tokens),
            engine="tesseract",
            engine_version=str(pytesseract.get_tesseract_version()),
            soft_miss=not bool(tokens),
        )

    def recognize_png(self, data: bytes) -> OcrResult:
        with Image.open(BytesIO(data)) as image:
            return self.recognize(image.convert("RGB"))


def crop_around_point(image: Image.Image, *, x: int, y: int, size: int = 400) -> Image.Image:
    if size <= 0 or size % 2:
        raise ValueError("crop size must be a positive even integer")
    half = size // 2
    left = x - half
    top = y - half
    right = left + size
    bottom = top + size
    source_left = max(left, 0)
    source_top = max(top, 0)
    source_right = min(right, image.width)
    source_bottom = min(bottom, image.height)
    canvas = Image.new("RGB", (size, size), "white")
    if source_right > source_left and source_bottom > source_top:
        crop = image.crop((source_left, source_top, source_right, source_bottom)).convert("RGB")
        canvas.paste(crop, (source_left - left, source_top - top))
    return canvas


def redact_rectangles(image: Image.Image, rectangles: tuple[Rect, ...]) -> Image.Image:
    redacted = image.convert("RGB").copy()
    draw = ImageDraw.Draw(redacted)
    for rect in rectangles:
        if rect.space is not CoordinateSpace.SCREENSHOT:
            raise ValueError("redaction rectangles must use screenshot coordinates")
        draw.rectangle(
            (rect.x, rect.y, rect.x + rect.width, rect.y + rect.height),
            fill="black",
        )
    return redacted
