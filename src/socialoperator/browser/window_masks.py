from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module
from io import BytesIO
from typing import Any, Protocol, cast

from PIL import Image

from socialoperator.browser.coordinate_map import WindowCalibration
from socialoperator.ocr.engine import redact_rectangles
from socialoperator.types import CoordinateSpace, Rect


class WindowMaskDiscoveryError(RuntimeError):
    """Raised when operator window discovery cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class X11WindowSnapshot:
    window_id: str
    title: str
    wm_class: tuple[str, ...]
    rect: Rect
    mapped: bool = True


@dataclass(frozen=True, slots=True)
class OperatorWindowMask:
    window_id: str
    title: str
    wm_class: tuple[str, ...]
    rect: Rect


@dataclass(frozen=True, slots=True)
class SensitiveWindow:
    window_id: str
    title: str
    wm_class: tuple[str, ...]
    matched_phrase: str


@dataclass(frozen=True, slots=True)
class OperatorWindowMaskPolicy:
    class_markers: tuple[str, ...] = ("socialoperator",)
    title_markers: tuple[str, ...] = (
        "socialoperator control",
        "socialoperator review",
        "socialoperator private",
    )
    excluded_class_markers: tuple[str, ...] = (
        "google-chrome",
        "chromium",
        "chrome",
        "firefox",
        "brave-browser",
    )
    include_unmapped: bool = False


@dataclass(frozen=True, slots=True)
class SensitiveWindowPolicy:
    title_markers: tuple[str, ...] = (
        "passkey",
        "security key",
        "webauthn",
        "captcha",
        "verification code",
        "one-time code",
        "one time code",
        "two-factor",
        "multi-factor",
        "authentication required",
    )
    class_markers: tuple[str, ...] = ()
    include_unmapped: bool = False


class WindowEnumerator(Protocol):
    def snapshots(self) -> tuple[X11WindowSnapshot, ...]: ...


class XlibWindowEnumerator:
    """Enumerate X11 client windows through python3-Xlib."""

    def __init__(self, display_name: str | None = None) -> None:
        self.display_name = display_name

    def snapshots(self) -> tuple[X11WindowSnapshot, ...]:
        try:
            display_module = import_module("Xlib.display")
            x_module = import_module("Xlib.X")
        except ImportError as error:
            raise WindowMaskDiscoveryError("python3-Xlib is unavailable") from error
        display: Any | None = None
        try:
            display = display_module.Display(self.display_name)
            root = display.screen().root
            window_ids = self._client_window_ids(display, root)
            return tuple(
                snapshot
                for window_id in window_ids
                if (snapshot := self._snapshot_window(display, root, int(window_id), x_module))
                is not None
            )
        except Exception as error:
            raise WindowMaskDiscoveryError(f"unable to enumerate X11 windows: {error}") from error
        finally:
            if display is not None:
                display.close()

    @staticmethod
    def _client_window_ids(display: Any, root: Any) -> tuple[int, ...]:
        x_module = import_module("Xlib.X")
        for atom_name in ("_NET_CLIENT_LIST_STACKING", "_NET_CLIENT_LIST"):
            atom = display.intern_atom(atom_name, only_if_exists=True)
            if atom == 0:
                continue
            value = root.get_full_property(atom, x_module.AnyPropertyType)
            if value is not None:
                return tuple(int(window_id) for window_id in cast(Iterable[Any], value.value))
        children = root.query_tree().children
        return tuple(int(child.id) for child in children)

    @classmethod
    def _snapshot_window(
        cls,
        display: Any,
        root: Any,
        window_id: int,
        x_module: Any,
    ) -> X11WindowSnapshot | None:
        window = display.create_resource_object("window", window_id)
        try:
            attributes = window.get_attributes()
            geometry = window.get_geometry()
            translated = window.translate_coords(root, 0, 0)
        except Exception:
            return None
        mapped = int(attributes.map_state) == int(x_module.IsViewable)
        x = float(translated.x)
        y = float(translated.y)
        width = float(geometry.width)
        height = float(geometry.height)
        left_extent, right_extent, top_extent, bottom_extent = cls._frame_extents(display, window)
        rect = Rect(
            x=x - left_extent,
            y=y - top_extent,
            width=width + left_extent + right_extent,
            height=height + top_extent + bottom_extent,
            space=CoordinateSpace.DESKTOP,
        )
        return X11WindowSnapshot(
            window_id=f"0x{window_id:x}",
            title=cls._window_title(display, window),
            wm_class=cls._wm_class(display, window),
            rect=rect,
            mapped=mapped,
        )

    @staticmethod
    def _window_title(display: Any, window: Any) -> str:
        utf8_atom = display.intern_atom("UTF8_STRING", only_if_exists=True)
        for atom_name, property_type in (("_NET_WM_NAME", utf8_atom), ("WM_NAME", 0)):
            atom = display.intern_atom(atom_name, only_if_exists=True)
            if atom == 0:
                continue
            value = window.get_full_property(atom, property_type or 0)
            if value is None:
                continue
            text = _decode_x_property(value.value)
            if text:
                return text
        return ""

    @staticmethod
    def _wm_class(display: Any, window: Any) -> tuple[str, ...]:
        atom = display.intern_atom("WM_CLASS", only_if_exists=True)
        if atom == 0:
            return ()
        value = window.get_full_property(atom, 0)
        if value is None:
            return ()
        text = _decode_x_property(value.value)
        return tuple(part for part in text.split("\x00") if part)

    @staticmethod
    def _frame_extents(display: Any, window: Any) -> tuple[float, float, float, float]:
        atom = display.intern_atom("_NET_FRAME_EXTENTS", only_if_exists=True)
        if atom == 0:
            return (0.0, 0.0, 0.0, 0.0)
        value = window.get_full_property(atom, 0)
        if value is None or len(value.value) < 4:
            return (0.0, 0.0, 0.0, 0.0)
        left, right, top, bottom = tuple(float(entry) for entry in value.value[:4])
        return left, right, top, bottom


def discover_operator_window_masks(
    *,
    enumerator: WindowEnumerator | None = None,
    policy: OperatorWindowMaskPolicy | None = None,
) -> tuple[OperatorWindowMask, ...]:
    source = enumerator or XlibWindowEnumerator()
    effective_policy = policy or OperatorWindowMaskPolicy()
    return tuple(
        OperatorWindowMask(
            window_id=snapshot.window_id,
            title=snapshot.title,
            wm_class=snapshot.wm_class,
            rect=snapshot.rect,
        )
        for snapshot in source.snapshots()
        if _is_operator_window(snapshot, effective_policy)
    )


def discover_sensitive_x11_windows(
    *,
    enumerator: WindowEnumerator | None = None,
    policy: SensitiveWindowPolicy | None = None,
) -> tuple[SensitiveWindow, ...]:
    source = enumerator or XlibWindowEnumerator()
    effective_policy = policy or SensitiveWindowPolicy()
    matches: list[SensitiveWindow] = []
    for snapshot in source.snapshots():
        matched_phrase = _sensitive_window_match(snapshot, effective_policy)
        if matched_phrase is None:
            continue
        matches.append(
            SensitiveWindow(
                window_id=snapshot.window_id,
                title=snapshot.title,
                wm_class=snapshot.wm_class,
                matched_phrase=matched_phrase,
            )
        )
    return tuple(matches)


def operator_masks_for_viewport(
    masks: tuple[OperatorWindowMask, ...],
    *,
    calibration: WindowCalibration,
    viewport_width: int,
    viewport_height: int,
) -> tuple[Rect, ...]:
    viewport_rect = Rect(
        x=calibration.viewport_origin_desktop_x,
        y=calibration.viewport_origin_desktop_y,
        width=float(viewport_width),
        height=float(viewport_height),
        space=CoordinateSpace.DESKTOP,
    )
    redactions: list[Rect] = []
    for mask in masks:
        overlap = _intersect(mask.rect, viewport_rect)
        if overlap is None:
            continue
        redactions.append(
            Rect(
                x=overlap.x - viewport_rect.x,
                y=overlap.y - viewport_rect.y,
                width=overlap.width,
                height=overlap.height,
                space=CoordinateSpace.SCREENSHOT,
            )
        )
    return tuple(redactions)


def redact_operator_windows_from_png(
    data: bytes,
    *,
    calibration: WindowCalibration,
    masks: tuple[OperatorWindowMask, ...],
) -> tuple[bytes, tuple[Rect, ...]]:
    with Image.open(BytesIO(data)) as image:
        source = image.convert("RGB")
    redactions = operator_masks_for_viewport(
        masks,
        calibration=calibration,
        viewport_width=source.width,
        viewport_height=source.height,
    )
    if not redactions:
        return data, ()
    output = BytesIO()
    redact_rectangles(source, redactions).save(output, format="PNG")
    return output.getvalue(), redactions


def _is_operator_window(
    snapshot: X11WindowSnapshot,
    policy: OperatorWindowMaskPolicy,
) -> bool:
    if not snapshot.mapped and not policy.include_unmapped:
        return False
    class_text = " ".join(snapshot.wm_class).casefold()
    title = snapshot.title.casefold()
    excluded_browser = any(
        marker.casefold() in class_text for marker in policy.excluded_class_markers
    )
    class_match = any(marker.casefold() in class_text for marker in policy.class_markers)
    title_match = any(marker.casefold() in title for marker in policy.title_markers)
    return class_match or (title_match and not excluded_browser)


def _sensitive_window_match(
    snapshot: X11WindowSnapshot,
    policy: SensitiveWindowPolicy,
) -> str | None:
    if not snapshot.mapped and not policy.include_unmapped:
        return None
    title = snapshot.title.casefold()
    class_text = " ".join(snapshot.wm_class).casefold()
    for marker in policy.title_markers:
        if marker.casefold() in title:
            return marker
    for marker in policy.class_markers:
        if marker.casefold() in class_text:
            return marker
    return None


def _intersect(left: Rect, right: Rect) -> Rect | None:
    if left.space is not CoordinateSpace.DESKTOP or right.space is not CoordinateSpace.DESKTOP:
        raise ValueError("window mask intersection requires desktop coordinates")
    x1 = max(left.x, right.x)
    y1 = max(left.y, right.y)
    x2 = min(left.x + left.width, right.x + right.width)
    y2 = min(left.y + left.height, right.y + right.height)
    if x2 <= x1 or y2 <= y1:
        return None
    return Rect(x=x1, y=y1, width=x2 - x1, height=y2 - y1, space=CoordinateSpace.DESKTOP)


def _decode_x_property(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00")
    try:
        raw = bytes(cast(Iterable[int], value))
    except (TypeError, ValueError):
        return str(value)
    return raw.decode("utf-8", errors="replace").rstrip("\x00")
