from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from playwright.sync_api import Download, Page

from socialoperator.audit.events import AuditLogger
from socialoperator.browser.models import InteractiveTarget, PageObservation
from socialoperator.browser.native_mouse import MouseSafetyController
from socialoperator.browser.observer import PageObserver
from socialoperator.browser.session import BrowserSession
from socialoperator.browser.target_fusion import TargetCandidate, select_target
from socialoperator.policy.actions import authorize_action
from socialoperator.types import ActionRisk, CoordinateSpace, OperatorState, Rect


class ActionVerificationError(RuntimeError):
    """Raised when hover or action postconditions cannot be verified."""


@dataclass(frozen=True, slots=True)
class Postcondition:
    kind: str
    value: str

    @classmethod
    def selector_visible(cls, selector: str) -> Postcondition:
        return cls("selector_visible", selector)

    @classmethod
    def url_changed(cls, previous_url: str) -> Postcondition:
        return cls("url_changed", previous_url)

    @classmethod
    def title_equals(cls, title: str) -> Postcondition:
        return cls("title_equals", title)

    @classmethod
    def text_visible(cls, text: str) -> Postcondition:
        return cls("text_visible", text)

    @classmethod
    def selector_hidden(cls, selector: str) -> Postcondition:
        return cls("selector_hidden", selector)

    @classmethod
    def url_equals(cls, expected_url: str) -> Postcondition:
        return cls("url_equals", expected_url)

    @classmethod
    def popup_url_equals(cls, expected_url: str) -> Postcondition:
        return cls("popup_url_equals", expected_url)

    @classmethod
    def download_filename_equals(cls, expected_filename: str) -> Postcondition:
        return cls("download_filename_equals", expected_filename)

    @classmethod
    def scroll_y_changed(cls, previous_scroll_y: float) -> Postcondition:
        return cls("scroll_y_changed", repr(previous_scroll_y))

    @classmethod
    def selector_text_equals(cls, selector: str, expected_text: str) -> Postcondition:
        value = json.dumps(
            {"selector": selector, "expected_text": expected_text},
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls("selector_text_equals", value)

    @classmethod
    def selector_text_changed(cls, selector: str, previous_text: str) -> Postcondition:
        value = json.dumps(
            {"selector": selector, "previous_text": previous_text},
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls("selector_text_changed", value)


@dataclass(frozen=True, slots=True)
class ActionResult:
    action_id: str
    target: InteractiveTarget | None
    before_state_sha256: str
    after_state_sha256: str
    postcondition: Postcondition
    verified: bool
    postcondition_evidence: tuple[tuple[str, str], ...] = ()


def _normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _rect_payload(rect: Any) -> dict[str, object]:
    return {
        "x": rect.x,
        "y": rect.y,
        "width": rect.width,
        "height": rect.height,
        "space": rect.space.value,
    }


def observation_sha256(observation: PageObservation) -> str:
    payload = {
        "url": observation.url,
        "title": observation.title,
        "viewport": [observation.viewport_width, observation.viewport_height],
        "scale": observation.device_scale_factor,
        "scroll": [observation.scroll_x, observation.scroll_y],
        "headings": observation.headings,
        "readable_text": observation.readable_text,
        "aria": observation.aria_snapshot,
        "contexts": [
            {
                "id": context.context_id,
                "parent": context.parent_context_id,
                "frame_path": context.frame_path,
                "kind": context.kind,
                "url": context.url,
                "name": context.name,
                "same_origin": context.same_origin,
                "headings": context.headings,
                "readable_text": context.readable_text,
                "aria": context.aria_snapshot,
            }
            for context in observation.contexts
        ],
        "targets": [
            {
                "id": target.target_id,
                "role": target.role,
                "name": target.accessible_name,
                "text": target.text,
                "href": target.href,
                "enabled": target.enabled,
                "visible": target.visible,
                "rect": _rect_payload(target.rect),
                "context_id": target.context_id,
                "frame_path": target.frame_path,
                "local_rect": (
                    _rect_payload(target.local_rect) if target.local_rect is not None else None
                ),
                "shadow_host": target.shadow_host,
            }
            for target in observation.targets
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class VerifiedActionExecutor:
    def __init__(
        self,
        session: BrowserSession,
        mouse: MouseSafetyController,
        *,
        observer: PageObserver | None = None,
    ) -> None:
        self.session = session
        self.mouse = mouse
        self.observer = observer or PageObserver()

    def click(
        self,
        query: str,
        postcondition: Postcondition,
        *,
        ocr_text: str = "",
    ) -> ActionResult:
        if self.session.state is not OperatorState.READY:
            raise ActionVerificationError("browser session must be READY before an action")
        self.session.poll_control_requests()
        if self.session.state is not OperatorState.READY:
            raise ActionVerificationError("browser session must be READY before an action")
        self.session.record_action_attempt()
        action_id = str(uuid4())
        before = self.observer.observe(self.session)
        before_sha = observation_sha256(before)
        candidate = select_target(query, before.targets, ocr_text=ocr_text)
        self.session.transition(OperatorState.PLANNING_ACTION)
        try:
            self._authorize_candidate(candidate, postcondition)
            calibration = self.session.window_calibration()
            desktop_target = calibration.viewport_rect_to_desktop(candidate.target.rect)
            self.session.transition(OperatorState.MOVING_POINTER)
            self.mouse.move_to_target(desktop_target)
            self.session.transition(OperatorState.VERIFYING_HOVER)
            post_move_calibration = self.session.window_calibration()
            calibration.assert_compatible(post_move_calibration)
            candidate = self._revalidate_target(
                query,
                candidate,
                ocr_text=ocr_text,
                calibration=post_move_calibration,
            )
            self._verify_element_at_target(candidate)
            self.session.transition(OperatorState.CLICKING)
            popup, download = self._click_with_event_capture(postcondition)
            self.session.transition(OperatorState.VERIFYING_RESULT)
            postcondition_evidence = self._verify_postcondition(
                self.session.require_page(),
                postcondition,
                popup=popup,
                download=download,
            )
            after = self.observer.observe(self.session)
            after_sha = observation_sha256(after)
            self._record_action(
                action_id=action_id,
                candidate=candidate,
                action_type="click",
                before_sha=before_sha,
                after_sha=after_sha,
                postcondition=postcondition,
                result="verified",
                verified=True,
                postcondition_evidence=postcondition_evidence,
            )
            self.session.transition(OperatorState.READY)
            return ActionResult(
                action_id=action_id,
                target=candidate.target,
                before_state_sha256=before_sha,
                after_state_sha256=after_sha,
                postcondition=postcondition,
                verified=True,
                postcondition_evidence=tuple(sorted(postcondition_evidence.items())),
            )
        except Exception as error:
            self._record_action(
                action_id=action_id,
                candidate=candidate,
                action_type="click",
                before_sha=before_sha,
                after_sha=None,
                postcondition=postcondition,
                result="failed",
                failure_reason=str(error),
                verified=False,
            )
            self.session.transition(OperatorState.PAUSED)
            raise

    def scroll_viewport(
        self,
        amount: int,
        postcondition: Postcondition,
    ) -> ActionResult:
        if self.session.state is not OperatorState.READY:
            raise ActionVerificationError("browser session must be READY before an action")
        self.session.poll_control_requests()
        if self.session.state is not OperatorState.READY:
            raise ActionVerificationError("browser session must be READY before an action")
        if amount == 0:
            raise ActionVerificationError("scroll amount must be non-zero")
        self.session.record_action_attempt()
        action_id = str(uuid4())
        before = self.observer.observe(self.session)
        before_sha = observation_sha256(before)
        try:
            self._authorize_scroll(postcondition)
            calibration = self.session.window_calibration()
            viewport_center = Rect(
                before.viewport_width / 2 - 1,
                before.viewport_height / 2 - 1,
                2,
                2,
                CoordinateSpace.VIEWPORT,
            )
            desktop_target = calibration.viewport_rect_to_desktop(viewport_center)
            self.session.transition(OperatorState.MOVING_POINTER)
            self.mouse.move_to_target(desktop_target)
            self.session.transition(OperatorState.VERIFYING_HOVER)
            post_move_calibration = self.session.window_calibration()
            calibration.assert_compatible(post_move_calibration)
            self.session.transition(OperatorState.SCROLLING)
            self.mouse.scroll_current(amount)
            self.session.transition(OperatorState.VERIFYING_RESULT)
            postcondition_evidence = self._verify_postcondition(
                self.session.require_page(),
                postcondition,
                popup=None,
                download=None,
            )
            after = self.observer.observe(self.session)
            after_sha = observation_sha256(after)
            self._record_action(
                action_id=action_id,
                candidate=None,
                action_type="scroll",
                before_sha=before_sha,
                after_sha=after_sha,
                postcondition=postcondition,
                result="verified",
                verified=True,
                postcondition_evidence=postcondition_evidence,
                extra_metadata={
                    "scroll_amount": amount,
                    "viewport_anchor": _rect_payload(viewport_center),
                    "before_scroll": {"x": before.scroll_x, "y": before.scroll_y},
                    "after_scroll": {"x": after.scroll_x, "y": after.scroll_y},
                },
            )
            self.session.transition(OperatorState.READY)
            return ActionResult(
                action_id=action_id,
                target=None,
                before_state_sha256=before_sha,
                after_state_sha256=after_sha,
                postcondition=postcondition,
                verified=True,
                postcondition_evidence=tuple(sorted(postcondition_evidence.items())),
            )
        except Exception as error:
            self._record_action(
                action_id=action_id,
                candidate=None,
                action_type="scroll",
                before_sha=before_sha,
                after_sha=None,
                postcondition=postcondition,
                result="failed",
                failure_reason=str(error),
                verified=False,
                extra_metadata={"scroll_amount": amount},
            )
            self.session.transition(OperatorState.PAUSED)
            raise

    def _authorize_candidate(
        self,
        candidate: TargetCandidate,
        postcondition: Postcondition,
    ) -> None:
        authorization = authorize_action(
            ActionRisk.NAVIGATE,
            config=self.session.config,
            site_policy=self.session.site_policy,
        )
        if not authorization.allowed:
            raise ActionVerificationError(authorization.reason)
        if candidate.target.href is not None:
            self.session.require_url_allowed(candidate.target.href)
        if postcondition.kind in {"url_equals", "popup_url_equals"}:
            self.session.require_url_allowed(postcondition.value)
        if postcondition.kind == "url_changed" and candidate.target.href is None:
            raise ActionVerificationError(
                "URL-changing actions without an observed destination are not authorized"
            )

    def _authorize_scroll(self, postcondition: Postcondition) -> None:
        authorization = authorize_action(
            ActionRisk.NAVIGATE,
            config=self.session.config,
            site_policy=self.session.site_policy,
        )
        if not authorization.allowed:
            raise ActionVerificationError(authorization.reason)
        if postcondition.kind not in {
            "selector_visible",
            "selector_hidden",
            "text_visible",
            "scroll_y_changed",
        }:
            raise ActionVerificationError(
                f"scroll actions do not support {postcondition.kind!r} postconditions"
            )

    def _click_with_event_capture(
        self,
        postcondition: Postcondition,
    ) -> tuple[Page | None, Download | None]:
        page = self.session.require_page()
        timeout = self.session.config.browser.action_timeout_seconds * 1000
        if postcondition.kind == "popup_url_equals":
            with page.expect_popup(timeout=timeout) as popup_info:
                self.mouse.mouse.click()
            return popup_info.value, None
        if postcondition.kind == "download_filename_equals":
            with page.expect_download(timeout=timeout) as download_info:
                self.mouse.mouse.click()
            return None, download_info.value
        self.mouse.mouse.click()
        return None, None

    def _revalidate_target(
        self,
        query: str,
        previous: TargetCandidate,
        *,
        ocr_text: str,
        calibration: Any,
    ) -> TargetCandidate:
        current_observation = self.observer.observe(self.session)
        current = select_target(query, current_observation.targets, ocr_text=ocr_text)
        if current.target.target_id != previous.target.target_id:
            raise ActionVerificationError(
                "target identity or geometry changed during pointer travel"
            )
        desktop_rect = calibration.viewport_rect_to_desktop(current.target.rect)
        if not desktop_rect.contains(self.mouse.mouse.position()):
            raise ActionVerificationError("pointer is outside the revalidated target geometry")
        return current

    def _verify_element_at_target(self, candidate: TargetCandidate) -> None:
        page = self.session.require_page()
        frame = self.observer.resolve_frame(page, candidate.target.frame_path)
        center = (candidate.target.local_rect or candidate.target.rect).center
        value = frame.evaluate(
            """({x, y}) => {
              let element = document.elementFromPoint(x, y);
              while (element && element.shadowRoot) {
                const nested = element.shadowRoot.elementFromPoint(x, y);
                if (!nested || nested === element) break;
                element = nested;
              }
              if (!element) return null;
              const interactive = element.closest('a,button,input,select,textarea,summary,[role]');
              if (!interactive) return null;
              return {
                role: interactive.getAttribute('role') || interactive.tagName.toLowerCase(),
                name: interactive.getAttribute('aria-label') || interactive.innerText ||
                  interactive.getAttribute('title') || interactive.getAttribute('placeholder') || ''
              };
            }""",
            {"x": center.x, "y": center.y},
        )
        if not value:
            raise ActionVerificationError("no interactive element is present at the target center")
        expected = _normalized(candidate.target.accessible_name or candidate.target.text)
        actual = _normalized(str(value["name"]))
        if expected != actual:
            raise ActionVerificationError(
                f"hover target changed: expected {expected!r}, observed {actual!r}"
            )

    def _verify_postcondition(
        self,
        page: Page,
        postcondition: Postcondition,
        *,
        popup: Page | None,
        download: Download | None,
    ) -> dict[str, str]:
        timeout = self.session.config.browser.action_timeout_seconds * 1000
        if postcondition.kind == "selector_visible":
            page.locator(postcondition.value).wait_for(state="visible", timeout=timeout)
            self.session.require_url_allowed(page.url)
            return {"selector": postcondition.value, "state": "visible", "url": page.url}
        if postcondition.kind == "selector_hidden":
            page.locator(postcondition.value).wait_for(state="hidden", timeout=timeout)
            self.session.require_url_allowed(page.url)
            return {"selector": postcondition.value, "state": "hidden", "url": page.url}
        if postcondition.kind == "url_changed":
            page.wait_for_function(
                "previous => window.location.href !== previous",
                arg=postcondition.value,
                timeout=timeout,
            )
            self.session.require_url_allowed(page.url)
            return {"url": page.url, "previous_url": postcondition.value}
        if postcondition.kind == "url_equals":
            page.wait_for_url(postcondition.value, timeout=timeout)
            self.session.require_url_allowed(page.url)
            return {"url": page.url}
        if postcondition.kind == "title_equals":
            page.wait_for_function(
                "expected => document.title === expected",
                arg=postcondition.value,
                timeout=timeout,
            )
            self.session.require_url_allowed(page.url)
            return {"title": page.title(), "url": page.url}
        if postcondition.kind == "text_visible":
            page.get_by_text(postcondition.value, exact=True).wait_for(
                state="visible", timeout=timeout
            )
            self.session.require_url_allowed(page.url)
            return {"text": postcondition.value, "state": "visible", "url": page.url}
        if postcondition.kind == "popup_url_equals":
            if popup is None:
                raise ActionVerificationError("expected popup was not captured")
            popup.wait_for_url(postcondition.value, timeout=timeout)
            self.session.require_url_allowed(popup.url)
            evidence = {"popup_url": popup.url, "popup_title": popup.title()}
            popup.close()
            return evidence
        if postcondition.kind == "download_filename_equals":
            if download is None:
                raise ActionVerificationError("expected download was not captured")
            if download.suggested_filename != postcondition.value:
                raise ActionVerificationError(
                    "download filename mismatch: "
                    f"expected {postcondition.value!r}, got {download.suggested_filename!r}"
                )
            return {"download_filename": download.suggested_filename}
        if postcondition.kind == "scroll_y_changed":
            previous = float(postcondition.value)
            page.wait_for_function(
                "previous => window.scrollY !== previous",
                arg=previous,
                timeout=timeout,
            )
            self.session.require_url_allowed(page.url)
            current = float(page.evaluate("() => window.scrollY"))
            return {"previous_scroll_y": repr(previous), "scroll_y": repr(current), "url": page.url}
        if postcondition.kind == "selector_text_equals":
            payload = _postcondition_payload(postcondition)
            selector = str(payload["selector"])
            expected_text = str(payload["expected_text"])
            page.wait_for_function(
                """({selector, expectedText}) => {
                  const element = document.querySelector(selector);
                  return element && element.innerText.trim() === expectedText;
                }""",
                arg={"selector": selector, "expectedText": expected_text},
                timeout=timeout,
            )
            self.session.require_url_allowed(page.url)
            return {"selector": selector, "text": expected_text, "url": page.url}
        if postcondition.kind == "selector_text_changed":
            payload = _postcondition_payload(postcondition)
            selector = str(payload["selector"])
            previous_text = str(payload["previous_text"])
            page.wait_for_function(
                """({selector, previousText}) => {
                  const element = document.querySelector(selector);
                  return element && element.innerText.trim() !== previousText;
                }""",
                arg={"selector": selector, "previousText": previous_text},
                timeout=timeout,
            )
            self.session.require_url_allowed(page.url)
            current_text = str(page.locator(selector).inner_text()).strip()
            return {
                "selector": selector,
                "previous_text": previous_text,
                "text": current_text,
                "url": page.url,
            }
        raise ValueError(f"unsupported postcondition kind: {postcondition.kind}")

    def _record_action(
        self,
        *,
        action_id: str,
        candidate: TargetCandidate | None,
        action_type: str,
        before_sha: str,
        after_sha: str | None,
        postcondition: Postcondition,
        result: str,
        verified: bool,
        failure_reason: str | None = None,
        postcondition_evidence: dict[str, str] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        database = self.session.database
        session_manager = self.session.session_manager
        if database is None or session_manager is None or session_manager.session_id is None:
            return
        metadata: dict[str, Any] = {
            "postcondition_evidence": postcondition_evidence or {},
            **(extra_metadata or {}),
        }
        if candidate is not None:
            metadata.update(
                {
                    "target_id": candidate.target.target_id,
                    "target_role": candidate.target.role,
                    "target_name": candidate.target.accessible_name,
                    "target_rect": _rect_payload(candidate.target.rect),
                    "selection_score": candidate.score,
                    "selection_reasons": candidate.reasons,
                }
            )
        database.record_browser_action(
            action_id=action_id,
            session_id=session_manager.session_id,
            risk_level=ActionRisk.NAVIGATE.value,
            action_type=action_type,
            expected_postcondition=asdict(postcondition),
            before_state_sha256=before_sha,
            after_state_sha256=after_sha,
            result=result,
            failure_reason=failure_reason,
            verified=verified,
            metadata=metadata,
        )
        AuditLogger(database, session_manager.session_id).write(
            "BROWSER_ACTION_RECORDED",
            {
                "action_id": action_id,
                "result": result,
                "verified": verified,
                "before_state_sha256": before_sha,
                "after_state_sha256": after_sha,
            },
        )


def _postcondition_payload(postcondition: Postcondition) -> dict[str, object]:
    payload = json.loads(postcondition.value)
    if not isinstance(payload, dict):
        raise ActionVerificationError(f"invalid {postcondition.kind} payload")
    return payload
