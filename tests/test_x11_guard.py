from __future__ import annotations

import subprocess
from collections.abc import Sequence
from io import BytesIO

from PIL import Image

from socialoperator.browser.coordinate_map import WindowCalibration
from socialoperator.browser.window_masks import (
    OperatorWindowMask,
    SensitiveWindowPolicy,
    X11WindowSnapshot,
    discover_operator_window_masks,
    discover_sensitive_x11_windows,
    operator_masks_for_viewport,
    redact_operator_windows_from_png,
)
from socialoperator.browser.x11 import X11ActiveWindowGuard
from socialoperator.types import CoordinateSpace, Rect


class FakeWindowEnumerator:
    def __init__(self, snapshots: tuple[X11WindowSnapshot, ...]) -> None:
        self._snapshots = snapshots

    def snapshots(self) -> tuple[X11WindowSnapshot, ...]:
        return self._snapshots


def test_x11_guard_requires_matching_title_and_browser_class() -> None:
    responses = {
        ("xprop", "-root", "_NET_ACTIVE_WINDOW"): subprocess.CompletedProcess(
            (), 0, "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3e00007\n", ""
        ),
        (
            "xprop",
            "-id",
            "0x3e00007",
            "_NET_WM_NAME",
            "WM_NAME",
            "WM_CLASS",
        ): subprocess.CompletedProcess(
            (),
            0,
            '_NET_WM_NAME(UTF8_STRING) = "SocialOperator Fixture"\n'
            'WM_CLASS(STRING) = "google-chrome", "Google-chrome"\n',
            "",
        ),
    }

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return responses[tuple(command)]

    guard = X11ActiveWindowGuard(expected_title=lambda: "SocialOperator Fixture", runner=runner)
    assert guard()


def test_x11_guard_fails_closed_without_active_window() -> None:
    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        del command
        return subprocess.CompletedProcess((), 0, "_NET_ACTIVE_WINDOW:  not found.\n", "")

    guard = X11ActiveWindowGuard(expected_title=lambda: "SocialOperator Fixture", runner=runner)
    assert not guard()


def test_operator_window_masks_include_owned_windows_and_exclude_browser_titles() -> None:
    snapshots = (
        X11WindowSnapshot(
            window_id="0x1",
            title="SocialOperator Review",
            wm_class=("socialoperator", "SocialOperator"),
            rect=Rect(10, 20, 300, 200, CoordinateSpace.DESKTOP),
        ),
        X11WindowSnapshot(
            window_id="0x2",
            title="SocialOperator Fixture - Chromium",
            wm_class=("chromium", "Chromium"),
            rect=Rect(40, 40, 800, 600, CoordinateSpace.DESKTOP),
        ),
        X11WindowSnapshot(
            window_id="0x3",
            title="Hidden SocialOperator Review",
            wm_class=("socialoperator", "SocialOperator"),
            rect=Rect(0, 0, 200, 200, CoordinateSpace.DESKTOP),
            mapped=False,
        ),
    )

    masks = discover_operator_window_masks(enumerator=FakeWindowEnumerator(snapshots))

    assert [mask.window_id for mask in masks] == ["0x1"]


def test_operator_window_masks_clip_to_viewport_screenshot_coordinates() -> None:
    mask = OperatorWindowMask(
        window_id="0x1",
        title="SocialOperator Control",
        wm_class=("socialoperator",),
        rect=Rect(90, 40, 40, 40, CoordinateSpace.DESKTOP),
    )
    calibration = WindowCalibration(
        viewport_origin_desktop_x=100,
        viewport_origin_desktop_y=50,
    )

    redactions = operator_masks_for_viewport(
        (mask,),
        calibration=calibration,
        viewport_width=80,
        viewport_height=70,
    )

    assert redactions == (Rect(0, 0, 30, 30, CoordinateSpace.SCREENSHOT),)


def test_redact_operator_windows_from_png_blacks_overlapping_rectangles() -> None:
    source = Image.new("RGB", (100, 100), "white")
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    mask = OperatorWindowMask(
        window_id="0x1",
        title="SocialOperator Control",
        wm_class=("socialoperator",),
        rect=Rect(20, 30, 10, 10, CoordinateSpace.DESKTOP),
    )
    calibration = WindowCalibration(
        viewport_origin_desktop_x=10,
        viewport_origin_desktop_y=20,
    )

    redacted, rectangles = redact_operator_windows_from_png(
        buffer.getvalue(),
        calibration=calibration,
        masks=(mask,),
    )

    assert rectangles == (Rect(10, 10, 10, 10, CoordinateSpace.SCREENSHOT),)
    with Image.open(BytesIO(redacted)) as image:
        assert image.getpixel((15, 15)) == (0, 0, 0)
        assert image.getpixel((5, 5)) == (255, 255, 255)


def test_sensitive_x11_window_detection_matches_browser_chrome_privacy_titles() -> None:
    snapshots = (
        X11WindowSnapshot(
            window_id="0x1",
            title="Use your passkey",
            wm_class=("chromium", "Chromium"),
            rect=Rect(10, 20, 300, 200, CoordinateSpace.DESKTOP),
        ),
        X11WindowSnapshot(
            window_id="0x2",
            title="Ordinary Page",
            wm_class=("chromium", "Chromium"),
            rect=Rect(40, 40, 800, 600, CoordinateSpace.DESKTOP),
        ),
    )

    matches = discover_sensitive_x11_windows(enumerator=FakeWindowEnumerator(snapshots))

    assert [(match.window_id, match.matched_phrase) for match in matches] == [("0x1", "passkey")]


def test_sensitive_x11_window_detection_can_include_class_markers() -> None:
    snapshots = (
        X11WindowSnapshot(
            window_id="0x1",
            title="Credential request",
            wm_class=("pinentry-webauthn",),
            rect=Rect(10, 20, 300, 200, CoordinateSpace.DESKTOP),
        ),
    )

    matches = discover_sensitive_x11_windows(
        enumerator=FakeWindowEnumerator(snapshots),
        policy=SensitiveWindowPolicy(class_markers=("pinentry-webauthn",)),
    )

    assert matches[0].matched_phrase == "pinentry-webauthn"
