import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from socialoperator.audit.sessions import SessionManager
from socialoperator.cli import main
from socialoperator.knowledge.database import Database
from socialoperator.types import OperatorState

ROOT = Path(__file__).resolve().parents[1]


def test_cli_init_verify_backup_restore_delete(tmp_path: Path, capsys: object) -> None:
    config = ROOT / "config" / "default.toml"
    database = tmp_path / "private.sqlite"
    backup = tmp_path / "backup.sqlite"
    exported = tmp_path / "export.sqlite"
    report = tmp_path / "session-report.json"
    assert main(["init", "--config", str(config), "--db", str(database)]) == 0
    protection_report = tmp_path / "at-rest.json"
    assert (
        main(
            [
                "security",
                "at-rest-report",
                "--config",
                str(config),
                "--db",
                str(database),
                "--output",
                str(protection_report),
            ]
        )
        == 0
    )
    protection_payload = json.loads(protection_report.read_text())
    assert protection_payload["filesystem"]["ok"]
    assert "database" in protection_payload["filesystem"]["files"]
    assert protection_payload["real_site_capture"]["blocked"]
    assert main(["kb", "verify", "--config", str(config), "--db", str(database)]) == 0
    database_handle = Database(database)
    removable = database_handle.add_observation(
        observation_kind="dom",
        raw_text="CLI prune candidate",
        normalized_text="cli prune candidate",
    )
    protected = database_handle.add_observation(
        observation_kind="review",
        raw_text="CLI protected evidence",
        normalized_text="cli protected evidence",
        retention_protected=True,
    )
    cutoff = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert (
        main(
            [
                "kb",
                "prune",
                "--config",
                str(config),
                "--db",
                str(database),
                "--before",
                cutoff,
                "--confirm",
                "PRUNE",
            ]
        )
        == 0
    )
    with database_handle.connect() as connection:
        remaining = connection.execute(
            "SELECT observation_id FROM observations ORDER BY observation_id"
        ).fetchall()
    assert [row["observation_id"] for row in remaining] == [protected]
    assert removable != protected
    assert (
        main(
            [
                "security",
                "accept-full-disk",
                "--config",
                str(config),
                "--db",
                str(database),
                "--accepted-by",
                "test-user",
                "--summary",
                "Synthetic full-disk encryption acceptance.",
                "--confirm",
                "ACCEPT-FULL-DISK",
            ]
        )
        == 0
    )
    acceptance_report = database_handle.at_rest_acceptance_report(status="active")
    assert acceptance_report["acceptance_count"] == 1
    acceptance_id = acceptance_report["acceptances"][0]["at_rest_acceptance_id"]
    assert (
        main(
            [
                "security",
                "at-rest-acceptance-status",
                "--config",
                str(config),
                "--db",
                str(database),
                "--status",
                "active",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "security",
                "revoke-at-rest-acceptance",
                "--config",
                str(config),
                "--db",
                str(database),
                "--acceptance-id",
                acceptance_id,
            ]
        )
        == 0
    )
    assert database_handle.at_rest_acceptance_report(status="active")["acceptance_count"] == 0
    assert (
        main(
            [
                "site",
                "policy-report",
                "--policy",
                str(ROOT / "config" / "sites" / "real_site.example.toml"),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "site",
                "approve-scope",
                "--config",
                str(config),
                "--db",
                str(database),
                "--policy",
                str(ROOT / "config" / "sites" / "real_site.example.toml"),
                "--approver",
                "test-user",
                "--summary",
                "Approve the synthetic example real-site policy.",
                "--confirm",
                "APPROVE-SCOPE",
            ]
        )
        == 0
    )
    scope_report = database_handle.site_scope_report(site_id="example_real_site")
    assert scope_report["approval_count"] == 1
    approval_id = scope_report["approvals"][0]["site_scope_approval_id"]
    assert (
        main(
            [
                "site",
                "scope-status",
                "--config",
                str(config),
                "--db",
                str(database),
                "--site-id",
                "example_real_site",
                "--status",
                "active",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "site",
                "revoke-scope",
                "--config",
                str(config),
                "--db",
                str(database),
                "--approval-id",
                approval_id,
            ]
        )
        == 0
    )
    assert (
        database_handle.site_scope_report(site_id="example_real_site", status="active")[
            "approval_count"
        ]
        == 0
    )
    assert (
        main(
            [
                "kb",
                "backup",
                "--config",
                str(config),
                "--db",
                str(database),
                "--output",
                str(backup),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "kb",
                "export",
                "--config",
                str(config),
                "--db",
                str(database),
                "--output",
                str(exported),
            ]
        )
        == 0
    )
    assert exported.exists()
    assert (
        main(
            [
                "session",
                "report",
                "--config",
                str(config),
                "--db",
                str(database),
                "--output",
                str(report),
            ]
        )
        == 0
    )
    report_payload = json.loads(report.read_text())
    assert report_payload["database"] == database.name
    assert report_payload["session_count"] == 0
    manager = SessionManager(database_handle)
    session_id = manager.start({"cli": True})
    manager.transition(OperatorState.PAUSED)
    database_handle.append_audit_event("SYNTHETIC_INCIDENT", {"safe": True}, session_id=session_id)
    assert (
        main(
            [
                "session",
                "pause",
                "--config",
                str(config),
                "--db",
                str(database),
                "--session-id",
                session_id,
                "--reason",
                "CLI pause request",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "session",
                "control-status",
                "--config",
                str(config),
                "--db",
                str(database),
                "--session-id",
                session_id,
                "--status",
                "pending",
            ]
        )
        == 0
    )
    assert database_handle.control_report(session_id=session_id)["request_count"] == 1
    incident_dir = tmp_path / "incident"
    assert (
        main(
            [
                "session",
                "incident",
                "--config",
                str(config),
                "--db",
                str(database),
                "--session-id",
                session_id,
                "--summary",
                "Synthetic CLI incident",
                "--output-dir",
                str(incident_dir),
            ]
        )
        == 0
    )
    incident_payload = json.loads((incident_dir / "incident.json").read_text())
    assert incident_payload["incident"]["summary"] == "Synthetic CLI incident"
    assert incident_payload["evidence_manifest"]["session"]["session_id"] == session_id
    assert incident_payload["evidence_manifest"]["counts"]["events"] >= 1
    assert (incident_dir / "incident.md").is_file()
    assert (incident_dir / "incident.json").stat().st_mode & 0o777 == 0o600
    drill_dir = tmp_path / "incident-drill"
    assert (
        main(
            [
                "session",
                "incident-drill",
                "--config",
                str(config),
                "--db",
                str(database),
                "--summary",
                "Synthetic CLI incident drill",
                "--output-dir",
                str(drill_dir),
            ]
        )
        == 0
    )
    drill_payload = json.loads((drill_dir / "incident.json").read_text())
    assert drill_payload["incident"]["summary"] == "Synthetic CLI incident drill"
    assert drill_payload["evidence_manifest"]["counts"]["failed_actions"] == 1
    assert (drill_dir / "incident.md").stat().st_mode & 0o777 == 0o600
    assert (
        main(
            [
                "kb",
                "delete",
                "--config",
                str(config),
                "--db",
                str(database),
                "--confirm",
                "DELETE",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "kb",
                "restore",
                "--config",
                str(config),
                "--db",
                str(database),
                "--backup",
                str(backup),
            ]
        )
        == 0
    )
    assert database.exists()


def test_fixture_files_exist() -> None:
    fixture_root = ROOT / "tests" / "fixtures" / "site"
    assert (fixture_root / "index.html").is_file()
    assert "Open project details" in (fixture_root / "index.html").read_text()


def test_cli_ocr_golden_report(tmp_path: Path) -> None:
    output = tmp_path / "ocr-golden.json"

    assert (
        main(
            [
                "ocr",
                "golden",
                "--corpus",
                str(ROOT / "tests" / "fixtures" / "ocr" / "golden.json"),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    report = json.loads(output.read_text())
    assert report["passed"]
    assert report["case_count"] == 2


def test_cli_release_evidence_and_approval_record(tmp_path: Path) -> None:
    source_manifest = tmp_path / "source.json"
    session_report = tmp_path / "session.json"
    at_rest_report = tmp_path / "at-rest.json"
    ocr_report = tmp_path / "ocr.json"
    action_report = tmp_path / "action.json"
    native_pointer_report = tmp_path / "native-pointer.json"
    incident_json = tmp_path / "incident.json"
    sdist = tmp_path / "package.tar.gz"
    wheel = tmp_path / "package.whl"
    source_manifest.write_text(
        json.dumps({"entry_count": 1, "entries_sha256": "source-hash"}),
        encoding="utf-8",
    )
    session_report.write_text(
        json.dumps({"session_count": 1, "action_count": 1, "event_count": 4}),
        encoding="utf-8",
    )
    at_rest_report.write_text(
        json.dumps(
            {
                "real_site_capture": {
                    "blocked": True,
                    "blocked_reasons": ["real-site capture is disabled by configuration"],
                }
            }
        ),
        encoding="utf-8",
    )
    ocr_report.write_text(json.dumps({"passed": True}), encoding="utf-8")
    action_report.write_text(
        json.dumps({"verified_cases": 5, "expected_failure_cases": 5}),
        encoding="utf-8",
    )
    native_pointer_report.write_text(
        json.dumps({"trials": 100, "verified": 100, "success_rate": 1.0}),
        encoding="utf-8",
    )
    incident_json.write_text(
        json.dumps(
            {
                "evidence_manifest": {
                    "manifest_sha256": "incident-hash",
                    "counts": {"failed_actions": 1},
                }
            }
        ),
        encoding="utf-8",
    )
    sdist.write_bytes(b"sdist")
    wheel.write_bytes(b"wheel")
    candidate = tmp_path / "release-candidate.json"
    assert (
        main(
            [
                "release",
                "evidence",
                "--source-manifest",
                str(source_manifest),
                "--session-report",
                str(session_report),
                "--at-rest-report",
                str(at_rest_report),
                "--ocr-report",
                str(ocr_report),
                "--action-report",
                str(action_report),
                "--native-pointer-report",
                str(native_pointer_report),
                "--incident-json",
                str(incident_json),
                "--sdist",
                str(sdist),
                "--wheel",
                str(wheel),
                "--output",
                str(candidate),
            ]
        )
        == 0
    )
    candidate_payload = json.loads(candidate.read_text())
    assert not candidate_payload["release_ready"]
    assert candidate_payload["candidate_sha256"]
    candidate_file_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    approval = tmp_path / "release-approval.json"
    assert (
        main(
            [
                "release",
                "approve",
                "--candidate",
                str(candidate),
                "--expected-sha256",
                candidate_file_hash,
                "--approver",
                "test-user",
                "--output",
                str(approval),
                "--confirm",
                "APPROVE-RELEASE",
            ]
        )
        == 0
    )
    approval_payload = json.loads(approval.read_text())
    assert approval_payload["candidate_file_sha256"] == candidate_file_hash
    assert approval.stat().st_mode & 0o777 == 0o600


def test_cli_static_portfolio_export(tmp_path: Path) -> None:
    snapshot = tmp_path / "portfolio-public.sqlite"
    with sqlite3.connect(snapshot) as connection:
        connection.executescript(
            """
            CREATE TABLE publication (
                publication_version_id TEXT PRIMARY KEY,
                version_number INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                manifest_sha256 TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                asset_count INTEGER NOT NULL
            ) STRICT;
            CREATE TABLE portfolio_items (
                slug TEXT PRIMARY KEY,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                body TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                item_sha256 TEXT NOT NULL
            ) WITHOUT ROWID, STRICT;
            CREATE TABLE portfolio_assets (
                item_slug TEXT NOT NULL REFERENCES portfolio_items(slug),
                public_relative_path TEXT NOT NULL,
                media_type TEXT NOT NULL,
                asset_sha256 TEXT NOT NULL,
                byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
                source_label TEXT NOT NULL,
                PRIMARY KEY (item_slug, public_relative_path)
            ) WITHOUT ROWID, STRICT;
            INSERT INTO publication VALUES ('pub', 1, '2026-08-31T00:00:00+00:00', 'sha', 1, 0);
            INSERT INTO portfolio_items VALUES (
                'cli-export', 'project', 'CLI Export', 'CLI summary', 'CLI body',
                '2026-08-31T00:00:00+00:00', 'item-sha'
            );
            """
        )
    output = tmp_path / "static"
    assert (
        main(
            [
                "portfolio",
                "export",
                "--config",
                str(ROOT / "config" / "default.toml"),
                "--snapshot",
                str(snapshot),
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    assert (output / "index.html").is_file()
    assert (output / "items" / "cli-export" / "index.html").is_file()
    assert (output / "static-export-manifest.json").is_file()
