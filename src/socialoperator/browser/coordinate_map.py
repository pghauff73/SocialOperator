from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from math import ceil, floor
from typing import Any, cast

from mss import MSS
from PIL import Image

from socialoperator.types import CoordinateSpace, Point, Rect


class CalibrationError(RuntimeError):
    """Raised when the browser viewport cannot be mapped to the desktop reliably."""


@dataclass(frozen=True, slots=True)
class WindowCalibration:
    viewport_origin_desktop_x: float
    viewport_origin_desktop_y: float
    device_scale_factor: float = 1.0
    method: str = "metrics"
    mean_absolute_error: float | None = None
    screen_x: float | None = None
    screen_y: float | None = None
    outer_width: float | None = None
    outer_height: float | None = None
    inner_width: float | None = None
    inner_height: float | None = None

    def __post_init__(self) -> None:
        if self.device_scale_factor <= 0:
            raise ValueError("device_scale_factor must be positive")

    def viewport_point_to_desktop(self, point: Point) -> Point:
        if point.space is not CoordinateSpace.VIEWPORT:
            raise ValueError("expected viewport point")
        return Point(
            x=self.viewport_origin_desktop_x + point.x,
            y=self.viewport_origin_desktop_y + point.y,
            space=CoordinateSpace.DESKTOP,
        )

    def viewport_rect_to_desktop(self, rect: Rect) -> Rect:
        if rect.space is not CoordinateSpace.VIEWPORT:
            raise ValueError("expected viewport rectangle")
        return Rect(
            x=self.viewport_origin_desktop_x + rect.x,
            y=self.viewport_origin_desktop_y + rect.y,
            width=rect.width,
            height=rect.height,
            space=CoordinateSpace.DESKTOP,
        )

    def assert_compatible(
        self,
        current: WindowCalibration,
        *,
        position_tolerance: float = 1.0,
        size_tolerance: float = 1.0,
        scale_tolerance: float = 0.01,
    ) -> None:
        comparisons = (
            (
                "viewport origin x",
                self.viewport_origin_desktop_x,
                current.viewport_origin_desktop_x,
                position_tolerance,
            ),
            (
                "viewport origin y",
                self.viewport_origin_desktop_y,
                current.viewport_origin_desktop_y,
                position_tolerance,
            ),
            ("screen x", self.screen_x, current.screen_x, position_tolerance),
            ("screen y", self.screen_y, current.screen_y, position_tolerance),
            ("outer width", self.outer_width, current.outer_width, size_tolerance),
            ("outer height", self.outer_height, current.outer_height, size_tolerance),
            ("inner width", self.inner_width, current.inner_width, size_tolerance),
            ("inner height", self.inner_height, current.inner_height, size_tolerance),
            (
                "device scale factor",
                self.device_scale_factor,
                current.device_scale_factor,
                scale_tolerance,
            ),
        )
        for label, previous, observed, tolerance in comparisons:
            if previous is None or observed is None:
                continue
            if abs(previous - observed) > tolerance:
                raise CalibrationError(
                    f"browser geometry changed during action: {label} "
                    f"was {previous:.3f}, now {observed:.3f}"
                )

    @classmethod
    def from_browser_metrics(
        cls,
        *,
        screen_x: float,
        screen_y: float,
        outer_width: float,
        outer_height: float,
        inner_width: float,
        inner_height: float,
        device_scale_factor: float,
    ) -> WindowCalibration:
        horizontal_border = max((outer_width - inner_width) / 2, 0)
        top_chrome = max(outer_height - inner_height - horizontal_border, 0)
        return cls(
            viewport_origin_desktop_x=screen_x + horizontal_border,
            viewport_origin_desktop_y=screen_y + top_chrome,
            device_scale_factor=device_scale_factor,
            screen_x=screen_x,
            screen_y=screen_y,
            outer_width=outer_width,
            outer_height=outer_height,
            inner_width=inner_width,
            inner_height=inner_height,
        )


def visual_window_calibration(
    *,
    page_png: bytes,
    screen_x: float,
    screen_y: float,
    outer_width: float,
    outer_height: float,
    inner_width: float,
    inner_height: float,
    device_scale_factor: float,
    maximum_mean_absolute_error: float = 20.0,
) -> WindowCalibration:
    with Image.open(BytesIO(page_png)) as source:
        page_image = source.convert("RGB")
    expected_size = (round(inner_width), round(inner_height))
    if page_image.size != expected_size:
        raise CalibrationError(
            f"page screenshot size {page_image.size} does not match viewport {expected_size}"
        )
    with MSS() as capture:
        monitor = capture.monitors[0]
        frame = capture.grab(monitor)
        desktop_image = Image.frombytes("RGB", frame.size, frame.rgb)
        desktop_left = int(monitor["left"])
        desktop_top = int(monitor["top"])

    x_start = floor(screen_x)
    x_end = ceil(screen_x + max(outer_width - inner_width, 0))
    y_start = floor(screen_y)
    y_end = ceil(screen_y + max(outer_height - inner_height, 0))
    page_pixels = cast(Any, page_image.load())
    desktop_pixels = cast(Any, desktop_image.load())
    sample_step_x = max(page_image.width // 36, 1)
    sample_step_y = max(page_image.height // 30, 1)
    sample_points = tuple(
        (x, y)
        for y in range(0, page_image.height, sample_step_y)
        for x in range(0, page_image.width, sample_step_x)
    )
    best_origin: tuple[int, int] | None = None
    best_error = float("inf")
    for origin_y in range(y_start, y_end + 1):
        desktop_y = origin_y - desktop_top
        if desktop_y < 0 or desktop_y + page_image.height > desktop_image.height:
            continue
        for origin_x in range(x_start, x_end + 1):
            desktop_x = origin_x - desktop_left
            if desktop_x < 0 or desktop_x + page_image.width > desktop_image.width:
                continue
            error = 0
            for sample_x, sample_y in sample_points:
                page_rgb = page_pixels[sample_x, sample_y]
                desktop_rgb = desktop_pixels[desktop_x + sample_x, desktop_y + sample_y]
                error += sum(abs(page_rgb[index] - desktop_rgb[index]) for index in range(3))
            mean_error = error / (len(sample_points) * 3)
            if mean_error < best_error:
                best_error = mean_error
                best_origin = (origin_x, origin_y)
    if best_origin is None or best_error > maximum_mean_absolute_error:
        raise CalibrationError(
            f"visual viewport calibration failed: best mean absolute error {best_error:.2f}"
        )
    return WindowCalibration(
        viewport_origin_desktop_x=float(best_origin[0]),
        viewport_origin_desktop_y=float(best_origin[1]),
        device_scale_factor=device_scale_factor,
        method="visual_screenshot_match",
        mean_absolute_error=best_error,
        screen_x=screen_x,
        screen_y=screen_y,
        outer_width=outer_width,
        outer_height=outer_height,
        inner_width=inner_width,
        inner_height=inner_height,
    )
