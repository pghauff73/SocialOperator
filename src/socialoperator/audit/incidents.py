from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from socialoperator.audit.sessions import SessionManager
from socialoperator.knowledge.database import Database, canonical_json, utc_now
from socialoperator.types import ActionRisk, OperatorState


@dataclass(frozen=True, slots=True)
class IncidentBundleResult:
    incident_id: str
    output_dir: Path
    json_path: Path
    markdown_path: Path
    manifest_sha256: str
    json_sha256: str
    markdown_sha256: str


@dataclass(frozen=True, slots=True)
class IncidentDrillResult:
    incident_id: str
    session_id: str
    output_dir: Path
    json_path: Path
    markdown_path: Path
    manifest_sha256: str
    passed: bool
    checks: dict[str, bool]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _session_row(database: Database, session_id: str) -> dict[str, Any]:
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT session_id, status, started_at, updated_at, ended_at,
                   last_verified_action_id, metadata_json
            FROM operator_sessions WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"unknown session: {session_id}")
    session = dict(row)
    session["metadata_sha256"] = _sha256_text(str(session.pop("metadata_json")))
    return session


def build_incident_evidence_manifest(database: Database, *, session_id: str) -> dict[str, Any]:
    session = _session_row(database, session_id)
    with database.connect() as connection:
        action_rows = connection.execute(
            """
            SELECT action_id, risk_level, action_type, result, failure_reason,
                   created_at, verified_at, before_state_sha256, after_state_sha256,
                   expected_postcondition_json, metadata_json
            FROM browser_actions
            WHERE session_id = ?
            ORDER BY created_at, action_id
            """,
            (session_id,),
        ).fetchall()
        event_rows = connection.execute(
            """
            SELECT audit_event_id, event_type, created_at, previous_event_sha256,
                   event_sha256, payload_json
            FROM audit_events
            WHERE session_id = ?
            ORDER BY rowid
            """,
            (session_id,),
        ).fetchall()
    actions: list[dict[str, Any]] = []
    for row in action_rows:
        action = dict(row)
        action["expected_postcondition"] = json.loads(
            str(action.pop("expected_postcondition_json"))
        )
        action["metadata_sha256"] = _sha256_text(str(action.pop("metadata_json")))
        actions.append(action)
    events: list[dict[str, Any]] = []
    for row in event_rows:
        event = dict(row)
        event["payload_sha256"] = _sha256_text(str(event.pop("payload_json")))
        events.append(event)
    manifest: dict[str, Any] = {
        "schema": "socialoperator.incident_bundle.v1",
        "generated_at": utc_now(),
        "database": database.path.name,
        "session": session,
        "actions": actions,
        "events": events,
        "counts": {
            "actions": len(actions),
            "events": len(events),
            "failed_actions": sum(1 for action in actions if action["result"] != "verified"),
        },
    }
    manifest["manifest_sha256"] = _json_hash(manifest)
    return manifest


def _markdown_table_row(values: tuple[object, ...]) -> str:
    escaped = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
    return "| " + " | ".join(escaped) + " |"


def render_incident_markdown(incident: dict[str, Any], evidence_manifest: dict[str, Any]) -> str:
    session = evidence_manifest["session"]
    lines = [
        "# SocialOperator Incident Bundle",
        "",
        f"- Incident ID: `{incident['incident_id']}`",
        f"- Severity: `{incident['severity']}`",
        f"- Summary: {incident['summary']}",
        f"- Created At: `{incident['created_at']}`",
        f"- Resolved At: `{incident['resolved_at'] or 'unresolved'}`",
        f"- Evidence Manifest SHA-256: `{evidence_manifest['manifest_sha256']}`",
        "",
        "## Session",
        "",
        f"- Session ID: `{session['session_id']}`",
        f"- Status: `{session['status']}`",
        f"- Started At: `{session['started_at']}`",
        f"- Updated At: `{session['updated_at']}`",
        f"- Last Verified Action ID: `{session['last_verified_action_id'] or 'none'}`",
        f"- Session Metadata SHA-256: `{session['metadata_sha256']}`",
        "",
        "## Action Evidence",
        "",
        _markdown_table_row(
            (
                "Created At",
                "Action ID",
                "Type",
                "Risk",
                "Result",
                "Before State",
                "After State",
                "Failure",
            )
        ),
        _markdown_table_row(("---", "---", "---", "---", "---", "---", "---", "---")),
    ]
    for action in evidence_manifest["actions"]:
        lines.append(
            _markdown_table_row(
                (
                    action["created_at"],
                    action["action_id"],
                    action["action_type"],
                    action["risk_level"],
                    action["result"],
                    action["before_state_sha256"],
                    action["after_state_sha256"] or "none",
                    action["failure_reason"] or "",
                )
            )
        )
    if not evidence_manifest["actions"]:
        lines.append("_No browser actions were recorded for this session._")
    lines.extend(
        [
            "",
            "## Audit Chain",
            "",
            _markdown_table_row(
                ("Created At", "Event ID", "Type", "Event SHA-256", "Payload SHA-256")
            ),
            _markdown_table_row(("---", "---", "---", "---", "---")),
        ]
    )
    for event in evidence_manifest["events"]:
        lines.append(
            _markdown_table_row(
                (
                    event["created_at"],
                    event["audit_event_id"],
                    event["event_type"],
                    event["event_sha256"],
                    event["payload_sha256"],
                )
            )
        )
    if not evidence_manifest["events"]:
        lines.append("_No audit events were recorded for this session._")
    lines.append("")
    return "\n".join(lines)


def build_incident_bundle(
    database: Database,
    *,
    output_dir: str | Path,
    session_id: str,
    severity: str,
    summary: str,
    file_mode: int = 0o600,
) -> IncidentBundleResult:
    incident_id = str(uuid4())
    evidence_manifest = build_incident_evidence_manifest(database, session_id=session_id)
    database.create_incident(
        incident_id=incident_id,
        session_id=session_id,
        severity=severity,
        summary=summary,
        evidence_manifest=evidence_manifest,
    )
    incident = database.incident_report(incident_id)
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    output_path.chmod(0o700)
    payload = {
        "incident": incident,
        "evidence_manifest": evidence_manifest,
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    markdown = render_incident_markdown(incident, evidence_manifest)
    json_path = output_path / "incident.json"
    markdown_path = output_path / "incident.md"
    json_path.write_text(encoded, encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.chmod(file_mode)
    markdown_path.chmod(file_mode)
    return IncidentBundleResult(
        incident_id=incident_id,
        output_dir=output_path,
        json_path=json_path,
        markdown_path=markdown_path,
        manifest_sha256=evidence_manifest["manifest_sha256"],
        json_sha256=_sha256_text(encoded),
        markdown_sha256=_sha256_text(markdown),
    )


def run_incident_drill(
    database: Database,
    *,
    output_dir: str | Path,
    severity: str = "warning",
    summary: str = "Synthetic incident drill",
    file_mode: int = 0o600,
) -> IncidentDrillResult:
    session_manager = SessionManager(database)
    session_id = session_manager.start({"drill": "incident", "real_site": False})
    session_manager.transition(OperatorState.READY)
    database.record_browser_action(
        action_id=str(uuid4()),
        session_id=session_id,
        risk_level=ActionRisk.NAVIGATE.value,
        action_type="drill",
        expected_postcondition={"kind": "synthetic_incident_drill"},
        before_state_sha256=_sha256_text("incident-drill-before"),
        result="failed",
        failure_reason="synthetic incident drill failure",
        metadata={"drill": True, "real_site": False},
    )
    database.append_audit_event(
        "INCIDENT_DRILL_FAILURE_INJECTION",
        {"drill": True, "action_replayed": False},
        session_id=session_id,
    )
    session_manager.transition(OperatorState.PAUSED, ended=True)
    bundle = build_incident_bundle(
        database,
        output_dir=output_dir,
        session_id=session_id,
        severity=severity,
        summary=summary,
        file_mode=file_mode,
    )
    payload = json.loads(bundle.json_path.read_text(encoding="utf-8"))
    checks = {
        "json_file_mode": bundle.json_path.stat().st_mode & 0o777 == file_mode,
        "markdown_file_mode": bundle.markdown_path.stat().st_mode & 0o777 == file_mode,
        "directory_mode": bundle.output_dir.stat().st_mode & 0o777 == 0o700,
        "manifest_sha256": payload["evidence_manifest"]["manifest_sha256"]
        == bundle.manifest_sha256,
        "failed_action_count": int(payload["evidence_manifest"]["counts"]["failed_actions"]) >= 1,
        "audit_event_count": int(payload["evidence_manifest"]["counts"]["events"]) >= 4,
    }
    return IncidentDrillResult(
        incident_id=bundle.incident_id,
        session_id=session_id,
        output_dir=bundle.output_dir,
        json_path=bundle.json_path,
        markdown_path=bundle.markdown_path,
        manifest_sha256=bundle.manifest_sha256,
        passed=all(checks.values()),
        checks=checks,
    )
