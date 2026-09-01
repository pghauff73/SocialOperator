from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from socialoperator.config import AppConfig
from socialoperator.knowledge.database import Database


def sqlite_codec_available() -> bool:
    with sqlite3.connect(":memory:") as connection:
        options = {str(row[0]) for row in connection.execute("PRAGMA compile_options")}
    return "SQLITE_HAS_CODEC" in options


def at_rest_protection_report(
    config: AppConfig,
    *,
    workspace: Path,
    database: Database | None = None,
) -> dict[str, Any]:
    private_directory_mode = int(config.security.private_directory_mode, 8)
    private_file_mode = int(config.security.private_file_mode, 8)
    directories = {
        "private_data_dir": config.resolve_path(config.paths.private_data_dir, workspace=workspace),
        "artifact_dir": config.resolve_path(config.paths.artifact_dir, workspace=workspace),
        "browser_profile_dir": config.resolve_path(
            config.paths.browser_profile_dir,
            workspace=workspace,
        ),
    }
    database_path = (
        database.path
        if database is not None
        else config.resolve_path(config.paths.database_path, workspace=workspace)
    )
    file_paths = {
        "database": database_path,
        "database-wal": database_path.with_name(database_path.name + "-wal"),
        "database-shm": database_path.with_name(database_path.name + "-shm"),
    }
    directory_checks = {
        name: _mode_check(path, expected_mode=private_directory_mode, required=True)
        for name, path in directories.items()
    }
    file_checks = {
        name: _mode_check(path, expected_mode=private_file_mode, required=name == "database")
        for name, path in file_paths.items()
    }
    filesystem_ok = all(
        check["ok"] for check in (*directory_checks.values(), *file_checks.values())
    )
    codec_available = sqlite_codec_available()
    application_encryption_required = config.security.require_application_encryption_for_real_data
    active_acceptance = database.active_at_rest_acceptance() if database is not None else None
    accepted_without_application_encryption = (
        not application_encryption_required and active_acceptance is not None
    )
    ok_for_real_data = filesystem_ok and (
        codec_available or accepted_without_application_encryption
    )
    blocked_reasons: list[str] = []
    if not filesystem_ok:
        blocked_reasons.append("private filesystem permissions are not verified")
    if application_encryption_required and not codec_available:
        blocked_reasons.append("application-level SQLite encryption is required but unavailable")
    if not application_encryption_required and not accepted_without_application_encryption:
        blocked_reasons.append("full-disk encryption acceptance is required but absent")
    if not config.security.allow_real_site_capture:
        blocked_reasons.append("real-site capture is disabled by configuration")
    return {
        "schema": "socialoperator.at_rest_protection.v1",
        "filesystem": {
            "ok": filesystem_ok,
            "directories": directory_checks,
            "files": file_checks,
        },
        "sqlite_encryption": {
            "codec_available": codec_available,
            "application_encryption_required": application_encryption_required,
            "accepted_without_application_encryption": accepted_without_application_encryption,
            "active_full_disk_acceptance_id": (
                active_acceptance["at_rest_acceptance_id"] if active_acceptance else None
            ),
        },
        "real_site_capture": {
            "allowed_by_config": config.security.allow_real_site_capture,
            "ok_for_real_data": ok_for_real_data,
            "blocked": bool(blocked_reasons),
            "blocked_reasons": tuple(blocked_reasons),
        },
    }


def _mode_check(path: Path, *, expected_mode: int, required: bool) -> dict[str, Any]:
    exists = path.exists()
    if not exists:
        return {
            "path": str(path),
            "exists": False,
            "required": required,
            "expected_mode": oct(expected_mode),
            "actual_mode": None,
            "ok": not required,
        }
    actual_mode = path.stat().st_mode & 0o777
    return {
        "path": str(path),
        "exists": True,
        "required": required,
        "expected_mode": oct(expected_mode),
        "actual_mode": oct(actual_mode),
        "ok": actual_mode == expected_mode,
    }
