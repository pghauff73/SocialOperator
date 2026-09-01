from __future__ import annotations

import json
import os
import re
import time
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from socialoperator.audit.events import AuditLogger
from socialoperator.audit.sessions import SessionManager
from socialoperator.browser.coordinate_map import WindowCalibration, visual_window_calibration
from socialoperator.browser.window_masks import (
    SensitiveWindow,
    WindowMaskDiscoveryError,
    discover_operator_window_masks,
    discover_sensitive_x11_windows,
    redact_operator_windows_from_png,
)
from socialoperator.config import AppConfig, SitePolicy, site_policy_sha256
from socialoperator.knowledge.database import Database
from socialoperator.policy.domains import is_url_allowed
from socialoperator.security.at_rest import sqlite_codec_available
from socialoperator.types import OperatorState, Rect


class BrowserSessionError(RuntimeError):
    """Base error for supervised browser sessions."""


class PrivacyBoundaryError(BrowserSessionError):
    """Raised when capture or automation crosses the authentication privacy boundary."""


class OriginPolicyError(BrowserSessionError):
    """Raised when the current page is outside the approved site policy."""


class ProfileInUseError(BrowserSessionError):
    """Raised when another SocialOperator process owns the dedicated profile."""


class SessionBudgetExceeded(BrowserSessionError):
    """Raised when page, action, time, or capture-byte budgets are exhausted."""


class RealSiteReadinessError(BrowserSessionError):
    """Raised when a real-site session lacks explicit readiness evidence."""


class ProfileLock:
    def __init__(self, profile_dir: Path) -> None:
        self.path = profile_dir / ".socialoperator-profile.lock"
        self.acquired = False

    @staticmethod
    def _process_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(0o700)
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                pid = int(payload["pid"])
            except (ValueError, KeyError, json.JSONDecodeError):
                pid = -1
            if pid > 0 and self._process_exists(pid):
                raise ProfileInUseError(f"dedicated browser profile is already in use by PID {pid}")
            self.path.unlink(missing_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, json.dumps({"pid": os.getpid()}).encode())
        finally:
            os.close(descriptor)
        self.acquired = True

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


class BrowserSession:
    SENSITIVE_SELECTORS = (
        "input[type='password']",
        "input[autocomplete='current-password']",
        "input[autocomplete='new-password']",
        "input[autocomplete='one-time-code']",
        "input[autocomplete~='webauthn']",
        "[aria-label*='passkey' i]",
        "[aria-label*='security key' i]",
        "[aria-label*='captcha' i]",
        ".g-recaptcha",
        ".h-captcha",
        "[data-sitekey]",
        "iframe[src*='captcha' i]",
        "iframe[title*='captcha' i]",
    )
    SENSITIVE_TEXT_PATTERN = re.compile(
        r"\b(passkey|security key|captcha|verification code|one[- ]?time code|mfa)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        config: AppConfig,
        site_policy: SitePolicy,
        *,
        workspace: Path,
        database: Database | None = None,
        profile_dir: Path | None = None,
        headless: bool | None = None,
    ) -> None:
        self.config = config
        self.site_policy = site_policy
        self.workspace = workspace.resolve()
        self.profile_dir = profile_dir or config.resolve_path(
            config.paths.browser_profile_dir,
            workspace=self.workspace,
        )
        self.headless = config.browser.headless if headless is None else headless
        self.database = database
        self.session_manager = SessionManager(database) if database else None
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.profile_lock = ProfileLock(self.profile_dir)
        self.manual_privacy_mode = True
        self.state = OperatorState.STOPPED
        self._started_monotonic: float | None = None
        self._observed_urls: set[str] = set()
        self._action_attempt_count = 0
        self._captured_bytes = 0
        self.last_capture_redaction_rectangles: tuple[Rect, ...] = ()

    def start(self, initial_url: str = "about:blank") -> Page:
        if self.context is not None:
            raise BrowserSessionError("browser session is already started")
        self.require_real_site_ready()
        self.profile_lock.acquire()
        self._started_monotonic = time.monotonic()
        self._observed_urls = set()
        self._action_attempt_count = 0
        self._captured_bytes = 0
        self.last_capture_redaction_rectangles = ()
        if self.session_manager:
            self.session_manager.start(
                {
                    "site_id": self.site_policy.site_id,
                    "profile_dir": str(self.profile_dir),
                    "headless": self.headless,
                    "limits": self.budget_snapshot(),
                }
            )
        self.state = OperatorState.STARTING
        try:
            self.playwright = sync_playwright().start()
            browser_type = getattr(self.playwright, self.config.browser.browser_name)
            launch_arguments: dict[str, object] = {
                "headless": self.headless,
                "viewport": {
                    "width": self.config.browser.default_viewport_width,
                    "height": self.config.browser.default_viewport_height,
                },
                "args": [
                    "--disable-sync",
                    "--window-position=20,20",
                    (
                        "--window-size="
                        f"{self.config.browser.default_viewport_width + 40},"
                        f"{self.config.browser.default_viewport_height + 120}"
                    ),
                ],
            }
            if self.config.browser.channel:
                launch_arguments["channel"] = self.config.browser.channel
            self.context = browser_type.launch_persistent_context(
                str(self.profile_dir),
                **launch_arguments,
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.set_default_timeout(self.config.browser.action_timeout_seconds * 1000)
            if initial_url != "about:blank":
                self.page.goto(initial_url, wait_until="domcontentloaded")
            self.state = OperatorState.LOGIN_REQUIRED
            if self.session_manager:
                self.session_manager.transition(OperatorState.LOGIN_REQUIRED)
            return self.page
        except Exception:
            self.stop(halted=True)
            raise

    def stop(self, *, halted: bool = False) -> None:
        state = OperatorState.HALTED if halted else OperatorState.STOPPED
        if self.context is not None:
            self.context.close()
            self.context = None
        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None
        if self.session_manager and self.session_manager.session_id:
            self.session_manager.transition(state, ended=True)
        self.page = None
        self.manual_privacy_mode = True
        self.state = state
        self._started_monotonic = None
        self._observed_urls = set()
        self._action_attempt_count = 0
        self._captured_bytes = 0
        self.last_capture_redaction_rectangles = ()
        self.profile_lock.release()

    def __enter__(self) -> BrowserSession:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop(halted=exc is not None)

    def set_privacy_mode(self, enabled: bool) -> None:
        self.manual_privacy_mode = enabled

    def require_real_site_ready(self) -> None:
        if not self.site_policy.real_site:
            return
        if not self.config.security.allow_real_site_capture:
            raise RealSiteReadinessError("real-site capture is disabled by configuration")
        if (
            self.config.security.require_application_encryption_for_real_data
            and not sqlite_codec_available()
        ):
            raise RealSiteReadinessError(
                "application-level SQLite encryption is required but unavailable"
            )
        if self.database is None:
            raise RealSiteReadinessError("real-site sessions require a private database")
        if (
            not self.config.security.require_application_encryption_for_real_data
            and self.database.active_at_rest_acceptance() is None
        ):
            raise RealSiteReadinessError(
                "full-disk encryption acceptance is required when application "
                "encryption is disabled"
            )
        approval = self.database.active_site_scope_approval(
            site_id=self.site_policy.site_id,
            policy_sha256=site_policy_sha256(self.site_policy),
        )
        if approval is None:
            raise RealSiteReadinessError(
                "real-site policy requires an active exact-hash scope approval"
            )

    def transition(self, state: OperatorState) -> None:
        self.state = state
        if self.session_manager:
            self.session_manager.transition(state)

    def budget_snapshot(self) -> dict[str, object]:
        elapsed = 0.0
        if self._started_monotonic is not None:
            elapsed = time.monotonic() - self._started_monotonic
        return {
            "elapsed_seconds": round(elapsed, 3),
            "observed_pages": len(self._observed_urls),
            "action_attempts": self._action_attempt_count,
            "captured_bytes": self._captured_bytes,
            "maximum_pages_per_session": self.config.limits.maximum_pages_per_session,
            "maximum_actions_per_session": self.config.limits.maximum_actions_per_session,
            "maximum_session_minutes": self.config.limits.maximum_session_minutes,
            "maximum_capture_bytes": self.config.limits.maximum_capture_bytes,
        }

    def require_session_budget(
        self,
        *,
        next_pages: int = 0,
        next_actions: int = 0,
        next_capture_bytes: int = 0,
    ) -> None:
        if self._started_monotonic is None:
            return
        if next_pages < 0 or next_actions < 0 or next_capture_bytes < 0:
            raise ValueError("budget increments must be non-negative")
        elapsed_seconds = time.monotonic() - self._started_monotonic
        maximum_seconds = self.config.limits.maximum_session_minutes * 60
        if elapsed_seconds > maximum_seconds:
            self._pause_for_budget("session time budget exceeded")
        if len(self._observed_urls) + next_pages > self.config.limits.maximum_pages_per_session:
            self._pause_for_budget("page budget exceeded")
        if (
            self._action_attempt_count + next_actions
            > self.config.limits.maximum_actions_per_session
        ):
            self._pause_for_budget("action budget exceeded")
        if self._captured_bytes + next_capture_bytes > self.config.limits.maximum_capture_bytes:
            self._pause_for_budget("capture byte budget exceeded")

    def record_page_observed(self, url: str) -> None:
        if url not in self._observed_urls:
            self.require_session_budget(next_pages=1)
            self._observed_urls.add(url)
        self.require_session_budget()

    def record_action_attempt(self) -> None:
        self.require_session_budget(next_actions=1)
        self._action_attempt_count += 1

    def record_capture_bytes(self, byte_length: int) -> None:
        self.require_session_budget(next_capture_bytes=byte_length)
        self._captured_bytes += byte_length

    def _pause_for_budget(self, reason: str) -> None:
        if self.session_manager and self.session_manager.session_id:
            assert self.database is not None
            AuditLogger(self.database, self.session_manager.session_id).write(
                "SESSION_BUDGET_EXCEEDED",
                {"reason": reason, "budget": self.budget_snapshot()},
            )
        if self.state not in {
            OperatorState.STOPPED,
            OperatorState.HALTED,
            OperatorState.PAUSED,
            OperatorState.PAUSED_RECOVERY,
        }:
            self.transition(OperatorState.PAUSED)
        else:
            self.state = OperatorState.PAUSED
        raise SessionBudgetExceeded(reason)

    def poll_control_requests(self) -> dict[str, object] | None:
        if (
            self.database is None
            or self.session_manager is None
            or self.session_manager.session_id is None
        ):
            return None
        request = self.database.next_control_request(self.session_manager.session_id)
        if request is None:
            return None
        command = str(request["command"])
        request_id = str(request["control_request_id"])
        try:
            if command == "pause":
                self.transition(OperatorState.PAUSED)
                self.database.acknowledge_control_request(
                    request_id,
                    metadata={"applied_state": self.state.value},
                )
            elif command == "resume":
                if self.state not in {OperatorState.PAUSED, OperatorState.PAUSED_RECOVERY}:
                    raise BrowserSessionError("resume control requires a paused session")
                self.resume_after_login()
                self.database.acknowledge_control_request(
                    request_id,
                    metadata={"applied_state": self.state.value},
                )
            elif command == "stop":
                self.database.acknowledge_control_request(
                    request_id,
                    metadata={"applied_state": OperatorState.STOPPED.value},
                )
                self.stop()
            else:
                raise BrowserSessionError(f"unsupported control command: {command}")
        except Exception as error:
            if command != "stop":
                self.database.acknowledge_control_request(
                    request_id,
                    status="rejected",
                    metadata={"error": str(error), "state": self.state.value},
                )
            raise
        return request

    def page_sensitive_elements_visible(self) -> bool:
        page = self.require_page()
        for selector in self.SENSITIVE_SELECTORS:
            locator = page.locator(selector)
            for index in range(locator.count()):
                if locator.nth(index).is_visible():
                    return True
        text_locator = page.locator("button,a,label,summary,[role='button']").filter(
            has_text=self.SENSITIVE_TEXT_PATTERN
        )
        return any(text_locator.nth(index).is_visible() for index in range(text_locator.count()))

    def sensitive_browser_chrome_windows(self) -> tuple[SensitiveWindow, ...]:
        if self.headless:
            return ()
        try:
            return discover_sensitive_x11_windows()
        except WindowMaskDiscoveryError:
            return (
                SensitiveWindow(
                    window_id="unknown",
                    title="X11 sensitive-window discovery failed",
                    wm_class=(),
                    matched_phrase="fail-closed",
                ),
            )

    def sensitive_elements_visible(self) -> bool:
        return self.page_sensitive_elements_visible() or bool(
            self.sensitive_browser_chrome_windows()
        )

    def capture_allowed(self) -> bool:
        return not self.manual_privacy_mode and not self.sensitive_elements_visible()

    def require_capture_allowed(self) -> None:
        if not self.capture_allowed():
            raise PrivacyBoundaryError(
                "capture and OCR are disabled while privacy mode or "
                "authentication-sensitive fields are active"
            )

    def require_not_paused_or_stopped(self) -> None:
        if self.state in {
            OperatorState.PAUSED,
            OperatorState.PAUSED_RECOVERY,
            OperatorState.STOPPED,
            OperatorState.HALTED,
        }:
            raise BrowserSessionError(f"browser session is not active: {self.state.value}")

    def current_origin_allowed(self) -> bool:
        return self.url_allowed(self.require_page().url)

    def url_allowed(self, url: str) -> bool:
        return is_url_allowed(url, self.site_policy)

    def require_url_allowed(self, url: str) -> None:
        if not self.url_allowed(url):
            raise OriginPolicyError(f"URL is outside the approved policy: {url}")

    def resume_after_login(self) -> None:
        if self.sensitive_elements_visible():
            raise PrivacyBoundaryError("authentication-sensitive fields remain visible")
        if not self.current_origin_allowed():
            raise OriginPolicyError(
                f"current page is outside the approved policy: {self.require_page().url}"
            )
        self.require_session_budget()
        self.manual_privacy_mode = False
        self.transition(OperatorState.READY)

    def window_calibration(self) -> WindowCalibration:
        page = self.require_page()
        metrics = page.evaluate(
            """() => ({
              screenX: window.screenX,
              screenY: window.screenY,
              outerWidth: window.outerWidth,
              outerHeight: window.outerHeight,
              innerWidth: window.innerWidth,
              innerHeight: window.innerHeight,
              deviceScaleFactor: window.devicePixelRatio
            })"""
        )
        if not self.headless:
            self.require_capture_allowed()
            page_png = self._capture_raw_page_png()
            self.record_capture_bytes(len(page_png))
            return visual_window_calibration(
                page_png=page_png,
                screen_x=float(metrics["screenX"]),
                screen_y=float(metrics["screenY"]),
                outer_width=float(metrics["outerWidth"]),
                outer_height=float(metrics["outerHeight"]),
                inner_width=float(metrics["innerWidth"]),
                inner_height=float(metrics["innerHeight"]),
                device_scale_factor=float(metrics["deviceScaleFactor"]),
            )
        return WindowCalibration.from_browser_metrics(
            screen_x=float(metrics["screenX"]),
            screen_y=float(metrics["screenY"]),
            outer_width=float(metrics["outerWidth"]),
            outer_height=float(metrics["outerHeight"]),
            inner_width=float(metrics["innerWidth"]),
            inner_height=float(metrics["innerHeight"]),
            device_scale_factor=float(metrics["deviceScaleFactor"]),
        )

    def capture_page_png(self, *, maximum_attempts: int = 3) -> bytes:
        self.poll_control_requests()
        self.require_not_paused_or_stopped()
        self.require_capture_allowed()
        screenshot = self._capture_raw_page_png(maximum_attempts=maximum_attempts)
        screenshot = self._redact_operator_windows(screenshot)
        self.record_capture_bytes(len(screenshot))
        return screenshot

    def _capture_raw_page_png(self, *, maximum_attempts: int = 3) -> bytes:
        page = self.require_page()
        last_error: PlaywrightError | None = None
        for attempt in range(maximum_attempts):
            try:
                return page.screenshot(
                    type="png",
                    full_page=False,
                    animations="disabled",
                )
            except PlaywrightError as error:
                last_error = error
                if attempt + 1 < maximum_attempts:
                    page.wait_for_timeout(100)
        raise BrowserSessionError(
            f"unable to capture page screenshot after {maximum_attempts} attempts"
        ) from last_error

    def require_page(self) -> Page:
        if self.page is None:
            raise BrowserSessionError("browser session has not been started")
        return self.page

    def _redact_operator_windows(self, screenshot: bytes) -> bytes:
        self.last_capture_redaction_rectangles = ()
        if self.headless or not self.config.capture.redact_operator_windows:
            return screenshot
        page = self.require_page()
        metrics = page.evaluate(
            """() => ({
              screenX: window.screenX,
              screenY: window.screenY,
              outerWidth: window.outerWidth,
              outerHeight: window.outerHeight,
              innerWidth: window.innerWidth,
              innerHeight: window.innerHeight,
              deviceScaleFactor: window.devicePixelRatio
            })"""
        )
        with Image.open(BytesIO(screenshot)) as image:
            screenshot_width, screenshot_height = image.size
        calibration = WindowCalibration.from_browser_metrics(
            screen_x=float(metrics["screenX"]),
            screen_y=float(metrics["screenY"]),
            outer_width=float(metrics["outerWidth"]),
            outer_height=float(metrics["outerHeight"]),
            inner_width=float(screenshot_width),
            inner_height=float(screenshot_height),
            device_scale_factor=float(metrics["deviceScaleFactor"]),
        )
        try:
            masks = discover_operator_window_masks()
        except WindowMaskDiscoveryError as error:
            raise PrivacyBoundaryError(
                "operator-window redaction is enabled but X11 window discovery failed"
            ) from error
        redacted, rectangles = redact_operator_windows_from_png(
            screenshot,
            calibration=calibration,
            masks=masks,
        )
        self.last_capture_redaction_rectangles = rectangles
        return redacted
