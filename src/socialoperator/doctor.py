from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

from socialoperator.config import load_config, load_site_policy
from socialoperator.security.at_rest import sqlite_codec_available


def _sqlite_capabilities() -> dict[str, object]:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE VIRTUAL TABLE test_fts USING fts5(body)")
        json_value = connection.execute("SELECT json_extract('{\"ok\":true}', '$.ok')").fetchone()[
            0
        ]
    return {
        "version": sqlite3.sqlite_version,
        "fts5": True,
        "json": bool(json_value),
    }


def run_doctor(config_path: str | Path) -> dict[str, Any]:
    config = load_config(config_path)
    workspace = config.source_path.parent.parent
    site_policy_path = workspace / "config" / "sites" / "local_fixture.toml"
    load_site_policy(site_policy_path)
    chrome_candidates = (
        shutil.which("google-chrome"),
        shutil.which("google-chrome-unstable"),
        shutil.which("chromium"),
        "/opt/google/chrome-unstable/chrome",
    )
    chrome = next((value for value in chrome_candidates if value and Path(value).exists()), None)
    checks: dict[str, Any] = {
        "python": {
            "version": sys.version.split()[0],
            "supported": sys.version_info >= (3, 13),
        },
        "sqlite": _sqlite_capabilities(),
        "display": {
            "xdg_session_type": os.environ.get("XDG_SESSION_TYPE", ""),
            "display": os.environ.get("DISPLAY", ""),
            "x11_ready": bool(os.environ.get("DISPLAY")),
        },
        "tesseract": shutil.which("tesseract"),
        "chrome": chrome,
        "python_modules": {
            module: importlib.util.find_spec(module) is not None
            for module in (
                "fastapi",
                "mss",
                "PIL",
                "playwright",
                "pyautogui",
                "pytesseract",
                "uvicorn",
                "Xlib",
            )
        },
        "at_rest": {
            "sqlite_codec_available": sqlite_codec_available(),
            "application_encryption_required": (
                config.security.require_application_encryption_for_real_data
            ),
        },
        "configuration": {
            "path": str(config.source_path),
            "real_site_capture": config.security.allow_real_site_capture,
            "external_side_effects": config.security.allow_external_side_effects,
        },
    }
    checks["ok"] = bool(
        checks["python"]["supported"]
        and checks["sqlite"]["fts5"]
        and checks["sqlite"]["json"]
        and checks["display"]["x11_ready"]
        and checks["tesseract"]
        and checks["chrome"]
        and all(checks["python_modules"].values())
    )
    return checks
