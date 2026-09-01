from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Any

from socialoperator.browser.actions import (
    ActionVerificationError,
    Postcondition,
    VerifiedActionExecutor,
)
from socialoperator.browser.native_mouse import MouseSafetyController, NativeMouse, PyAutoGuiMouse
from socialoperator.browser.session import BrowserSession, OriginPolicyError
from socialoperator.config import load_config, load_site_policy
from socialoperator.knowledge.database import Database
from socialoperator.types import OperatorState, Point

ROOT = Path(__file__).resolve().parents[1]


def _session(temp: Path, database: Database) -> BrowserSession:
    config = load_config(ROOT / "config" / "default.toml")
    config = replace(
        config,
        browser=replace(config.browser, action_timeout_seconds=3.0),
    )
    return BrowserSession(
        config,
        load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml"),
        workspace=ROOT,
        database=database,
        profile_dir=temp / "profile",
        headless=False,
    )


class ResizeDuringMoveMouse:
    def __init__(self, delegate: NativeMouse, session: BrowserSession) -> None:
        self.delegate = delegate
        self.session = session

    def move_to(self, x: float, y: float, duration_seconds: float) -> None:
        self.delegate.move_to(x, y, duration_seconds)
        self.session.require_page().set_viewport_size({"width": 1320, "height": 900})

    def position(self) -> Point:
        return self.delegate.position()

    def click(self) -> None:
        self.delegate.click()

    def scroll(self, amount: int) -> None:
        self.delegate.scroll(amount)


def _executor(
    session: BrowserSession,
    *,
    mouse: NativeMouse | None = None,
    foreground_check: Callable[[], bool] | None = None,
) -> VerifiedActionExecutor:
    return VerifiedActionExecutor(
        session,
        MouseSafetyController(
            mouse or PyAutoGuiMouse(),
            foreground_check=foreground_check or (lambda: True),
            movement_duration_seconds=0.08,
        ),
    )


def _verified_case(
    executor: VerifiedActionExecutor,
    query: str,
    postcondition: Postcondition,
) -> dict[str, Any]:
    result = executor.click(query, postcondition, ocr_text=query)
    return {
        "query": query,
        "verified": result.verified,
        "action_id": result.action_id,
        "evidence": dict(result.postcondition_evidence),
    }


def _verified_scroll_case(
    executor: VerifiedActionExecutor,
    amount: int,
    postcondition: Postcondition,
) -> dict[str, Any]:
    result = executor.scroll_viewport(amount, postcondition)
    return {
        "query": "Native wheel scroll",
        "amount": amount,
        "verified": result.verified,
        "action_id": result.action_id,
        "evidence": dict(result.postcondition_evidence),
    }


def main() -> int:
    fixture_root = ROOT / "tests" / "fixtures" / "site"
    handler = partial(SimpleHTTPRequestHandler, directory=str(fixture_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    cases: list[dict[str, Any]] = []
    try:
        with TemporaryDirectory(prefix="socialoperator-action-cases-") as temporary:
            temp = Path(temporary)
            database = Database(temp / "operator.sqlite")
            database.initialize()
            session = _session(temp, database)
            try:
                session.start(f"{base_url}/actions.html")
                session.resume_after_login()
                executor = _executor(session)
                cases.append(
                    _verified_case(
                        executor,
                        "Open project popup",
                        Postcondition.popup_url_equals(f"{base_url}/project.html?popup=1"),
                    )
                )
                cases.append(
                    _verified_case(
                        executor,
                        "Download synthetic file",
                        Postcondition.download_filename_equals("synthetic.txt"),
                    )
                )
                cases.append(
                    _verified_case(
                        executor,
                        "Next page",
                        Postcondition.selector_text_equals("#page-indicator", "Page 2 of 2"),
                    )
                )
                previous_scroll = float(session.require_page().evaluate("() => window.scrollY"))
                cases.append(
                    _verified_scroll_case(
                        executor,
                        -6,
                        Postcondition.scroll_y_changed(previous_scroll),
                    )
                )
                session.require_page().goto(f"{base_url}/actions.html", wait_until="load")
                cases.append(
                    _verified_case(
                        executor,
                        "Navigate to project",
                        Postcondition.url_equals(f"{base_url}/project.html"),
                    )
                )
            finally:
                session.stop()

            for name, query, postcondition, expected_error in (
                (
                    "moving_target",
                    "Moving target",
                    Postcondition.text_visible("Moving target was clicked."),
                    ActionVerificationError,
                ),
                (
                    "missing_postcondition",
                    "No-op action",
                    Postcondition.text_visible("Never appears"),
                    Exception,
                ),
                (
                    "outside_policy",
                    "Outside policy link",
                    Postcondition.url_equals("https://example.invalid/outside"),
                    OriginPolicyError,
                ),
            ):
                case_temp = temp / name
                case_temp.mkdir()
                session = _session(case_temp, database)
                try:
                    session.start(f"{base_url}/actions.html")
                    session.resume_after_login()
                    executor = _executor(session)
                    try:
                        executor.click(query, postcondition, ocr_text=query)
                    except expected_error as error:
                        if name == "moving_target":
                            assert not session.require_page().locator("#click-result").is_visible()
                        cases.append(
                            {
                                "query": query,
                                "verified": False,
                                "expected_failure": True,
                                "error": str(error),
                                "state": session.state.value,
                                "url": session.require_page().url,
                            }
                        )
                        assert session.state is OperatorState.PAUSED
                    else:
                        raise AssertionError(f"{name} unexpectedly verified")
                finally:
                    session.stop()

            injected_cases = (
                (
                    "window_resize",
                    lambda session: _executor(
                        session,
                        mouse=ResizeDuringMoveMouse(PyAutoGuiMouse(), session),
                    ),
                    "browser geometry changed during action",
                ),
                (
                    "foreground_loss",
                    lambda session: _executor(
                        session,
                        foreground_check=iter((True, False)).__next__,
                    ),
                    "foreground window changed during pointer movement",
                ),
            )
            for name, executor_factory, expected_text in injected_cases:
                case_temp = temp / name
                case_temp.mkdir()
                session = _session(case_temp, database)
                try:
                    session.start(f"{base_url}/actions.html")
                    session.resume_after_login()
                    try:
                        executor_factory(session).click(
                            "No-op action",
                            Postcondition.text_visible("Never appears"),
                            ocr_text="No-op action",
                        )
                    except Exception as error:
                        assert expected_text in str(error)
                        cases.append(
                            {
                                "query": name,
                                "verified": False,
                                "expected_failure": True,
                                "error": str(error),
                                "state": session.state.value,
                                "url": session.require_page().url,
                            }
                        )
                        assert session.state is OperatorState.PAUSED
                    else:
                        raise AssertionError(f"{name} unexpectedly verified")
                finally:
                    session.stop()

            with database.connect() as connection:
                action_rows = connection.execute(
                    "SELECT result, COUNT(*) AS count FROM browser_actions GROUP BY result"
                ).fetchall()
            summary = {
                "verified_cases": sum(1 for case in cases if case.get("verified")),
                "expected_failure_cases": sum(1 for case in cases if case.get("expected_failure")),
                "database_results": {str(row["result"]): int(row["count"]) for row in action_rows},
                "cases": cases,
            }
            assert summary["verified_cases"] == 5
            assert summary["expected_failure_cases"] == 5
            assert summary["database_results"] == {"failed": 5, "verified": 5}
            report = ROOT / "reports" / "action-postcondition-fixture.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
            print(summary)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


raise SystemExit(main())
