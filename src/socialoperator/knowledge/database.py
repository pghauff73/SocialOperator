from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from socialoperator.knowledge.migrations import LATEST_SCHEMA_VERSION, MIGRATIONS
from socialoperator.types import OperatorState


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def canonical_json(value: Mapping[str, Any] | None = None) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Database:
    def __init__(self, path: str | Path, *, file_mode: int = 0o600) -> None:
        self.path = Path(path).expanduser().resolve()
        self.file_mode = file_mode

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if self.path.exists():
            self.path.chmod(self.file_mode)

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    applied_at TEXT NOT NULL
                ) STRICT
                """
            )
            applied = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for migration in MIGRATIONS:
                if migration.version in applied:
                    continue
                name = migration.name.replace("'", "''")
                applied_at = utc_now().replace("'", "''")
                connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    f"{migration.sql}\n"
                    "INSERT INTO schema_migrations(version, name, applied_at) "
                    f"VALUES ({migration.version}, '{name}', '{applied_at}');\n"
                    "COMMIT;"
                )

    def verify(self) -> dict[str, Any]:
        with self.connect() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
            migration_row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            protected_observations = connection.execute(
                "SELECT COUNT(*) FROM observations WHERE retention_protected = 1"
            ).fetchone()[0]
            fts_rows = connection.execute("SELECT COUNT(*) FROM observations_fts").fetchone()[0]
            return {
                "path": str(self.path),
                "integrity": integrity,
                "foreign_key_errors": len(foreign_key_rows),
                "schema_version": int(migration_row["version"]),
                "latest_schema_version": LATEST_SCHEMA_VERSION,
                "protected_observations": int(protected_observations),
                "observation_fts_rows": int(fts_rows),
                "ok": (
                    integrity == "ok"
                    and not foreign_key_rows
                    and int(migration_row["version"]) == LATEST_SCHEMA_VERSION
                ),
            }

    def create_session(self, metadata: Mapping[str, Any] | None = None) -> str:
        session_id = str(uuid4())
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO operator_sessions(
                    session_id, status, started_at, updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, OperatorState.STARTING.value, now, now, canonical_json(metadata)),
            )
        return session_id

    def transition_session(
        self,
        session_id: str,
        state: OperatorState,
        *,
        ended: bool = False,
        last_verified_action_id: str | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE operator_sessions
                SET status = ?, updated_at = ?, ended_at = ?,
                    last_verified_action_id = COALESCE(?, last_verified_action_id)
                WHERE session_id = ?
                """,
                (state.value, now, now if ended else None, last_verified_action_id, session_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown session: {session_id}")

    def recover_stale_sessions(self) -> list[str]:
        terminal = {
            OperatorState.STOPPED.value,
            OperatorState.HALTED.value,
            OperatorState.PAUSED.value,
            OperatorState.PAUSED_RECOVERY.value,
        }
        placeholders = ",".join("?" for _ in terminal)
        now = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT session_id FROM operator_sessions WHERE status NOT IN ({placeholders})",
                tuple(sorted(terminal)),
            ).fetchall()
            session_ids = [str(row["session_id"]) for row in rows]
            if session_ids:
                connection.executemany(
                    "UPDATE operator_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
                    [
                        (OperatorState.PAUSED_RECOVERY.value, now, session_id)
                        for session_id in session_ids
                    ],
                )
        return session_ids

    def append_audit_event(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        session_id: str | None = None,
    ) -> str:
        event_id = str(uuid4())
        created_at = utc_now()
        payload_json = canonical_json(payload)
        with self.connect() as connection:
            previous = connection.execute(
                "SELECT event_sha256 FROM audit_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            previous_sha = str(previous["event_sha256"]) if previous else None
            digest_input = canonical_json(
                {
                    "audit_event_id": event_id,
                    "session_id": session_id,
                    "event_type": event_type,
                    "created_at": created_at,
                    "payload": json.loads(payload_json),
                    "previous_event_sha256": previous_sha,
                }
            ).encode()
            event_sha = hashlib.sha256(digest_input).hexdigest()
            connection.execute(
                """
                INSERT INTO audit_events(
                    audit_event_id, session_id, event_type, created_at, payload_json,
                    previous_event_sha256, event_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    event_type,
                    created_at,
                    payload_json,
                    previous_sha,
                    event_sha,
                ),
            )
        return event_id

    def add_observation(
        self,
        *,
        observation_kind: str,
        raw_text: str,
        normalized_text: str,
        source_page_id: str | None = None,
        capture_artifact_id: str | None = None,
        bbox: Mapping[str, Any] | None = None,
        confidence: float | None = None,
        retention_protected: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        observation_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO observations(
                    observation_id, source_page_id, capture_artifact_id, observation_kind,
                    raw_text, normalized_text, bbox_json, confidence, observed_at,
                    retention_protected, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_id,
                    source_page_id,
                    capture_artifact_id,
                    observation_kind,
                    raw_text,
                    normalized_text,
                    canonical_json(bbox),
                    confidence,
                    utc_now(),
                    int(retention_protected),
                    canonical_json(metadata),
                ),
            )
            connection.execute(
                """
                INSERT INTO observations_fts(observation_id, raw_text, normalized_text)
                VALUES (?, ?, ?)
                """,
                (observation_id, raw_text, normalized_text),
            )
        return observation_id

    def record_browser_action(
        self,
        *,
        action_id: str,
        session_id: str,
        risk_level: str,
        action_type: str,
        expected_postcondition: Mapping[str, Any],
        before_state_sha256: str,
        result: str,
        target_id: str | None = None,
        after_state_sha256: str | None = None,
        approval_id: str | None = None,
        failure_reason: str | None = None,
        verified: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO browser_actions(
                    action_id, session_id, target_id, risk_level, action_type,
                    expected_postcondition_json, before_state_sha256, after_state_sha256,
                    approval_id, result, failure_reason, created_at, verified_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    session_id,
                    target_id,
                    risk_level,
                    action_type,
                    canonical_json(expected_postcondition),
                    before_state_sha256,
                    after_state_sha256,
                    approval_id,
                    result,
                    failure_reason,
                    now,
                    now if verified else None,
                    canonical_json(metadata),
                ),
            )

    def create_incident(
        self,
        *,
        severity: str,
        summary: str,
        session_id: str | None = None,
        evidence_manifest: Mapping[str, Any] | None = None,
        incident_id: str | None = None,
    ) -> str:
        if not severity.strip():
            raise ValueError("incident severity must not be empty")
        if not summary.strip():
            raise ValueError("incident summary must not be empty")
        incident_id = incident_id or str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO incidents(
                    incident_id, session_id, severity, summary, created_at,
                    evidence_manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    incident_id,
                    session_id,
                    severity,
                    summary,
                    utc_now(),
                    canonical_json(evidence_manifest),
                ),
            )
        return incident_id

    def resolve_incident(self, incident_id: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE incidents
                SET resolved_at = ?
                WHERE incident_id = ? AND resolved_at IS NULL
                """,
                (utc_now(), incident_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown unresolved incident: {incident_id}")

    def incident_report(self, incident_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT incident_id, session_id, severity, summary, created_at, resolved_at,
                       evidence_manifest_json
                FROM incidents WHERE incident_id = ?
                """,
                (incident_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown incident: {incident_id}")
        report = dict(row)
        report["evidence_manifest"] = json.loads(str(report.pop("evidence_manifest_json")))
        return report

    def request_control(
        self,
        *,
        session_id: str,
        command: str,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if command not in {"pause", "resume", "stop"}:
            raise ValueError(f"unsupported control command: {command}")
        if not reason.strip():
            raise ValueError("control reason must not be empty")
        request_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO operator_control_requests(
                    control_request_id, session_id, command, reason, status,
                    requested_at, metadata_json
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    request_id,
                    session_id,
                    command,
                    reason,
                    utc_now(),
                    canonical_json(metadata),
                ),
            )
        return request_id

    def next_control_request(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT control_request_id, session_id, command, reason, status,
                       requested_at, acknowledged_at, metadata_json
                FROM operator_control_requests
                WHERE session_id = ? AND status = 'pending'
                ORDER BY requested_at, control_request_id
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        request = dict(row)
        request["metadata"] = json.loads(str(request.pop("metadata_json")))
        return request

    def acknowledge_control_request(
        self,
        control_request_id: str,
        *,
        status: str = "acknowledged",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if status not in {"acknowledged", "rejected"}:
            raise ValueError("control acknowledgement status must be acknowledged or rejected")
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE operator_control_requests
                SET status = ?, acknowledged_at = ?, metadata_json = ?
                WHERE control_request_id = ? AND status = 'pending'
                """,
                (status, utc_now(), canonical_json(metadata), control_request_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown pending control request: {control_request_id}")

    def control_report(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        filters = []
        values: list[str] = []
        if session_id is not None:
            filters.append("session_id = ?")
            values.append(session_id)
        if status is not None:
            filters.append("status = ?")
            values.append(status)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT control_request_id, session_id, command, reason, status,
                       requested_at, acknowledged_at, metadata_json
                FROM operator_control_requests
                {where}
                ORDER BY requested_at, control_request_id
                """,
                values,
            ).fetchall()
        requests = []
        for row in rows:
            request = dict(row)
            request["metadata"] = json.loads(str(request.pop("metadata_json")))
            requests.append(request)
        return {
            "database": self.path.name,
            "session_filter": session_id,
            "status_filter": status,
            "request_count": len(requests),
            "requests": requests,
        }

    def create_site_scope_approval(
        self,
        *,
        site_id: str,
        policy_sha256: str,
        approved_by: str,
        scope_summary: str,
        expires_at: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if not site_id.strip():
            raise ValueError("site_id cannot be empty")
        if len(policy_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in policy_sha256
        ):
            raise ValueError("policy_sha256 must be a lowercase SHA-256 hex digest")
        if not approved_by.strip():
            raise ValueError("approved_by cannot be empty")
        if not scope_summary.strip():
            raise ValueError("scope_summary cannot be empty")
        approval_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO site_scope_approvals(
                    site_scope_approval_id, site_id, policy_sha256, approved_by,
                    approved_at, expires_at, status, scope_summary, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    approval_id,
                    site_id,
                    policy_sha256,
                    approved_by,
                    utc_now(),
                    expires_at,
                    scope_summary,
                    canonical_json(metadata),
                ),
            )
        return approval_id

    def active_site_scope_approval(
        self,
        *,
        site_id: str,
        policy_sha256: str,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM site_scope_approvals
                WHERE site_id = ?
                  AND policy_sha256 = ?
                  AND status = 'active'
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY approved_at DESC, site_scope_approval_id DESC
                LIMIT 1
                """,
                (site_id, policy_sha256, now),
            ).fetchone()
        if row is None:
            return None
        approval = dict(row)
        approval["metadata"] = json.loads(str(approval.pop("metadata_json")))
        return approval

    def revoke_site_scope_approval(self, approval_id: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE site_scope_approvals
                SET status = 'revoked'
                WHERE site_scope_approval_id = ?
                """,
                (approval_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown site scope approval: {approval_id}")

    def site_scope_report(
        self,
        *,
        site_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[str] = []
        if site_id is not None:
            clauses.append("site_id = ?")
            params.append(site_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM site_scope_approvals
                {where}
                ORDER BY approved_at DESC, site_id, site_scope_approval_id
                """,
                params,
            ).fetchall()
        approvals = []
        for row in rows:
            approval = dict(row)
            approval["metadata"] = json.loads(str(approval.pop("metadata_json")))
            approvals.append(approval)
        return {
            "database": self.path.name,
            "site_filter": site_id,
            "status_filter": status,
            "approval_count": len(approvals),
            "approvals": approvals,
        }

    def create_at_rest_acceptance(
        self,
        *,
        accepted_by: str,
        evidence_summary: str,
        expires_at: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        if not accepted_by.strip():
            raise ValueError("accepted_by cannot be empty")
        if not evidence_summary.strip():
            raise ValueError("evidence_summary cannot be empty")
        acceptance_id = str(uuid4())
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO at_rest_acceptances(
                    at_rest_acceptance_id, protection_kind, accepted_by,
                    accepted_at, expires_at, status, evidence_summary, metadata_json
                ) VALUES (?, 'full_disk_encryption', ?, ?, ?, 'active', ?, ?)
                """,
                (
                    acceptance_id,
                    accepted_by,
                    utc_now(),
                    expires_at,
                    evidence_summary,
                    canonical_json(metadata),
                ),
            )
        return acceptance_id

    def active_at_rest_acceptance(self) -> dict[str, Any] | None:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM at_rest_acceptances
                WHERE protection_kind = 'full_disk_encryption'
                  AND status = 'active'
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY accepted_at DESC, at_rest_acceptance_id DESC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
        if row is None:
            return None
        acceptance = dict(row)
        acceptance["metadata"] = json.loads(str(acceptance.pop("metadata_json")))
        return acceptance

    def revoke_at_rest_acceptance(self, acceptance_id: str) -> None:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE at_rest_acceptances
                SET status = 'revoked'
                WHERE at_rest_acceptance_id = ?
                """,
                (acceptance_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown at-rest acceptance: {acceptance_id}")

    def at_rest_acceptance_report(self, *, status: str | None = None) -> dict[str, Any]:
        where = "WHERE status = ?" if status is not None else ""
        params = (status,) if status is not None else ()
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM at_rest_acceptances
                {where}
                ORDER BY accepted_at DESC, at_rest_acceptance_id
                """,
                params,
            ).fetchall()
        acceptances = []
        for row in rows:
            acceptance = dict(row)
            acceptance["metadata"] = json.loads(str(acceptance.pop("metadata_json")))
            acceptances.append(acceptance)
        return {
            "database": self.path.name,
            "status_filter": status,
            "acceptance_count": len(acceptances),
            "acceptances": acceptances,
        }

    def search_observations(self, query: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT o.*
                FROM observations_fts f
                JOIN observations o ON o.observation_id = f.observation_id
                WHERE observations_fts MATCH ?
                ORDER BY rank
                """,
                (query,),
            ).fetchall()

    def prune_observations_before(self, cutoff: str) -> int:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT observation_id FROM observations
                WHERE observed_at < ? AND retention_protected = 0
                """,
                (cutoff,),
            ).fetchall()
            ids = [str(row["observation_id"]) for row in rows]
            if ids:
                connection.executemany(
                    "DELETE FROM observations_fts WHERE observation_id = ?",
                    [(observation_id,) for observation_id in ids],
                )
                connection.executemany(
                    "DELETE FROM observations WHERE observation_id = ?",
                    [(observation_id,) for observation_id in ids],
                )
        return len(ids)

    def backup(self, destination: str | Path) -> Path:
        destination_path = Path(destination).expanduser().resolve()
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, sqlite3.connect(destination_path) as target:
            source.backup(target)
        destination_path.chmod(self.file_mode)
        return destination_path

    def session_report(self, session_id: str | None = None) -> dict[str, Any]:
        with self.connect() as connection:
            if session_id is None:
                sessions = connection.execute(
                    """
                    SELECT session_id, status, started_at, updated_at, ended_at,
                           last_verified_action_id
                    FROM operator_sessions ORDER BY started_at, session_id
                    """
                ).fetchall()
                actions = connection.execute(
                    """
                    SELECT action_id, session_id, risk_level, action_type, result,
                           created_at, verified_at, before_state_sha256, after_state_sha256
                    FROM browser_actions ORDER BY created_at, action_id
                    """
                ).fetchall()
                events = connection.execute(
                    """
                    SELECT audit_event_id, session_id, event_type, created_at,
                           previous_event_sha256, event_sha256
                    FROM audit_events ORDER BY rowid
                    """
                ).fetchall()
            else:
                sessions = connection.execute(
                    """
                    SELECT session_id, status, started_at, updated_at, ended_at,
                           last_verified_action_id
                    FROM operator_sessions WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchall()
                actions = connection.execute(
                    """
                    SELECT action_id, session_id, risk_level, action_type, result,
                           created_at, verified_at, before_state_sha256, after_state_sha256
                    FROM browser_actions WHERE session_id = ? ORDER BY created_at, action_id
                    """,
                    (session_id,),
                ).fetchall()
                events = connection.execute(
                    """
                    SELECT audit_event_id, session_id, event_type, created_at,
                           previous_event_sha256, event_sha256
                    FROM audit_events WHERE session_id = ? ORDER BY rowid
                    """,
                    (session_id,),
                ).fetchall()
            return {
                "database": self.path.name,
                "session_filter": session_id,
                "session_count": len(sessions),
                "action_count": len(actions),
                "event_count": len(events),
                "sessions": [dict(row) for row in sessions],
                "actions": [dict(row) for row in actions],
                "events": [dict(row) for row in events],
            }

    @staticmethod
    def verify_external(path: str | Path) -> None:
        external_path = Path(path).expanduser().resolve()
        with sqlite3.connect(external_path) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise ValueError(f"invalid SQLite database: {external_path}")

    def restore(self, backup_path: str | Path) -> None:
        source = Path(backup_path).expanduser().resolve()
        self.verify_external(source)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".restore.tmp")
        shutil.copy2(source, temporary)
        temporary.chmod(self.file_mode)
        temporary.replace(self.path)
        for suffix in ("-wal", "-shm"):
            self.path.with_name(self.path.name + suffix).unlink(missing_ok=True)

    def delete(self) -> None:
        for path in (
            self.path,
            self.path.with_name(self.path.name + "-wal"),
            self.path.with_name(self.path.name + "-shm"),
        ):
            path.unlink(missing_ok=True)


def copy_database(source: str | Path, destination: str | Path) -> Path:
    source_path = Path(source).expanduser().resolve()
    Database.verify_external(source_path)
    destination_path = Path(destination).expanduser().resolve()
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)
    destination_path.chmod(0o600)
    return destination_path
