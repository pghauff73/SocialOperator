from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APPROVE_RELEASE_CONFIRMATION = "APPROVE-RELEASE"


def write_release_evidence(
    *,
    output_path: str | Path,
    source_manifest: str | Path,
    session_report: str | Path,
    at_rest_report: str | Path,
    ocr_report: str | Path,
    action_report: str | Path,
    native_pointer_report: str | Path,
    incident_json: str | Path,
    sdist: str | Path,
    wheel: str | Path,
) -> Path:
    output = Path(output_path).expanduser().resolve()
    payload = build_release_evidence(
        source_manifest=source_manifest,
        session_report=session_report,
        at_rest_report=at_rest_report,
        ocr_report=ocr_report,
        action_report=action_report,
        native_pointer_report=native_pointer_report,
        incident_json=incident_json,
        sdist=sdist,
        wheel=wheel,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def build_release_evidence(
    *,
    source_manifest: str | Path,
    session_report: str | Path,
    at_rest_report: str | Path,
    ocr_report: str | Path,
    action_report: str | Path,
    native_pointer_report: str | Path,
    incident_json: str | Path,
    sdist: str | Path,
    wheel: str | Path,
) -> dict[str, Any]:
    artifacts = {
        "source_manifest": _file_artifact(source_manifest),
        "session_report": _file_artifact(session_report),
        "at_rest_report": _file_artifact(at_rest_report),
        "ocr_report": _file_artifact(ocr_report),
        "action_report": _file_artifact(action_report),
        "native_pointer_report": _file_artifact(native_pointer_report),
        "incident_json": _file_artifact(incident_json),
        "sdist": _file_artifact(sdist),
        "wheel": _file_artifact(wheel),
    }
    reports = {
        "source_manifest": _read_json_report(source_manifest),
        "session_report": _read_json_report(session_report),
        "at_rest_report": _read_json_report(at_rest_report),
        "ocr_report": _read_json_report(ocr_report),
        "action_report": _read_json_report(action_report),
        "native_pointer_report": _read_json_report(native_pointer_report),
        "incident_json": _read_json_report(incident_json),
    }
    blockers = _release_blockers(artifacts, reports)
    payload: dict[str, Any] = {
        "schema": "socialoperator.release_evidence.v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "artifacts": artifacts,
        "report_summaries": {
            "source_entry_count": reports["source_manifest"].get("entry_count"),
            "source_entries_sha256": reports["source_manifest"].get("entries_sha256"),
            "session_count": reports["session_report"].get("session_count"),
            "action_count": reports["session_report"].get("action_count"),
            "event_count": reports["session_report"].get("event_count"),
            "at_rest_blocked": reports["at_rest_report"]
            .get("real_site_capture", {})
            .get("blocked"),
            "ocr_passed": reports["ocr_report"].get("passed"),
            "action_verified_cases": reports["action_report"].get("verified_cases"),
            "action_expected_failure_cases": reports["action_report"].get("expected_failure_cases"),
            "native_pointer_trials": reports["native_pointer_report"].get("trials"),
            "native_pointer_verified": reports["native_pointer_report"].get("verified"),
            "native_pointer_success_rate": reports["native_pointer_report"].get("success_rate"),
            "incident_manifest_sha256": reports["incident_json"]
            .get("evidence_manifest", {})
            .get("manifest_sha256"),
        },
        "release_ready": not blockers,
        "blockers": blockers,
    }
    payload["candidate_sha256"] = _sha256_json(payload)
    return payload


def write_release_approval_record(
    *,
    candidate_path: str | Path,
    expected_sha256: str,
    approver: str,
    output_path: str | Path,
    confirmation: str,
) -> Path:
    if confirmation != APPROVE_RELEASE_CONFIRMATION:
        raise ValueError(f"confirmation must be {APPROVE_RELEASE_CONFIRMATION}")
    candidate = Path(candidate_path).expanduser().resolve()
    actual_sha256 = _sha256_bytes(candidate.read_bytes())
    if actual_sha256 != expected_sha256:
        raise ValueError("candidate file hash does not match expected hash")
    candidate_payload = json.loads(candidate.read_text(encoding="utf-8"))
    candidate_payload_hash = str(candidate_payload.get("candidate_sha256", ""))
    if not candidate_payload_hash:
        raise ValueError("candidate evidence is missing candidate_sha256")
    record = {
        "schema": "socialoperator.release_approval.v1",
        "approved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "approver": approver,
        "candidate_path": str(candidate),
        "candidate_file_sha256": actual_sha256,
        "candidate_sha256": candidate_payload_hash,
        "release_ready": bool(candidate_payload.get("release_ready")),
        "blockers_at_approval": candidate_payload.get("blockers", ()),
    }
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.chmod(0o600)
    return output


def _release_blockers(
    artifacts: dict[str, dict[str, Any]],
    reports: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    blockers: list[str] = []
    missing_artifacts = tuple(
        name for name, artifact in artifacts.items() if not artifact["exists"]
    )
    if missing_artifacts:
        blockers.append(f"missing artifacts: {', '.join(missing_artifacts)}")
    at_rest = reports["at_rest_report"].get("real_site_capture", {})
    if at_rest.get("blocked"):
        reasons = ", ".join(str(reason) for reason in at_rest.get("blocked_reasons", ()))
        blockers.append(f"real-site capture blocked: {reasons}")
    if reports["ocr_report"].get("passed") is False:
        blockers.append("OCR golden report failed")
    native_pointer = reports["native_pointer_report"]
    if native_pointer and float(native_pointer.get("success_rate", 0.0)) < 1.0:
        blockers.append("native pointer report did not reach 100% success")
    action_report = reports["action_report"]
    if action_report and int(action_report.get("expected_failure_cases", 0)) < 1:
        blockers.append("action fixture lacks expected-failure evidence")
    incident_counts = reports["incident_json"].get("evidence_manifest", {}).get("counts", {})
    if incident_counts and int(incident_counts.get("failed_actions", 0)) < 1:
        blockers.append("incident drill lacks failed-action evidence")
    return tuple(blockers)


def _file_artifact(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        return {
            "path": str(resolved),
            "exists": False,
            "byte_length": 0,
            "sha256": None,
        }
    data = resolved.read_bytes()
    return {
        "path": str(resolved),
        "exists": True,
        "byte_length": len(data),
        "sha256": _sha256_bytes(data),
    }


def _read_json_report(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        return {}
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"release evidence report is not a JSON object: {resolved}")
    return payload


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
