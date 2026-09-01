from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from socialoperator.browser.observer import PageObserver
from socialoperator.browser.session import (
    BrowserSession,
    PrivacyBoundaryError,
    RealSiteReadinessError,
    SessionBudgetExceeded,
)
from socialoperator.browser.window_masks import SensitiveWindow, WindowMaskDiscoveryError
from socialoperator.config import AppConfig, load_config, load_site_policy, site_policy_sha256
from socialoperator.knowledge.database import Database
from socialoperator.types import OperatorState

ROOT = Path(__file__).resolve().parents[1]


def _session(
    tmp_path: Path,
    *,
    database: Database | None = None,
    config: AppConfig | None = None,
) -> BrowserSession:
    config = config or load_config(ROOT / "config" / "default.toml")
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    return BrowserSession(
        config,
        policy,
        workspace=ROOT,
        database=database,
        profile_dir=tmp_path / "profile",
        headless=True,
    )


def test_authentication_page_blocks_capture(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    session = _session(tmp_path)
    try:
        session.start(f"{fixture_server_url}/login.html")
        assert session.state is OperatorState.LOGIN_REQUIRED
        assert session.sensitive_elements_visible()
        assert not session.capture_allowed()
        with pytest.raises(PrivacyBoundaryError):
            PageObserver().screenshot(session)
        with pytest.raises(PrivacyBoundaryError):
            session.resume_after_login()
    finally:
        session.stop()


def test_passkey_and_captcha_page_blocks_capture(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    session = _session(tmp_path)
    try:
        session.start(f"{fixture_server_url}/auth-boundary.html")
        assert session.state is OperatorState.LOGIN_REQUIRED
        assert session.sensitive_elements_visible()
        assert not session.capture_allowed()
        with pytest.raises(PrivacyBoundaryError):
            PageObserver().observe(session)
    finally:
        session.stop()


def test_resume_observe_and_capture_fixture(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "operator.sqlite")
    database.initialize()
    session = _session(tmp_path, database=database)
    try:
        session.start(fixture_server_url)
        session.resume_after_login()
        observation = PageObserver().observe(session)
        names = {target.accessible_name for target in observation.targets}
        assert session.state is OperatorState.READY
        assert observation.title == "SocialOperator Fixture"
        assert observation.headings[0] == "SocialOperator Synthetic Profile"
        assert "synthetic user-owned portfolio data" in observation.readable_text
        assert "Open project details" in names
        assert "Read the synthetic project" in names
        screenshot = PageObserver().screenshot(session)
        assert screenshot.startswith(b"\x89PNG\r\n\x1a\n")
    finally:
        session.stop()
    assert database.verify()["ok"]


def test_observer_records_frame_shadow_and_boundary_contexts(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    session = _session(tmp_path)
    try:
        session.start(f"{fixture_server_url}/observer.html")
        session.resume_after_login()
        observation = PageObserver().observe(session)
    finally:
        session.stop()
    targets = {target.accessible_name: target for target in observation.targets}
    assert {"Main action", "Frame action", "Shadow action"} <= targets.keys()
    assert "Hidden action" not in targets
    assert "Disabled action" not in targets
    assert "Offscreen action" not in targets
    assert "Untrusted" not in targets
    assert targets["Frame action"].frame_path
    assert targets["Frame action"].context_id != "main"
    assert targets["Shadow action"].shadow_host == "shadow-host"
    assert "Same-origin frame evidence owned by synthetic-user." in observation.readable_text
    assert any(context.kind == "same_origin_frame" for context in observation.contexts)
    assert any(
        context.kind == "cross_origin_frame" and not context.same_origin
        for context in observation.contexts
    )


def test_session_action_budget_pauses_before_new_action(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    config = load_config(ROOT / "config" / "default.toml")
    config = replace(
        config,
        limits=replace(config.limits, maximum_actions_per_session=0),
    )
    database = Database(tmp_path / "operator.sqlite")
    database.initialize()
    session = _session(tmp_path, database=database, config=config)
    try:
        session.start(fixture_server_url)
        session.resume_after_login()
        with pytest.raises(SessionBudgetExceeded, match="action budget"):
            session.record_action_attempt()
        assert session.state is OperatorState.PAUSED
        with database.connect() as connection:
            event = connection.execute(
                "SELECT payload_json FROM audit_events WHERE event_type = 'SESSION_BUDGET_EXCEEDED'"
            ).fetchone()
        assert '"reason":"action budget exceeded"' in event["payload_json"]
    finally:
        session.stop()


def test_session_control_queue_pauses_and_resumes_running_session(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "operator.sqlite")
    database.initialize()
    session = _session(tmp_path, database=database)
    try:
        session.start(fixture_server_url)
        session.resume_after_login()
        assert session.session_manager is not None
        assert session.session_manager.session_id is not None
        session_id = session.session_manager.session_id
        pause_request_id = database.request_control(
            session_id=session_id,
            command="pause",
            reason="test pause",
        )
        assert session.poll_control_requests()["control_request_id"] == pause_request_id
        assert session.state is OperatorState.PAUSED
        paused_report = database.control_report(status="acknowledged")
        assert paused_report["requests"][0]["command"] == "pause"
        resume_request_id = database.request_control(
            session_id=session_id,
            command="resume",
            reason="test resume",
        )
        assert session.poll_control_requests()["control_request_id"] == resume_request_id
        assert session.state is OperatorState.READY
    finally:
        session.stop()


def test_session_page_budget_pauses_on_new_observed_url(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    config = load_config(ROOT / "config" / "default.toml")
    config = replace(
        config,
        limits=replace(config.limits, maximum_pages_per_session=1),
    )
    session = _session(tmp_path, config=config)
    try:
        session.start(fixture_server_url)
        session.resume_after_login()
        PageObserver().observe(session)
        session.require_page().goto(f"{fixture_server_url}/project.html", wait_until="load")
        with pytest.raises(SessionBudgetExceeded, match="page budget"):
            PageObserver().observe(session)
        assert session.state is OperatorState.PAUSED
    finally:
        session.stop()


def test_session_capture_byte_budget_pauses_after_oversized_capture(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    config = load_config(ROOT / "config" / "default.toml")
    config = replace(
        config,
        limits=replace(config.limits, maximum_capture_bytes=1),
    )
    session = _session(tmp_path, config=config)
    try:
        session.start(fixture_server_url)
        session.resume_after_login()
        with pytest.raises(SessionBudgetExceeded, match="capture byte budget"):
            PageObserver().screenshot(session)
        assert session.state is OperatorState.PAUSED
    finally:
        session.stop()


def test_browser_chrome_sensitive_window_blocks_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(ROOT / "config" / "default.toml")
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    session = BrowserSession(config, policy, workspace=ROOT, profile_dir=tmp_path, headless=False)
    monkeypatch.setattr(
        "socialoperator.browser.session.discover_sensitive_x11_windows",
        lambda: (
            SensitiveWindow(
                window_id="0x1",
                title="Use your passkey",
                wm_class=("chromium",),
                matched_phrase="passkey",
            ),
        ),
    )

    assert session.sensitive_browser_chrome_windows()[0].matched_phrase == "passkey"


def test_browser_chrome_sensitive_window_detection_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config(ROOT / "config" / "default.toml")
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    session = BrowserSession(config, policy, workspace=ROOT, profile_dir=tmp_path, headless=False)

    def raise_discovery_error() -> tuple[SensitiveWindow, ...]:
        raise WindowMaskDiscoveryError("display unavailable")

    monkeypatch.setattr(
        "socialoperator.browser.session.discover_sensitive_x11_windows",
        raise_discovery_error,
    )

    assert session.sensitive_browser_chrome_windows()[0].matched_phrase == "fail-closed"


def test_real_site_session_requires_enabled_capture_and_scope_approval(
    tmp_path: Path,
) -> None:
    config = load_config(ROOT / "config" / "default.toml")
    policy = load_site_policy(ROOT / "config" / "sites" / "real_site.example.toml")
    database = Database(tmp_path / "operator.sqlite")
    database.initialize()
    session = BrowserSession(config, policy, workspace=ROOT, database=database, headless=True)

    with pytest.raises(RealSiteReadinessError, match="disabled by configuration"):
        session.require_real_site_ready()


def test_real_site_session_accepts_matching_scope_approval_when_config_allows(
    tmp_path: Path,
) -> None:
    config = load_config(ROOT / "config" / "default.toml")
    config = replace(
        config,
        security=replace(
            config.security,
            allow_real_site_capture=True,
            require_application_encryption_for_real_data=False,
        ),
    )
    policy = load_site_policy(ROOT / "config" / "sites" / "real_site.example.toml")
    database = Database(tmp_path / "operator.sqlite")
    database.initialize()
    database.create_site_scope_approval(
        site_id=policy.site_id,
        policy_sha256=site_policy_sha256(policy),
        approved_by="test-user",
        scope_summary="Synthetic approval for example real-site scope.",
    )
    session = BrowserSession(config, policy, workspace=ROOT, database=database, headless=True)

    with pytest.raises(RealSiteReadinessError, match="full-disk encryption acceptance"):
        session.require_real_site_ready()

    database.create_at_rest_acceptance(
        accepted_by="test-user",
        evidence_summary="Synthetic full-disk encryption acceptance.",
    )
    session.require_real_site_ready()
