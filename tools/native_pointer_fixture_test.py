from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread

from mss import MSS
from PIL import Image

from socialoperator.browser.actions import Postcondition, VerifiedActionExecutor
from socialoperator.browser.native_mouse import MouseSafetyController, PyAutoGuiMouse
from socialoperator.browser.observer import PageObserver
from socialoperator.browser.session import BrowserSession
from socialoperator.browser.target_fusion import select_target
from socialoperator.config import load_config, load_site_policy
from socialoperator.knowledge.database import Database

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.trials <= 0 or args.trials > 100:
        raise ValueError("--trials must be between 1 and 100")
    fixture_root = ROOT / "tests" / "fixtures" / "site"
    handler = partial(SimpleHTTPRequestHandler, directory=str(fixture_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with TemporaryDirectory(prefix="socialoperator-native-pointer-") as temporary:
            temp = Path(temporary)
            database = Database(temp / "operator.sqlite")
            database.initialize()
            session = BrowserSession(
                load_config(ROOT / "config" / "default.toml"),
                load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml"),
                workspace=ROOT,
                database=database,
                profile_dir=temp / "profile",
                headless=False,
            )
            try:
                session.start(f"http://{host}:{port}")
                session.resume_after_login()
                executor = VerifiedActionExecutor(
                    session,
                    MouseSafetyController(
                        PyAutoGuiMouse(),
                        foreground_check=lambda: True,
                        movement_duration_seconds=0.08,
                    ),
                )
                trial_results: list[dict[str, object]] = []
                latencies: list[float] = []
                try:
                    for trial in range(args.trials):
                        opening = trial % 2 == 0
                        query = "Open project details" if opening else "Close details"
                        postcondition = (
                            Postcondition.selector_visible("#details-dialog[open]")
                            if opening
                            else Postcondition.selector_hidden("#details-dialog[open]")
                        )
                        started = time.perf_counter()
                        result = executor.click(query, postcondition, ocr_text=query)
                        latency = time.perf_counter() - started
                        latencies.append(latency)
                        trial_results.append(
                            {
                                "trial": trial + 1,
                                "verified": result.verified,
                                "action_id": result.action_id,
                                "target": result.target.accessible_name,
                                "latency_seconds": latency,
                                "before": result.before_state_sha256,
                                "after": result.after_state_sha256,
                            }
                        )
                except Exception:
                    observation = PageObserver().observe(session)
                    candidate = select_target("Open project details", observation.targets)
                    calibration = session.window_calibration()
                    mapped = calibration.viewport_rect_to_desktop(candidate.target.rect)
                    page_metrics = session.require_page().evaluate(
                        """() => ({
                          screenX: window.screenX, screenY: window.screenY,
                          outerWidth: window.outerWidth, outerHeight: window.outerHeight,
                          innerWidth: window.innerWidth, innerHeight: window.innerHeight,
                          dpr: window.devicePixelRatio
                        })"""
                    )
                    with MSS() as capture:
                        monitor = capture.monitors[0]
                        frame = capture.grab(monitor)
                        image = Image.frombytes("RGB", frame.size, frame.rgb)
                        output = ROOT / "reports" / "native-pointer-failure.png"
                        output.parent.mkdir(parents=True, exist_ok=True)
                        image.save(output)
                    print(
                        {
                            "page_metrics": page_metrics,
                            "calibration": calibration,
                            "viewport_target": candidate.target.rect,
                            "desktop_target": mapped,
                            "mouse_position": executor.mouse.mouse.position(),
                            "screen_capture": str(output),
                        }
                    )
                    raise
                assert len(trial_results) == args.trials
                expected_open = args.trials % 2 == 1
                assert (
                    session.require_page().locator("#details-dialog").is_visible() is expected_open
                )
                with database.connect() as connection:
                    verified_count = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM browser_actions "
                            "WHERE result = 'verified' AND verified_at IS NOT NULL"
                        ).fetchone()[0]
                    )
                assert verified_count == args.trials
                summary = {
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "trials": args.trials,
                    "verified": verified_count,
                    "success_rate": verified_count / args.trials,
                    "latency_seconds": {
                        "minimum": min(latencies),
                        "median": statistics.median(latencies),
                        "maximum": max(latencies),
                    },
                    "results": trial_results,
                }
                if args.report is not None:
                    report = args.report.expanduser().resolve()
                    report.parent.mkdir(parents=True, exist_ok=True)
                    report.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
                print(summary)
            finally:
                session.stop()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


raise SystemExit(main())
