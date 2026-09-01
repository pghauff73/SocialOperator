from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from socialoperator.browser.coordinate_map import WindowCalibration
from socialoperator.browser.models import InteractiveTarget
from socialoperator.browser.native_mouse import MouseSafetyController, MouseSafetyError
from socialoperator.browser.target_fusion import AmbiguousTargetError, select_target
from socialoperator.types import CoordinateSpace, Point, Rect


def _target(target_id: str, name: str, x: float) -> InteractiveTarget:
    return InteractiveTarget(
        target_id=target_id,
        role="button",
        accessible_name=name,
        text=name,
        href=None,
        enabled=True,
        visible=True,
        rect=Rect(x, 20, 100, 40, CoordinateSpace.VIEWPORT),
    )


def test_target_fusion_selects_unique_exact_name() -> None:
    candidate = select_target(
        "Open project details",
        (_target("one", "Open project details", 10), _target("two", "Close details", 200)),
        ocr_text="Open project details",
    )
    assert candidate.target.target_id == "one"
    assert "exact_accessible_name" in candidate.reasons


def test_target_fusion_rejects_duplicate_names() -> None:
    with pytest.raises(AmbiguousTargetError):
        select_target("Next", (_target("one", "Next", 10), _target("two", "Next", 200)))


def test_coordinate_calibration_maps_viewport_to_desktop() -> None:
    calibration = WindowCalibration.from_browser_metrics(
        screen_x=100,
        screen_y=50,
        outer_width=1200,
        outer_height=900,
        inner_width=1180,
        inner_height=820,
        device_scale_factor=1,
    )
    mapped = calibration.viewport_rect_to_desktop(Rect(20, 30, 100, 40, CoordinateSpace.VIEWPORT))
    assert mapped == Rect(130, 150, 100, 40, CoordinateSpace.DESKTOP)


@dataclass(slots=True)
class FakeMouse:
    current: Point = field(default_factory=lambda: Point(0, 0, CoordinateSpace.DESKTOP))
    clicked: bool = False
    scroll_amounts: list[int] = field(default_factory=list)

    def move_to(self, x: float, y: float, duration_seconds: float) -> None:
        self.current = Point(x, y, CoordinateSpace.DESKTOP)

    def position(self) -> Point:
        return self.current

    def click(self) -> None:
        self.clicked = True

    def scroll(self, amount: int) -> None:
        self.scroll_amounts.append(amount)


def test_mouse_safety_moves_and_clicks_inside_target() -> None:
    mouse = FakeMouse()
    controller = MouseSafetyController(mouse, foreground_check=lambda: True)
    target = Rect(100, 200, 80, 40, CoordinateSpace.DESKTOP)
    assert controller.click_target(target) == target.center
    assert mouse.clicked


def test_mouse_safety_blocks_wrong_foreground() -> None:
    controller = MouseSafetyController(FakeMouse(), foreground_check=lambda: False)
    with pytest.raises(MouseSafetyError, match="foreground"):
        controller.click_target(Rect(100, 200, 80, 40, CoordinateSpace.DESKTOP))


def test_mouse_safety_scrolls_with_foreground_guard() -> None:
    mouse = FakeMouse()
    controller = MouseSafetyController(mouse, foreground_check=lambda: True)
    assert controller.scroll_current(-4) == mouse.current
    assert mouse.scroll_amounts == [-4]


def test_mouse_safety_blocks_foreground_loss_during_scroll() -> None:
    checks = iter((True, False))
    controller = MouseSafetyController(FakeMouse(), foreground_check=checks.__next__)
    with pytest.raises(MouseSafetyError, match="foreground window changed during scroll"):
        controller.scroll_current(-4)
