from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from socialoperator.browser.observer import PageObserver
from socialoperator.browser.session import BrowserSession
from socialoperator.capture.artifacts import ArtifactStore
from socialoperator.config import load_config, load_site_policy
from socialoperator.knowledge.database import Database
from socialoperator.knowledge.publication import (
    PublicationBuilder,
    PublicationError,
    verify_public_snapshot,
)
from socialoperator.knowledge.service import KnowledgeService
from socialoperator.portfolio.accessibility import check_html_accessibility, check_static_export
from socialoperator.portfolio.app import create_portfolio_app
from socialoperator.portfolio.export import export_static_site
from socialoperator.review.app import create_review_app
from socialoperator.review.service import ProposalDraft, ReviewConflictError, ReviewService
from socialoperator.types import Sensitivity

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_SENTINEL = "-".join(("PRIVATE", "ONLY", "SECRET", "DO", "NOT", "PUBLISH"))


def _capture_fixture_observation(
    tmp_path: Path,
    fixture_server_url: str,
):
    config = load_config(ROOT / "config" / "default.toml")
    policy = load_site_policy(ROOT / "config" / "sites" / "local_fixture.toml")
    session = BrowserSession(
        config,
        policy,
        workspace=ROOT,
        profile_dir=tmp_path / "profile",
        headless=True,
    )
    try:
        session.start(fixture_server_url)
        session.resume_after_login()
        observation = PageObserver().observe(session)
    finally:
        session.stop()
    return observation, policy


def test_private_observation_to_public_portfolio_flow(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    proposal = KnowledgeService(database).ingest_page_observation(
        observation,
        site_policy=policy,
    )
    database.add_observation(
        observation_kind="private_note",
        raw_text=PRIVATE_SENTINEL,
        normalized_text="private only secret do not publish",
        retention_protected=True,
    )
    review = ReviewService(database).approve(
        proposal.portfolio_item_id,
        expected_proposal_sha256=proposal.proposal_sha256,
        reviewer_identity="fixture-user",
        reason="synthetic fixture acceptance",
    )
    assert review.publication_status.value == "candidate"
    publication = PublicationBuilder(database, tmp_path / "public").build()
    verification = verify_public_snapshot(
        publication.active_database_path,
        expected_manifest_sha256=publication.manifest_sha256,
    )
    assert verification["ok"]
    assert publication.item_count == 1
    assert publication.asset_count == 0
    assert PRIVATE_SENTINEL.encode() not in publication.active_database_path.read_bytes()

    client = TestClient(create_portfolio_app(publication.active_database_path))
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["item_count"] == 1
    index = client.get("/")
    assert index.status_code == 200
    assert not check_html_accessibility(index.text, label="dynamic index")
    assert "SocialOperator Synthetic Profile" in index.text
    projects = client.get("/projects")
    assert projects.status_code == 200
    assert not check_html_accessibility(projects.text, label="dynamic projects")
    assert "SocialOperator Synthetic Profile" in projects.text
    profile = client.get("/profile")
    assert profile.status_code == 200
    assert "No approved public profile items" in profile.text
    assert client.get("/missing-section").status_code == 404
    item = client.get("/items/socialoperator-synthetic-profile")
    assert item.status_code == 200
    assert not check_html_accessibility(item.text, label="dynamic item")
    assert "Projects" in item.text
    assert "project" in item.text
    assert "synthetic user-owned portfolio data" in item.text

    second = PublicationBuilder(database, tmp_path / "public").build()
    assert second.version_number == 2
    assert second.item_count == 1
    current = ReviewService(database).get_item(proposal.portfolio_item_id)
    ReviewService(database).revoke(
        proposal.portfolio_item_id,
        expected_proposal_sha256=str(current["proposal_sha256"]),
        reviewer_identity="fixture-user",
        reason="revocation propagation test",
    )
    third = PublicationBuilder(database, tmp_path / "public").build()
    assert third.version_number == 3
    assert third.item_count == 0
    empty_client = TestClient(create_portfolio_app(third.active_database_path))
    assert "No approved public portfolio items" in empty_client.get("/").text
    PublicationBuilder(database, tmp_path / "public").rollback(1)
    rolled_back = TestClient(create_portfolio_app(third.active_database_path))
    assert rolled_back.get("/health").json()["item_count"] == 1


def test_public_assets_and_static_export_are_allowlisted_and_scanned(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    store = ArtifactStore(tmp_path / "artifacts", database)
    public_asset = store.put_bytes(
        b"Synthetic public asset created by the user.\n",
        media_type="text/plain",
        sensitivity=Sensitivity.PUBLIC,
        redacted=True,
        metadata={
            "source_label": "Synthetic public asset",
            "publication": {"allowed": True, "rights": "created_by_user"},
        },
    )
    private_asset = store.put_bytes(
        f"{PRIVATE_SENTINEL}\n".encode(),
        media_type="text/plain",
        sensitivity=Sensitivity.PRIVATE,
        redacted=False,
    )
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    proposal = KnowledgeService(database).ingest_page_observation(
        observation,
        site_policy=policy,
        capture_artifact_id=public_asset.artifact_id,
    )
    database.add_observation(
        observation_kind="private_asset_note",
        raw_text="private asset reference",
        normalized_text="private asset reference",
        capture_artifact_id=private_asset.artifact_id,
        retention_protected=True,
    )
    ReviewService(database).approve(
        proposal.portfolio_item_id,
        expected_proposal_sha256=proposal.proposal_sha256,
        reviewer_identity="fixture-user",
    )
    publication = PublicationBuilder(
        database,
        tmp_path / "public",
        artifact_root=store.root,
    ).build()
    assert publication.item_count == 1
    assert publication.asset_count == 1
    verification = verify_public_snapshot(
        publication.active_database_path, asset_root=tmp_path / "public"
    )
    assert verification["asset_count"] == 1
    public_asset_path = tmp_path / "public" / "assets" / "sha256" / public_asset.sha256
    assert public_asset_path.read_bytes() == b"Synthetic public asset created by the user.\n"
    public_bytes = publication.active_database_path.read_bytes() + public_asset_path.read_bytes()
    assert b"Synthetic public asset" in public_bytes
    assert PRIVATE_SENTINEL.encode() not in public_bytes

    client = TestClient(create_portfolio_app(publication.active_database_path))
    item = client.get("/items/socialoperator-synthetic-profile")
    assert item.status_code == 200
    assert "Synthetic public asset" in item.text
    asset_response = client.get(f"/assets/sha256/{public_asset.sha256}")
    assert asset_response.status_code == 200
    assert asset_response.content == b"Synthetic public asset created by the user.\n"

    export = export_static_site(publication.active_database_path, tmp_path / "static")
    assert export.file_count >= 3
    assert export.manifest_path.is_file()
    assert not check_static_export(export.output_dir)
    assert (export.output_dir / "projects" / "index.html").is_file()
    assert (export.output_dir / "assets" / "sha256" / public_asset.sha256).is_file()


def test_public_asset_scanner_rejects_forbidden_asset_content(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    store = ArtifactStore(tmp_path / "artifacts", database)
    bad_asset = store.put_bytes(
        f"{PRIVATE_SENTINEL}\n".encode(),
        media_type="text/plain",
        sensitivity=Sensitivity.PUBLIC,
        redacted=True,
        metadata={
            "source_label": "Bad public asset",
            "publication": {"allowed": True, "rights": "created_by_user"},
        },
    )
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    proposal = KnowledgeService(database).ingest_page_observation(
        observation,
        site_policy=policy,
        capture_artifact_id=bad_asset.artifact_id,
    )
    ReviewService(database).approve(
        proposal.portfolio_item_id,
        expected_proposal_sha256=proposal.proposal_sha256,
        reviewer_identity="fixture-user",
    )
    with pytest.raises(PublicationError, match="forbidden public content"):
        PublicationBuilder(database, tmp_path / "public", artifact_root=store.root).build()


def test_review_api_requires_token_and_exact_hash(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    proposal = KnowledgeService(database).ingest_page_observation(
        observation,
        site_policy=policy,
    )
    app = create_review_app(database.path, review_token="test-review-token")
    client = TestClient(app)
    assert client.get("/api/proposals").status_code == 401
    assert client.get("/").status_code == 401
    review_page = client.get("/", auth=("user", "test-review-token"))
    assert review_page.status_code == 200
    assert "Source evidence" in review_page.text
    assert "Redact and resubmit" in review_page.text
    assert fixture_server_url in review_page.text
    bad_csrf = client.post(
        f"/items/{proposal.portfolio_item_id}/approve",
        auth=("user", "test-review-token"),
        data={
            "csrf_token": "invalid",
            "proposal_sha256": proposal.proposal_sha256,
            "reviewer_identity": "fixture-user",
            "reason": "test",
        },
    )
    assert bad_csrf.status_code == 403
    headers = {"X-SocialOperator-Review-Token": "test-review-token"}
    proposals = client.get("/api/proposals", headers=headers)
    assert proposals.status_code == 200
    assert proposals.json()[0]["proposal_sha256"] == proposal.proposal_sha256
    conflict = client.post(
        f"/api/proposals/{proposal.portfolio_item_id}/approve",
        headers=headers,
        json={
            "proposal_sha256": "0" * 64,
            "reviewer_identity": "fixture-user",
        },
    )
    assert conflict.status_code == 409
    approved = client.post(
        f"/api/proposals/{proposal.portfolio_item_id}/approve",
        headers=headers,
        json={
            "proposal_sha256": proposal.proposal_sha256,
            "reviewer_identity": "fixture-user",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["decision"] == "approved"


def test_authenticated_review_redaction_merge_and_split_controls(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    observations = (
        observation,
        replace(
            observation,
            title="Merge Source Two",
            headings=("Merge Source Two",),
            readable_text="Merge Source Two\nCreated by synthetic-user as owned project data.",
        ),
        replace(
            observation,
            title="Split Source",
            headings=("Split Source",),
            readable_text="Split Source\nCreated by synthetic-user as owned project data.",
        ),
    )
    knowledge = KnowledgeService(database)
    first, second, third = tuple(
        knowledge.ingest_page_observation(value, site_policy=policy) for value in observations
    )
    app = create_review_app(database.path, review_token="test-review-token")
    client = TestClient(app)
    ui_auth = ("user", "test-review-token")
    headers = {"X-SocialOperator-Review-Token": "test-review-token"}
    redacted = client.post(
        f"/items/{first.portfolio_item_id}/redact",
        auth=ui_auth,
        follow_redirects=False,
        data={
            "csrf_token": app.state.csrf_token,
            "proposal_sha256": first.proposal_sha256,
            "title": "Redacted Merge Source One",
            "summary": "Redacted public summary",
            "body": "Redacted public body",
            "reviewer_identity": "fixture-user",
            "reason": "remove private phrase",
        },
    )
    assert redacted.status_code == 303
    first_current = ReviewService(database).get_item(first.portfolio_item_id)
    merged = client.post(
        "/api/proposals/merge",
        headers=headers,
        json={
            "source_proposal_sha256": {
                first.portfolio_item_id: first_current["proposal_sha256"],
                second.portfolio_item_id: second.proposal_sha256,
            },
            "draft": {
                "slug": "api-merged-project",
                "item_type": "project",
                "title": "API Merged Project",
                "summary": "Merged through authenticated API.",
                "body": "Merged API body.",
            },
            "reviewer_identity": "fixture-user",
            "reason": "authenticated merge test",
        },
    )
    assert merged.status_code == 200
    assert merged.json()["operation"] == "merge"
    assert len(merged.json()["derived_portfolio_item_ids"]) == 1
    split = client.post(
        f"/api/proposals/{third.portfolio_item_id}/split",
        headers=headers,
        json={
            "proposal_sha256": third.proposal_sha256,
            "drafts": [
                {
                    "slug": "api-split-a",
                    "item_type": "profile",
                    "title": "API Split A",
                    "summary": "First split proposal.",
                    "body": "First split body.",
                },
                {
                    "slug": "api-split-b",
                    "item_type": "project",
                    "title": "API Split B",
                    "summary": "Second split proposal.",
                    "body": "Second split body.",
                },
            ],
            "reviewer_identity": "fixture-user",
            "reason": "authenticated split test",
        },
    )
    assert split.status_code == 200
    assert split.json()["operation"] == "split"
    assert len(split.json()["derived_portfolio_item_ids"]) == 2
    unauthorized = client.post(
        "/api/proposals/merge",
        json={
            "source_proposal_sha256": {},
            "draft": {
                "slug": "blocked",
                "item_type": "project",
                "title": "Blocked",
                "summary": "Blocked",
                "body": "Blocked",
            },
            "reviewer_identity": "fixture-user",
            "reason": "must not run",
        },
    )
    assert unauthorized.status_code == 401


def test_review_claim_contradiction_supersession_requires_exact_hash(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    proposal = KnowledgeService(database).ingest_page_observation(observation, site_policy=policy)
    service = ReviewService(database)
    service.approve(
        proposal.portfolio_item_id,
        expected_proposal_sha256=proposal.proposal_sha256,
        reviewer_identity="fixture-user",
        reason="seed approved stale claim",
    )
    replacement_claim_id = "replacement-claim"
    with database.connect() as connection:
        source_claim = connection.execute(
            """
            SELECT c.*
            FROM claims c
            JOIN portfolio_item_claims pic ON pic.claim_id = c.claim_id
            WHERE pic.portfolio_item_id = ?
            """,
            (proposal.portfolio_item_id,),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO claims(
                claim_id, subject_entity_id, predicate, object_text, status,
                created_at, metadata_json
            ) VALUES (?, ?, ?, ?, 'proposed', ?, '{}')
            """,
            (
                replacement_claim_id,
                source_claim["subject_entity_id"],
                source_claim["predicate"],
                "Replacement public description for the same subject.",
                "2026-08-31T00:00:00+00:00",
            ),
        )
    app = create_review_app(database.path, review_token="test-review-token")
    client = TestClient(app)
    headers = {"X-SocialOperator-Review-Token": "test-review-token"}
    contradictions = client.get("/api/claims/contradictions", headers=headers)
    assert contradictions.status_code == 200
    contradiction = contradictions.json()[0]
    claims = [contradiction["first"], contradiction["second"]]
    source_payload = next(
        claim for claim in claims if claim["claim_id"] == source_claim["claim_id"]
    )
    replacement_payload = next(
        claim for claim in claims if claim["claim_id"] == replacement_claim_id
    )
    review_page = client.get("/", auth=("user", "test-review-token"))
    assert review_page.status_code == 200
    assert "Claim Contradictions" in review_page.text
    assert "Supersede first with second" in review_page.text
    stale = client.post(
        f"/api/claims/{source_payload['claim_id']}/supersede",
        headers=headers,
        json={
            "replacement_claim_id": replacement_payload["claim_id"],
            "claim_sha256": "0" * 64,
            "reviewer_identity": "fixture-user",
            "reason": "stale hash must fail",
        },
    )
    assert stale.status_code == 409
    superseded = client.post(
        f"/api/claims/{source_payload['claim_id']}/supersede",
        headers=headers,
        json={
            "replacement_claim_id": replacement_payload["claim_id"],
            "claim_sha256": source_payload["claim_sha256"],
            "reviewer_identity": "fixture-user",
            "reason": "replacement claim is authoritative",
        },
    )
    assert superseded.status_code == 200
    assert superseded.json()["affected_portfolio_item_ids"] == [proposal.portfolio_item_id]
    with database.connect() as connection:
        superseded_claim = connection.execute(
            "SELECT status, superseded_by_claim_id FROM claims WHERE claim_id = ?",
            (source_payload["claim_id"],),
        ).fetchone()
        portfolio_item = connection.execute(
            """
            SELECT review_status, publication_status
            FROM portfolio_items WHERE portfolio_item_id = ?
            """,
            (proposal.portfolio_item_id,),
        ).fetchone()
        decision = connection.execute(
            "SELECT decision FROM review_decisions WHERE claim_id = ?",
            (source_payload["claim_id"],),
        ).fetchone()
    assert superseded_claim["status"] == "superseded"
    assert superseded_claim["superseded_by_claim_id"] == replacement_claim_id
    assert portfolio_item["review_status"] == "proposed"
    assert portfolio_item["publication_status"] == "unpublished"
    assert decision["decision"] == "superseded"
    assert client.get("/api/claims/contradictions", headers=headers).json() == []


def test_edit_invalidates_previous_proposal_hash(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    proposal = KnowledgeService(database).ingest_page_observation(
        observation,
        site_policy=policy,
    )
    service = ReviewService(database)
    changed = service.edit_proposal(
        proposal.portfolio_item_id,
        expected_proposal_sha256=proposal.proposal_sha256,
        title="Edited Synthetic Profile",
        summary="Edited summary",
        body="Edited body",
        reviewer_identity="fixture-user",
        reason="fixture edit",
    )
    assert changed["proposal_sha256"] != proposal.proposal_sha256
    with pytest.raises(ReviewConflictError):
        service.approve(
            proposal.portfolio_item_id,
            expected_proposal_sha256=proposal.proposal_sha256,
            reviewer_identity="fixture-user",
        )


def test_redaction_preserves_revision_and_requires_new_exact_hash(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    proposal = KnowledgeService(database).ingest_page_observation(observation, site_policy=policy)
    service = ReviewService(database)
    result = service.redact(
        proposal.portfolio_item_id,
        expected_proposal_sha256=proposal.proposal_sha256,
        title="Redacted Synthetic Profile",
        summary="Public redacted summary",
        body="Public redacted body.",
        reviewer_identity="fixture-user",
        reason="remove private detail",
    )
    assert result.previous_proposal_sha256 == proposal.proposal_sha256
    assert result.proposal_sha256 != proposal.proposal_sha256
    with pytest.raises(ReviewConflictError):
        service.approve(
            proposal.portfolio_item_id,
            expected_proposal_sha256=proposal.proposal_sha256,
            reviewer_identity="fixture-user",
        )
    assert PublicationBuilder(database, tmp_path / "public-before-approval").build().item_count == 0
    service.approve(
        proposal.portfolio_item_id,
        expected_proposal_sha256=result.proposal_sha256,
        reviewer_identity="fixture-user",
        reason="approve redacted proposal",
    )
    publication = PublicationBuilder(database, tmp_path / "public").build()
    assert publication.item_count == 1
    public_bytes = publication.active_database_path.read_bytes()
    assert b"Public redacted body." in public_bytes
    assert b"synthetic user-owned portfolio data" not in public_bytes
    with database.connect() as connection:
        revision = connection.execute(
            "SELECT * FROM portfolio_item_revisions WHERE portfolio_item_id = ?",
            (proposal.portfolio_item_id,),
        ).fetchone()
        decision = connection.execute(
            "SELECT decision FROM review_decisions WHERE review_decision_id = ?",
            (result.review_decision_id,),
        ).fetchone()
    assert revision["proposal_sha256"] == proposal.proposal_sha256
    assert "SocialOperator Synthetic Profile" in revision["proposal_payload_json"]
    assert decision["decision"] == "redacted"


def test_merge_supersedes_sources_and_unions_claims(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    second_observation = replace(
        observation,
        title="Second Synthetic Project",
        headings=("Second Synthetic Project",),
        readable_text=(
            "Second Synthetic Project\nCreated by synthetic-user as user-owned portfolio data."
        ),
    )
    knowledge = KnowledgeService(database)
    first = knowledge.ingest_page_observation(observation, site_policy=policy)
    second = knowledge.ingest_page_observation(second_observation, site_policy=policy)
    service = ReviewService(database)
    merged = service.merge(
        {
            first.portfolio_item_id: first.proposal_sha256,
            second.portfolio_item_id: second.proposal_sha256,
        },
        draft=ProposalDraft(
            slug="merged-synthetic-projects",
            item_type="project",
            title="Merged Synthetic Projects",
            summary="Two reviewed sources merged into one proposal.",
            body="Merged public portfolio body.",
        ),
        reviewer_identity="fixture-user",
        reason="combine duplicate project coverage",
    )
    derived_id = merged.derived_portfolio_item_ids[0]
    with database.connect() as connection:
        source_statuses = connection.execute(
            """
            SELECT review_status, publication_status FROM portfolio_items
            WHERE portfolio_item_id IN (?, ?) ORDER BY portfolio_item_id
            """,
            (first.portfolio_item_id, second.portfolio_item_id),
        ).fetchall()
        claim_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM portfolio_item_claims WHERE portfolio_item_id = ?",
                (derived_id,),
            ).fetchone()[0]
        )
        lineage_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM portfolio_item_lineage WHERE derived_portfolio_item_id = ?",
                (derived_id,),
            ).fetchone()[0]
        )
    assert all(row["review_status"] == "superseded" for row in source_statuses)
    assert all(row["publication_status"] == "superseded" for row in source_statuses)
    assert claim_count == 2
    assert lineage_count == 2
    assert PublicationBuilder(database, tmp_path / "public-before-approval").build().item_count == 0
    service.approve(
        derived_id,
        expected_proposal_sha256=merged.derived_proposal_sha256[0],
        reviewer_identity="fixture-user",
    )
    publication = PublicationBuilder(database, tmp_path / "public").build()
    assert publication.item_count == 1
    assert b"Merged Synthetic Projects" in publication.active_database_path.read_bytes()


def test_split_supersedes_source_and_copies_provenance(
    tmp_path: Path,
    fixture_server_url: str,
) -> None:
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    observation, policy = _capture_fixture_observation(tmp_path, fixture_server_url)
    proposal = KnowledgeService(database).ingest_page_observation(observation, site_policy=policy)
    service = ReviewService(database)
    split = service.split(
        proposal.portfolio_item_id,
        expected_proposal_sha256=proposal.proposal_sha256,
        drafts=(
            ProposalDraft(
                slug="synthetic-profile-summary",
                item_type="profile",
                title="Synthetic Profile Summary",
                summary="Profile-only summary.",
                body="Profile-only public body.",
            ),
            ProposalDraft(
                slug="synthetic-project-detail",
                item_type="project",
                title="Synthetic Project Detail",
                summary="Project-only summary.",
                body="Project-only public body.",
            ),
        ),
        reviewer_identity="fixture-user",
        reason="separate profile and project concepts",
    )
    assert len(split.derived_portfolio_item_ids) == 2
    with database.connect() as connection:
        source = connection.execute(
            """
            SELECT review_status, publication_status FROM portfolio_items
            WHERE portfolio_item_id = ?
            """,
            (proposal.portfolio_item_id,),
        ).fetchone()
        lineage_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM portfolio_item_lineage WHERE source_portfolio_item_id = ?",
                (proposal.portfolio_item_id,),
            ).fetchone()[0]
        )
        copied_claim_counts = [
            int(
                connection.execute(
                    "SELECT COUNT(*) FROM portfolio_item_claims WHERE portfolio_item_id = ?",
                    (derived_id,),
                ).fetchone()[0]
            )
            for derived_id in split.derived_portfolio_item_ids
        ]
    assert source["review_status"] == "superseded"
    assert source["publication_status"] == "superseded"
    assert lineage_count == 2
    assert copied_claim_counts == [1, 1]
