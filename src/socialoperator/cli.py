from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from socialoperator import __version__
from socialoperator.audit.incidents import build_incident_bundle, run_incident_drill
from socialoperator.config import (
    ensure_runtime_directories,
    load_config,
    load_site_policy,
    site_policy_payload,
    site_policy_sha256,
)
from socialoperator.doctor import run_doctor
from socialoperator.knowledge.database import Database
from socialoperator.knowledge.publication import PublicationBuilder, verify_public_snapshot
from socialoperator.manifest import write_source_manifest
from socialoperator.ocr.golden import write_golden_report
from socialoperator.portfolio.app import create_portfolio_app
from socialoperator.portfolio.export import export_static_site
from socialoperator.release.evidence import write_release_approval_record, write_release_evidence
from socialoperator.review.app import create_review_app
from socialoperator.security.at_rest import at_rest_protection_report


def _add_common_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default="config/default.toml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="socialoperator")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check the local runtime foundation")
    _add_common_config(doctor)

    initialize = subparsers.add_parser("init", help="initialize runtime directories and database")
    _add_common_config(initialize)
    initialize.add_argument("--db")

    kb = subparsers.add_parser("kb", help="manage the private SQLite knowledge base")
    kb_subparsers = kb.add_subparsers(dest="kb_command", required=True)
    for name in ("verify", "backup", "export", "restore", "delete", "prune"):
        command = kb_subparsers.add_parser(name)
        _add_common_config(command)
        command.add_argument("--db")
        if name in {"backup", "export"}:
            command.add_argument("--output", required=True)
        elif name == "restore":
            command.add_argument("--backup", required=True)
        elif name == "delete":
            command.add_argument("--confirm", required=True)
        elif name == "prune":
            command.add_argument("--before", required=True)
            command.add_argument("--confirm", required=True)

    security = subparsers.add_parser("security", help="inspect local security posture")
    security_subparsers = security.add_subparsers(dest="security_command", required=True)
    at_rest = security_subparsers.add_parser("at-rest-report")
    _add_common_config(at_rest)
    at_rest.add_argument("--db")
    at_rest.add_argument("--output")
    accept_full_disk = security_subparsers.add_parser("accept-full-disk")
    _add_common_config(accept_full_disk)
    accept_full_disk.add_argument("--db")
    accept_full_disk.add_argument("--accepted-by", required=True)
    accept_full_disk.add_argument("--summary", required=True)
    accept_full_disk.add_argument("--expires-at")
    accept_full_disk.add_argument("--confirm", required=True)
    acceptance_status = security_subparsers.add_parser("at-rest-acceptance-status")
    _add_common_config(acceptance_status)
    acceptance_status.add_argument("--db")
    acceptance_status.add_argument("--status")
    revoke_acceptance = security_subparsers.add_parser("revoke-at-rest-acceptance")
    _add_common_config(revoke_acceptance)
    revoke_acceptance.add_argument("--db")
    revoke_acceptance.add_argument("--acceptance-id", required=True)

    site = subparsers.add_parser("site", help="inspect and approve site scopes")
    site_subparsers = site.add_subparsers(dest="site_command", required=True)
    site_policy = site_subparsers.add_parser("policy-report")
    site_policy.add_argument("--policy", required=True)
    site_approve = site_subparsers.add_parser("approve-scope")
    _add_common_config(site_approve)
    site_approve.add_argument("--db")
    site_approve.add_argument("--policy", required=True)
    site_approve.add_argument("--approver", required=True)
    site_approve.add_argument("--summary", required=True)
    site_approve.add_argument("--expires-at")
    site_approve.add_argument("--confirm", required=True)
    site_status = site_subparsers.add_parser("scope-status")
    _add_common_config(site_status)
    site_status.add_argument("--db")
    site_status.add_argument("--site-id")
    site_status.add_argument("--status")
    site_revoke = site_subparsers.add_parser("revoke-scope")
    _add_common_config(site_revoke)
    site_revoke.add_argument("--db")
    site_revoke.add_argument("--approval-id", required=True)

    fixture = subparsers.add_parser("fixture", help="serve deterministic local fixture pages")
    fixture_subparsers = fixture.add_subparsers(dest="fixture_command", required=True)
    serve = fixture_subparsers.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--root", default="tests/fixtures/site")

    manifest = subparsers.add_parser("source-manifest", help="hash the current source tree")
    manifest.add_argument("--root", default=".")
    manifest.add_argument("--output", default="reports/source-manifest.json")

    release = subparsers.add_parser("release", help="build release evidence and approvals")
    release_subparsers = release.add_subparsers(dest="release_command", required=True)
    release_evidence = release_subparsers.add_parser("evidence")
    release_evidence.add_argument(
        "--source-manifest", default="reports/current-source-manifest.json"
    )
    release_evidence.add_argument("--session-report", default="reports/current-session-report.json")
    release_evidence.add_argument("--at-rest-report", default="reports/at-rest-report.json")
    release_evidence.add_argument("--ocr-report", default="reports/ocr-golden.json")
    release_evidence.add_argument(
        "--action-report", default="reports/action-postcondition-fixture.json"
    )
    release_evidence.add_argument(
        "--native-pointer-report", default="reports/native-pointer-100-trial.json"
    )
    release_evidence.add_argument(
        "--incident-json", default="reports/incidents/drill/incident.json"
    )
    release_evidence.add_argument("--sdist", default="dist/socialoperator-0.1.0.tar.gz")
    release_evidence.add_argument("--wheel", default="dist/socialoperator-0.1.0-py3-none-any.whl")
    release_evidence.add_argument("--output", default="reports/release-candidate.json")
    release_approve = release_subparsers.add_parser("approve")
    release_approve.add_argument("--candidate", required=True)
    release_approve.add_argument("--expected-sha256", required=True)
    release_approve.add_argument("--approver", required=True)
    release_approve.add_argument("--output", required=True)
    release_approve.add_argument("--confirm", required=True)

    ocr = subparsers.add_parser("ocr", help="evaluate OCR fixture evidence")
    ocr_subparsers = ocr.add_subparsers(dest="ocr_command", required=True)
    ocr_golden = ocr_subparsers.add_parser("golden")
    ocr_golden.add_argument("--corpus", default="tests/fixtures/ocr/golden.json")
    ocr_golden.add_argument("--output", default="reports/ocr-golden.json")

    session = subparsers.add_parser("session", help="inspect recorded operator sessions")
    session_subparsers = session.add_subparsers(dest="session_command", required=True)
    session_report = session_subparsers.add_parser("report")
    _add_common_config(session_report)
    session_report.add_argument("--db")
    session_report.add_argument("--session-id")
    session_report.add_argument("--output")
    for name in ("pause", "resume", "stop"):
        control = session_subparsers.add_parser(name)
        _add_common_config(control)
        control.add_argument("--db")
        control.add_argument("--session-id", required=True)
        control.add_argument("--reason", required=True)
    session_control_status = session_subparsers.add_parser("control-status")
    _add_common_config(session_control_status)
    session_control_status.add_argument("--db")
    session_control_status.add_argument("--session-id")
    session_control_status.add_argument("--status")
    session_incident = session_subparsers.add_parser("incident")
    _add_common_config(session_incident)
    session_incident.add_argument("--db")
    session_incident.add_argument("--session-id", required=True)
    session_incident.add_argument("--severity", default="warning")
    session_incident.add_argument("--summary", required=True)
    session_incident.add_argument("--output-dir", required=True)
    session_incident_drill = session_subparsers.add_parser("incident-drill")
    _add_common_config(session_incident_drill)
    session_incident_drill.add_argument("--db")
    session_incident_drill.add_argument("--severity", default="warning")
    session_incident_drill.add_argument("--summary", default="Synthetic incident drill")
    session_incident_drill.add_argument("--output-dir", required=True)

    review = subparsers.add_parser("review", help="serve the local review authority API")
    review_subparsers = review.add_subparsers(dest="review_command", required=True)
    review_serve = review_subparsers.add_parser("serve")
    _add_common_config(review_serve)
    review_serve.add_argument("--db")
    review_serve.add_argument("--token")
    review_serve.add_argument("--host", default="127.0.0.1")
    review_serve.add_argument("--port", type=int, default=8002)

    publish = subparsers.add_parser("publish", help="build and verify public snapshots")
    publish_subparsers = publish.add_subparsers(dest="publish_command", required=True)
    publish_build = publish_subparsers.add_parser("build")
    _add_common_config(publish_build)
    publish_build.add_argument("--db")
    publish_build.add_argument("--output-dir")
    publish_verify = publish_subparsers.add_parser("verify")
    _add_common_config(publish_verify)
    publish_verify.add_argument("--snapshot")
    publish_rollback = publish_subparsers.add_parser("rollback")
    _add_common_config(publish_rollback)
    publish_rollback.add_argument("--db")
    publish_rollback.add_argument("--output-dir")
    publish_rollback.add_argument("--version", type=int, required=True)

    portfolio = subparsers.add_parser("portfolio", help="serve the dynamic public portfolio")
    portfolio_subparsers = portfolio.add_subparsers(dest="portfolio_command", required=True)
    portfolio_serve = portfolio_subparsers.add_parser("serve")
    _add_common_config(portfolio_serve)
    portfolio_serve.add_argument("--snapshot")
    portfolio_serve.add_argument("--host", default="127.0.0.1")
    portfolio_serve.add_argument("--port", type=int, default=8001)
    portfolio_export = portfolio_subparsers.add_parser("export")
    _add_common_config(portfolio_export)
    portfolio_export.add_argument("--snapshot")
    portfolio_export.add_argument("--output-dir", required=True)
    return parser


def _database_from_args(args: argparse.Namespace) -> Database:
    config = load_config(args.config)
    workspace = config.source_path.parent.parent
    path = (
        Path(args.db).resolve()
        if args.db
        else config.resolve_path(config.paths.database_path, workspace=workspace)
    )
    return Database(path, file_mode=int(config.security.private_file_mode, 8))


def _serve_fixture(host: str, port: int, root: str) -> int:
    directory = Path(root).expanduser().resolve()
    if not (directory / "index.html").is_file():
        raise FileNotFoundError(f"fixture index not found: {directory / 'index.html'}")
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer((host, port), handler)
    print(f"fixture=http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _validate_iso_datetime(value: str) -> str:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid ISO datetime: {value}") from error
    return value


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        report = run_doctor(args.config)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1
    if args.command == "init":
        config = load_config(args.config)
        workspace = config.source_path.parent.parent
        ensure_runtime_directories(config, workspace=workspace)
        database = _database_from_args(args)
        database.initialize()
        print(json.dumps(database.verify(), indent=2, sort_keys=True))
        return 0
    if args.command == "kb":
        database = _database_from_args(args)
        if args.kb_command == "verify":
            print(json.dumps(database.verify(), indent=2, sort_keys=True))
            return 0
        if args.kb_command in {"backup", "export"}:
            print(database.backup(args.output))
            return 0
        if args.kb_command == "restore":
            database.restore(args.backup)
            print(json.dumps(database.verify(), indent=2, sort_keys=True))
            return 0
        if args.kb_command == "delete":
            if args.confirm != "DELETE":
                print("refusing deletion: pass --confirm DELETE", file=sys.stderr)
                return 2
            database.delete()
            print(f"deleted={database.path}")
            return 0
        if args.kb_command == "prune":
            if args.confirm != "PRUNE":
                print("refusing prune: pass --confirm PRUNE", file=sys.stderr)
                return 2
            deleted = database.prune_observations_before(_validate_iso_datetime(args.before))
            print(
                json.dumps(
                    {
                        "database": database.path.name,
                        "before": args.before,
                        "deleted_observations": deleted,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
    if args.command == "security" and args.security_command == "at-rest-report":
        config = load_config(args.config)
        workspace = config.source_path.parent.parent
        database = _database_from_args(args)
        report = at_rest_protection_report(config, workspace=workspace, database=database)
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(encoded, encoding="utf-8")
            print(output)
        else:
            print(encoded, end="")
        return 0 if report["filesystem"]["ok"] else 1
    if args.command == "security" and args.security_command == "accept-full-disk":
        if args.confirm != "ACCEPT-FULL-DISK":
            print(
                "refusing full-disk acceptance: pass --confirm ACCEPT-FULL-DISK",
                file=sys.stderr,
            )
            return 2
        expires_at = _validate_iso_datetime(args.expires_at) if args.expires_at else None
        database = _database_from_args(args)
        acceptance_id = database.create_at_rest_acceptance(
            accepted_by=args.accepted_by,
            evidence_summary=args.summary,
            expires_at=expires_at,
            metadata={"accepted_via": "cli"},
        )
        print(
            json.dumps(
                {
                    "at_rest_acceptance_id": acceptance_id,
                    "protection_kind": "full_disk_encryption",
                    "status": "active",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "security" and args.security_command == "at-rest-acceptance-status":
        database = _database_from_args(args)
        print(
            json.dumps(
                database.at_rest_acceptance_report(status=args.status),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "security" and args.security_command == "revoke-at-rest-acceptance":
        database = _database_from_args(args)
        database.revoke_at_rest_acceptance(args.acceptance_id)
        print(json.dumps({"at_rest_acceptance_id": args.acceptance_id, "status": "revoked"}))
        return 0
    if args.command == "site" and args.site_command == "policy-report":
        policy = load_site_policy(args.policy)
        print(
            json.dumps(
                {
                    "policy_path": str(policy.source_path),
                    "policy_sha256": site_policy_sha256(policy),
                    "policy": site_policy_payload(policy),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "site" and args.site_command == "approve-scope":
        if args.confirm != "APPROVE-SCOPE":
            print("refusing site-scope approval: pass --confirm APPROVE-SCOPE", file=sys.stderr)
            return 2
        policy = load_site_policy(args.policy)
        if not policy.real_site:
            print("refusing site-scope approval: policy is not marked real_site", file=sys.stderr)
            return 2
        expires_at = _validate_iso_datetime(args.expires_at) if args.expires_at else None
        database = _database_from_args(args)
        approval_id = database.create_site_scope_approval(
            site_id=policy.site_id,
            policy_sha256=site_policy_sha256(policy),
            approved_by=args.approver,
            scope_summary=args.summary,
            expires_at=expires_at,
            metadata={
                "policy_path": str(policy.source_path),
                "policy": site_policy_payload(policy),
            },
        )
        print(
            json.dumps(
                {
                    "site_scope_approval_id": approval_id,
                    "site_id": policy.site_id,
                    "policy_sha256": site_policy_sha256(policy),
                    "status": "active",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "site" and args.site_command == "scope-status":
        database = _database_from_args(args)
        print(
            json.dumps(
                database.site_scope_report(site_id=args.site_id, status=args.status),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "site" and args.site_command == "revoke-scope":
        database = _database_from_args(args)
        database.revoke_site_scope_approval(args.approval_id)
        print(json.dumps({"site_scope_approval_id": args.approval_id, "status": "revoked"}))
        return 0
    if args.command == "fixture" and args.fixture_command == "serve":
        return _serve_fixture(args.host, args.port, args.root)
    if args.command == "source-manifest":
        output = write_source_manifest(args.root, args.output)
        print(output)
        return 0
    if args.command == "release" and args.release_command == "evidence":
        output = write_release_evidence(
            output_path=args.output,
            source_manifest=args.source_manifest,
            session_report=args.session_report,
            at_rest_report=args.at_rest_report,
            ocr_report=args.ocr_report,
            action_report=args.action_report,
            native_pointer_report=args.native_pointer_report,
            incident_json=args.incident_json,
            sdist=args.sdist,
            wheel=args.wheel,
        )
        print(output)
        return 0
    if args.command == "release" and args.release_command == "approve":
        output = write_release_approval_record(
            candidate_path=args.candidate,
            expected_sha256=args.expected_sha256,
            approver=args.approver,
            output_path=args.output,
            confirmation=args.confirm,
        )
        print(output)
        return 0
    if args.command == "ocr" and args.ocr_command == "golden":
        output = write_golden_report(args.corpus, args.output)
        print(output)
        return 0
    if args.command == "session" and args.session_command == "report":
        database = _database_from_args(args)
        report = database.session_report(args.session_id)
        encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(encoded, encoding="utf-8")
            print(output)
        else:
            print(encoded, end="")
        return 0
    if args.command == "session" and args.session_command in {"pause", "resume", "stop"}:
        database = _database_from_args(args)
        request_id = database.request_control(
            session_id=args.session_id,
            command=args.session_command,
            reason=args.reason,
            metadata={"requested_by": "cli"},
        )
        print(
            json.dumps(
                {
                    "control_request_id": request_id,
                    "session_id": args.session_id,
                    "command": args.session_command,
                    "status": "pending",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "session" and args.session_command == "control-status":
        database = _database_from_args(args)
        print(
            json.dumps(
                database.control_report(session_id=args.session_id, status=args.status),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "session" and args.session_command == "incident":
        database = _database_from_args(args)
        incident_result = build_incident_bundle(
            database,
            output_dir=args.output_dir,
            session_id=args.session_id,
            severity=args.severity,
            summary=args.summary,
            file_mode=database.file_mode,
        )
        print(
            json.dumps(
                {
                    "incident_id": incident_result.incident_id,
                    "output_dir": str(incident_result.output_dir),
                    "json_path": str(incident_result.json_path),
                    "markdown_path": str(incident_result.markdown_path),
                    "manifest_sha256": incident_result.manifest_sha256,
                    "json_sha256": incident_result.json_sha256,
                    "markdown_sha256": incident_result.markdown_sha256,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "session" and args.session_command == "incident-drill":
        database = _database_from_args(args)
        drill_result = run_incident_drill(
            database,
            output_dir=args.output_dir,
            severity=args.severity,
            summary=args.summary,
            file_mode=database.file_mode,
        )
        print(
            json.dumps(
                {
                    "incident_id": drill_result.incident_id,
                    "session_id": drill_result.session_id,
                    "output_dir": str(drill_result.output_dir),
                    "json_path": str(drill_result.json_path),
                    "markdown_path": str(drill_result.markdown_path),
                    "manifest_sha256": drill_result.manifest_sha256,
                    "passed": drill_result.passed,
                    "checks": drill_result.checks,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if drill_result.passed else 1
    if args.command == "review" and args.review_command == "serve":
        database = _database_from_args(args)
        token = args.token or os.environ.get("SOCIALOPERATOR_REVIEW_TOKEN", "")
        if not token:
            print(
                "refusing review server: pass --token or set SOCIALOPERATOR_REVIEW_TOKEN",
                file=sys.stderr,
            )
            return 2
        import uvicorn

        uvicorn.run(
            create_review_app(database.path, review_token=token),
            host=args.host,
            port=args.port,
        )
        return 0
    if args.command == "publish":
        config = load_config(args.config)
        workspace = config.source_path.parent.parent
        if args.publish_command == "build":
            database = _database_from_args(args)
            output_dir = (
                Path(args.output_dir).expanduser().resolve()
                if args.output_dir
                else config.resolve_path(config.paths.public_data_dir, workspace=workspace)
            )
            publication_result = PublicationBuilder(database, output_dir).build()
            print(
                json.dumps(
                    {
                        "publication_version_id": publication_result.publication_version_id,
                        "version_number": publication_result.version_number,
                        "version_database_path": str(publication_result.version_database_path),
                        "active_database_path": str(publication_result.active_database_path),
                        "manifest_path": str(publication_result.manifest_path),
                        "manifest_sha256": publication_result.manifest_sha256,
                        "item_count": publication_result.item_count,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.publish_command == "rollback":
            database = _database_from_args(args)
            output_dir = (
                Path(args.output_dir).expanduser().resolve()
                if args.output_dir
                else config.resolve_path(config.paths.public_data_dir, workspace=workspace)
            )
            print(PublicationBuilder(database, output_dir).rollback(args.version))
            return 0
        snapshot = (
            Path(args.snapshot).expanduser().resolve()
            if args.snapshot
            else config.resolve_path(
                f"{config.paths.public_data_dir}/portfolio-public.sqlite",
                workspace=workspace,
            )
        )
        print(json.dumps(verify_public_snapshot(snapshot), indent=2, sort_keys=True))
        return 0
    if args.command == "portfolio":
        config = load_config(args.config)
        workspace = config.source_path.parent.parent
        snapshot = (
            Path(args.snapshot).expanduser().resolve()
            if args.snapshot
            else config.resolve_path(
                f"{config.paths.public_data_dir}/portfolio-public.sqlite",
                workspace=workspace,
            )
        )
        if args.portfolio_command == "export":
            export_result = export_static_site(snapshot, args.output_dir)
            print(
                json.dumps(
                    {
                        "output_dir": str(export_result.output_dir),
                        "manifest_path": str(export_result.manifest_path),
                        "manifest_sha256": export_result.manifest_sha256,
                        "file_count": export_result.file_count,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        import uvicorn

        uvicorn.run(create_portfolio_app(snapshot), host=args.host, port=args.port)
        return 0
    raise AssertionError("unhandled command")
