from __future__ import annotations

import pytest
from PIL import Image

from socialoperator.browser.coordinate_map import CalibrationError, WindowCalibration
from socialoperator.types import CoordinateSpace, Rect


def test_metric_calibration_remains_available_for_headless_tests() -> None:
    calibration = WindowCalibration.from_browser_metrics(
        screen_x=20,
        screen_y=20,
        outer_width=1448,
        outer_height=1131,
        inner_width=1440,
        inner_height=1000,
        device_scale_factor=1,
    )
    mapped = calibration.viewport_rect_to_desktop(Rect(293, 171, 196, 50, CoordinateSpace.VIEWPORT))
    assert mapped.space is CoordinateSpace.DESKTOP
    assert calibration.method == "metrics"


def test_calibration_compatibility_detects_resize_and_scale_changes() -> None:
    initial = WindowCalibration.from_browser_metrics(
        screen_x=20,
        screen_y=20,
        outer_width=1448,
        outer_height=1131,
        inner_width=1440,
        inner_height=1000,
        device_scale_factor=1,
    )
    resized = WindowCalibration.from_browser_metrics(
        screen_x=20,
        screen_y=20,
        outer_width=1548,
        outer_height=1131,
        inner_width=1540,
        inner_height=1000,
        device_scale_factor=1,
    )
    scaled = WindowCalibration.from_browser_metrics(
        screen_x=20,
        screen_y=20,
        outer_width=1448,
        outer_height=1131,
        inner_width=1440,
        inner_height=1000,
        device_scale_factor=1.25,
    )
    with pytest.raises(CalibrationError, match="outer width"):
        initial.assert_compatible(resized)
    with pytest.raises(CalibrationError, match="device scale factor"):
        initial.assert_compatible(scaled)


def test_calibration_fixture_image_dimensions() -> None:
    image = Image.new("RGB", (1440, 1000), "white")
    assert image.size == (1440, 1000)
