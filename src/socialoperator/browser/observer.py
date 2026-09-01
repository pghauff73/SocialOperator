from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse

from playwright._impl._api_structures import FloatRect
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, Page

from socialoperator.browser.models import InteractiveTarget, ObservationContext, PageObservation
from socialoperator.browser.session import BrowserSession
from socialoperator.capture.artifacts import ArtifactStore, StoredArtifact
from socialoperator.knowledge.database import utc_now
from socialoperator.types import CoordinateSpace, Rect, Sensitivity

TARGET_SCRIPT = r"""
element => {
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  const visible = rect.width > 0 && rect.height > 0 &&
    style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0';
  const tag = element.tagName.toLowerCase();
  const implicitRole = {
    a: 'link', button: 'button', select: 'combobox', textarea: 'textbox',
    summary: 'button'
  }[tag] || (tag === 'input' ? (element.type === 'checkbox' ? 'checkbox' : 'textbox') : '');
  const labelledBy = element.getAttribute('aria-labelledby');
  const labelledText = labelledBy ? labelledBy.split(/\s+/).map(id => {
    const label = document.getElementById(id);
    return label ? label.innerText : '';
  }).join(' ') : '';
  const explicitLabel = element.id
    ? document.querySelector(`label[for="${CSS.escape(element.id)}"]`)
    : null;
  const name = element.getAttribute('aria-label') || labelledText ||
    (explicitLabel ? explicitLabel.innerText : '') || element.innerText ||
    element.getAttribute('title') || element.getAttribute('placeholder') || '';
  const root = element.getRootNode();
  const shadowHost = root instanceof ShadowRoot
    ? (root.host.id || root.host.getAttribute('aria-label') || root.host.tagName.toLowerCase())
    : null;
  return {
    role: element.getAttribute('role') || implicitRole,
    accessibleName: name.trim(),
    text: (element.innerText || '').trim(),
    href: tag === 'a' ? element.href : null,
    enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
    visible,
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    tag,
    shadowHost
  };
}
"""

TARGET_SELECTOR = "a,button,input:not([type='hidden']),select,textarea,summary,[role]"


class PageObserver:
    def observe(self, session: BrowserSession) -> PageObservation:
        session.poll_control_requests()
        session.require_not_paused_or_stopped()
        session.require_capture_allowed()
        page = session.require_page()
        session.record_page_observed(page.url)
        viewport = page.viewport_size or {"width": 0, "height": 0}
        contexts: list[ObservationContext] = []
        targets: list[InteractiveTarget] = []
        main_origin = self._origin(page.url)
        for frame_path, frame in self._walk_frames(page):
            context, context_targets = self._observe_frame(
                frame,
                frame_path=frame_path,
                main_origin=main_origin,
                viewport_width=int(viewport["width"]),
                viewport_height=int(viewport["height"]),
            )
            contexts.append(context)
            targets.extend(context_targets)
        metrics = page.evaluate(
            """() => ({
              deviceScaleFactor: window.devicePixelRatio,
              scrollX: window.scrollX,
              scrollY: window.scrollY
            })"""
        )
        observed_contexts = tuple(contexts)
        headings = tuple(
            heading
            for context in observed_contexts
            if context.same_origin
            for heading in context.headings
        )
        readable_text = "\n\n".join(
            context.readable_text
            for context in observed_contexts
            if context.same_origin and context.readable_text
        )
        aria_snapshot = "\n\n".join(
            f"[context {context.context_id}]\n{context.aria_snapshot}"
            for context in observed_contexts
            if context.same_origin and context.aria_snapshot
        )
        return PageObservation(
            url=page.url,
            title=page.title(),
            captured_at=utc_now(),
            viewport_width=int(viewport["width"]),
            viewport_height=int(viewport["height"]),
            device_scale_factor=float(metrics["deviceScaleFactor"]),
            scroll_x=float(metrics["scrollX"]),
            scroll_y=float(metrics["scrollY"]),
            headings=headings,
            readable_text=readable_text,
            aria_snapshot=aria_snapshot,
            targets=tuple(targets),
            contexts=observed_contexts,
        )

    def screenshot(self, session: BrowserSession) -> bytes:
        return session.capture_page_png()

    def store_screenshot(
        self,
        session: BrowserSession,
        artifact_store: ArtifactStore,
    ) -> StoredArtifact:
        page = session.require_page()
        screenshot = self.screenshot(session)
        return artifact_store.put_bytes(
            screenshot,
            media_type="image/png",
            sensitivity=Sensitivity.PRIVATE,
            redacted=bool(session.last_capture_redaction_rectangles),
            metadata={
                "url": page.url,
                "title": page.title(),
                "capture": "viewport",
                "operator_window_redaction_rectangles": [
                    {
                        "x": rect.x,
                        "y": rect.y,
                        "width": rect.width,
                        "height": rect.height,
                    }
                    for rect in session.last_capture_redaction_rectangles
                ],
            },
        )

    def _observe_frame(
        self,
        frame: Frame,
        *,
        frame_path: tuple[int, ...],
        main_origin: tuple[str, str, int | None] | None,
        viewport_width: int,
        viewport_height: int,
    ) -> tuple[ObservationContext, tuple[InteractiveTarget, ...]]:
        context_id = self._context_id(frame_path, frame.url)
        parent_context_id = (
            self._context_id(frame_path[:-1], frame.parent_frame.url)
            if frame.parent_frame is not None
            else None
        )
        same_origin = not frame_path or self._origin(frame.url) == main_origin
        if not same_origin:
            return (
                ObservationContext(
                    context_id=context_id,
                    parent_context_id=parent_context_id,
                    frame_path=frame_path,
                    kind="cross_origin_frame",
                    url=frame.url,
                    name=frame.name,
                    same_origin=False,
                    headings=(),
                    readable_text="",
                    aria_snapshot="",
                ),
                (),
            )
        try:
            heading_values = frame.locator("h1,h2,h3,h4,h5,h6").all_inner_texts()
            headings = tuple(value.strip() for value in heading_values if value.strip())
            readable_text = frame.locator("body").inner_text().strip()
            aria_snapshot = str(frame.locator("body").aria_snapshot())
        except PlaywrightError:
            headings = ()
            readable_text = ""
            aria_snapshot = ""
        observed_targets: list[InteractiveTarget] = []
        locator = frame.locator(TARGET_SELECTOR)
        try:
            count = locator.count()
        except PlaywrightError:
            count = 0
        for index in range(count):
            element = locator.nth(index)
            try:
                raw = element.evaluate(TARGET_SCRIPT)
                bounding_box = element.bounding_box()
            except PlaywrightError:
                continue
            if not raw["visible"] or not raw["enabled"] or bounding_box is None:
                continue
            if not self._inside_viewport(
                bounding_box,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
            ):
                continue
            observed_targets.append(
                self._target_from_raw(
                    raw,
                    bounding_box,
                    context_id=context_id,
                    frame_path=frame_path,
                )
            )
        return (
            ObservationContext(
                context_id=context_id,
                parent_context_id=parent_context_id,
                frame_path=frame_path,
                kind="main" if not frame_path else "same_origin_frame",
                url=frame.url,
                name=frame.name,
                same_origin=True,
                headings=headings,
                readable_text=readable_text,
                aria_snapshot=aria_snapshot,
            ),
            tuple(observed_targets),
        )

    @staticmethod
    def _walk_frames(page: Page) -> tuple[tuple[tuple[int, ...], Frame], ...]:
        frames: list[tuple[tuple[int, ...], Frame]] = []

        def visit(frame: Frame, path: tuple[int, ...]) -> None:
            frames.append((path, frame))
            for index, child in enumerate(frame.child_frames):
                visit(child, (*path, index))

        visit(page.main_frame, ())
        return tuple(frames)

    @staticmethod
    def resolve_frame(page: Page, frame_path: tuple[int, ...]) -> Frame:
        frame = page.main_frame
        for index in frame_path:
            children = frame.child_frames
            if index >= len(children):
                raise LookupError(f"frame path no longer exists: {frame_path}")
            frame = children[index]
        return frame

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int | None] | None:
        parsed = urlparse(url)
        if parsed.scheme in {"about", "data", "blob"} or parsed.hostname is None:
            return None
        return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port

    @staticmethod
    def _context_id(frame_path: tuple[int, ...], url: str) -> str:
        if not frame_path:
            return "main"
        identity = f"{'/'.join(str(value) for value in frame_path)}|{url}".encode()
        return f"frame-{hashlib.sha256(identity).hexdigest()[:16]}"

    @staticmethod
    def _inside_viewport(
        bounding_box: FloatRect,
        *,
        viewport_width: int,
        viewport_height: int,
    ) -> bool:
        return (
            bounding_box["x"] + bounding_box["width"] > 0
            and bounding_box["y"] + bounding_box["height"] > 0
            and bounding_box["x"] < viewport_width
            and bounding_box["y"] < viewport_height
        )

    @staticmethod
    def _target_from_raw(
        value: dict[str, Any],
        bounding_box: FloatRect,
        *,
        context_id: str,
        frame_path: tuple[int, ...],
    ) -> InteractiveTarget:
        identity = "|".join(
            (
                context_id,
                str(value.get("role", "")),
                str(value.get("accessibleName", "")),
                str(value.get("href", "")),
                f"{float(bounding_box['x']):.2f}",
                f"{float(bounding_box['y']):.2f}",
                f"{float(bounding_box['width']):.2f}",
                f"{float(bounding_box['height']):.2f}",
            )
        ).encode()
        return InteractiveTarget(
            target_id=hashlib.sha256(identity).hexdigest(),
            role=str(value.get("role", "")),
            accessible_name=str(value.get("accessibleName", "")),
            text=str(value.get("text", "")),
            href=str(value["href"]) if value.get("href") else None,
            enabled=bool(value["enabled"]),
            visible=bool(value["visible"]),
            rect=Rect(
                x=float(bounding_box["x"]),
                y=float(bounding_box["y"]),
                width=float(bounding_box["width"]),
                height=float(bounding_box["height"]),
                space=CoordinateSpace.VIEWPORT,
            ),
            context_id=context_id,
            frame_path=frame_path,
            local_rect=Rect(
                x=float(value["x"]),
                y=float(value["y"]),
                width=float(value["width"]),
                height=float(value["height"]),
                space=CoordinateSpace.VIEWPORT,
            ),
            shadow_host=str(value["shadowHost"]) if value.get("shadowHost") else None,
        )
