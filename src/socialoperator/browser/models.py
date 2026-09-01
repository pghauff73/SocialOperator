from __future__ import annotations

from dataclasses import dataclass

from socialoperator.types import Rect


@dataclass(frozen=True, slots=True)
class InteractiveTarget:
    target_id: str
    role: str
    accessible_name: str
    text: str
    href: str | None
    enabled: bool
    visible: bool
    rect: Rect
    context_id: str = "main"
    frame_path: tuple[int, ...] = ()
    local_rect: Rect | None = None
    shadow_host: str | None = None


@dataclass(frozen=True, slots=True)
class ObservationContext:
    context_id: str
    parent_context_id: str | None
    frame_path: tuple[int, ...]
    kind: str
    url: str
    name: str
    same_origin: bool
    headings: tuple[str, ...]
    readable_text: str
    aria_snapshot: str


@dataclass(frozen=True, slots=True)
class PageObservation:
    url: str
    title: str
    captured_at: str
    viewport_width: int
    viewport_height: int
    device_scale_factor: float
    scroll_x: float
    scroll_y: float
    headings: tuple[str, ...]
    readable_text: str
    aria_snapshot: str
    targets: tuple[InteractiveTarget, ...]
    contexts: tuple[ObservationContext, ...] = ()
