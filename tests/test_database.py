import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from socialoperator.audit.sessions import SessionManager, recover_sessions
from socialoperator.capture.artifacts import ArtifactStore
from socialoperator.config import load_site_policy, site_policy_sha256
from socialoperator.knowledge.database import Database
from socialoperator.types import OperatorState, Sensitivity

ROOT = Path(__file__).resolve().parents[1]


def test_database_initialize_search_prune_and_verify(tmp_path: Path) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    removable = database.add_observation(
        observation_kind="ocr",
        raw_text="Synthetic profile project",
        normalized_text="synthetic profile project",
    )
    protected = database.add_observation(
        observation_kind="review",
        raw_text="Approved synthetic project",
        normalized_text="approved synthetic project",
        retention_protected=True,
    )
    matches = database.search_observations("profile")
    assert [row["observation_id"] for row in matches] == [removable]
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert database.prune_observations_before(future) == 1
    with database.connect() as connection:
        remaining = connection.execute(
            "SELECT observation_id FROM observations ORDER BY observation_id"
        ).fetchall()
    assert [row["observation_id"] for row in remaining] == [protected]
    report = database.verify()
    assert report["ok"]
    assert report["protected_observations"] == 1


def test_database_backup_restore_and_delete(tmp_path: Path) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    database.add_observation(
        observation_kind="dom",
        raw_text="Backup evidence",
        normalized_text="backup evidence",
    )
    backup = database.backup(tmp_path / "backup.sqlite")
    database.delete()
    assert not database.path.exists()
    database.restore(backup)
    assert database.verify()["ok"]
    assert len(database.search_observations("backup")) == 1


def test_database_incident_records_manifest_and_resolution(tmp_path: Path) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    manager = SessionManager(database)
    session_id = manager.start({"incident": True})
    incident_id = database.create_incident(
        session_id=session_id,
        severity="warning",
        summary="Synthetic incident",
        evidence_manifest={"action_ids": ["a1"], "manifest_sha256": "abc"},
    )
    report = database.incident_report(incident_id)
    assert report["session_id"] == session_id
    assert report["severity"] == "warning"
    assert report["summary"] == "Synthetic incident"
    assert report["resolved_at"] is None
    assert report["evidence_manifest"]["action_ids"] == ["a1"]
    database.resolve_incident(incident_id)
    assert database.incident_report(incident_id)["resolved_at"] is not None


def test_database_control_request_queue(tmp_path: Path) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    manager = SessionManager(database)
    session_id = manager.start({"control": True})
    request_id = database.request_control(
        session_id=session_id,
        command="pause",
        reason="operator requested pause",
    )
    pending = database.next_control_request(session_id)
    assert pending is not None
    assert pending["control_request_id"] == request_id
    assert pending["command"] == "pause"
    database.acknowledge_control_request(request_id, metadata={"applied_state": "PAUSED"})
    assert database.next_control_request(session_id) is None
    report = database.control_report(session_id=session_id, status="acknowledged")
    assert report["request_count"] == 1
    assert report["requests"][0]["metadata"]["applied_state"] == "PAUSED"


def test_site_scope_approval_requires_exact_policy_hash_and_can_revoke(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    policy = load_site_policy(ROOT / "config" / "sites" / "real_site.example.toml")
    policy_hash = site_policy_sha256(policy)
    approval_id = database.create_site_scope_approval(
        site_id=policy.site_id,
        policy_sha256=policy_hash,
        approved_by="test-user",
        scope_summary="Synthetic approval for example real-site scope.",
    )
    approval = database.active_site_scope_approval(
        site_id=policy.site_id,
        policy_sha256=policy_hash,
    )

    assert approval is not None
    assert approval["site_scope_approval_id"] == approval_id
    assert approval["approved_by"] == "test-user"
    report = database.site_scope_report(site_id=policy.site_id, status="active")
    assert report["approval_count"] == 1
    database.revoke_site_scope_approval(approval_id)
    assert (
        database.active_site_scope_approval(
            site_id=policy.site_id,
            policy_sha256=policy_hash,
        )
        is None
    )


def test_at_rest_acceptance_can_be_reported_and_revoked(tmp_path: Path) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    acceptance_id = database.create_at_rest_acceptance(
        accepted_by="test-user",
        evidence_summary="Synthetic full-disk encryption acceptance.",
    )
    active = database.active_at_rest_acceptance()

    assert active is not None
    assert active["at_rest_acceptance_id"] == acceptance_id
    assert active["accepted_by"] == "test-user"
    report = database.at_rest_acceptance_report(status="active")
    assert report["acceptance_count"] == 1
    database.revoke_at_rest_acceptance(acceptance_id)
    assert database.active_at_rest_acceptance() is None


def test_session_recovery_never_replays_action(tmp_path: Path) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    manager = SessionManager(database)
    session_id = manager.start({"fixture": True})
    manager.transition(OperatorState.OBSERVING)
    assert recover_sessions(database) == [session_id]
    with database.connect() as connection:
        row = connection.execute(
            "SELECT status, last_verified_action_id FROM operator_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        event = connection.execute(
            "SELECT payload_json FROM audit_events WHERE event_type = 'SESSION_RECOVERED_PAUSED'"
        ).fetchone()
    assert row["status"] == OperatorState.PAUSED_RECOVERY.value
    assert row["last_verified_action_id"] is None
    assert '"action_replayed":false' in event["payload_json"]


def test_session_recovery_kill_point_matrix(tmp_path: Path) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    terminal = {
        OperatorState.STOPPED,
        OperatorState.HALTED,
        OperatorState.PAUSED,
        OperatorState.PAUSED_RECOVERY,
    }
    sessions: dict[OperatorState, str] = {}
    for state in OperatorState:
        manager = SessionManager(database)
        session_id = manager.start({"kill_point": state.value})
        sessions[state] = session_id
        if state is not OperatorState.STARTING:
            manager.transition(
                state,
                ended=state in {OperatorState.STOPPED, OperatorState.HALTED},
                last_verified_action_id=f"last-verified-{state.value}",
            )

    recovered = set(recover_sessions(database))
    expected = {session_id for state, session_id in sessions.items() if state not in terminal}
    assert recovered == expected
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT session_id, status, last_verified_action_id FROM operator_sessions"
        ).fetchall()
        actions = int(connection.execute("SELECT COUNT(*) FROM browser_actions").fetchone()[0])
        recovery_events = connection.execute(
            "SELECT payload_json FROM audit_events WHERE event_type = 'SESSION_RECOVERED_PAUSED'"
        ).fetchall()
    status_by_id = {row["session_id"]: row["status"] for row in rows}
    last_action_by_id = {row["session_id"]: row["last_verified_action_id"] for row in rows}
    for state, session_id in sessions.items():
        if state in terminal:
            assert status_by_id[session_id] == state.value
        else:
            assert status_by_id[session_id] == OperatorState.PAUSED_RECOVERY.value
        if state is OperatorState.STARTING:
            assert last_action_by_id[session_id] is None
        else:
            assert last_action_by_id[session_id] == f"last-verified-{state.value}"
    assert actions == 0
    assert len(recovery_events) == len(expected)
    assert all('"action_replayed":false' in row["payload_json"] for row in recovery_events)


def test_artifact_store_is_content_addressed_and_immutable(tmp_path: Path) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    store = ArtifactStore(tmp_path / "artifacts", database)
    first = store.put_bytes(
        b"synthetic screenshot bytes",
        media_type="image/png",
        sensitivity=Sensitivity.PRIVATE,
    )
    second = store.put_bytes(
        b"synthetic screenshot bytes",
        media_type="image/png",
        sensitivity=Sensitivity.PRIVATE,
    )
    assert first.artifact_id == second.artifact_id
    assert first.path.read_bytes() == b"synthetic screenshot bytes"
    assert store.verify()["ok"]


def test_foreign_keys_are_enabled(tmp_path: Path) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    with database.connect() as connection:
        try:
            connection.execute(
                """
                INSERT INTO claim_evidence(
                    claim_evidence_id, claim_id, observation_id, evidence_role
                ) VALUES ('bad', 'missing-claim', 'missing-observation', 'support')
                """
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("foreign key violation was accepted")
