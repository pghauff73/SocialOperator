from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from socialoperator.knowledge.database import Database, canonical_json, utc_now
from socialoperator.knowledge.service import proposal_payload, proposal_sha256
from socialoperator.types import PublicationStatus, ReviewStatus, Sensitivity


class ReviewError(RuntimeError):
    """Base review-authority error."""


class ReviewConflictError(ReviewError):
    """Raised when the reviewed proposal changed after presentation."""


@dataclass(frozen=True, slots=True)
class ReviewResult:
    review_decision_id: str
    portfolio_item_id: str
    proposal_sha256: str
    decision: ReviewStatus
    publication_status: PublicationStatus


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    slug: str
    item_type: str
    title: str
    summary: str
    body: str


@dataclass(frozen=True, slots=True)
class RedactionResult:
    review_decision_id: str
    portfolio_item_id: str
    previous_proposal_sha256: str
    proposal_sha256: str


@dataclass(frozen=True, slots=True)
class DerivationResult:
    operation: str
    source_portfolio_item_ids: tuple[str, ...]
    derived_portfolio_item_ids: tuple[str, ...]
    derived_proposal_sha256: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClaimSupersessionResult:
    review_decision_id: str
    claim_id: str
    replacement_claim_id: str
    claim_sha256: str
    affected_portfolio_item_ids: tuple[str, ...]


_SENSITIVITY_RANK = {
    Sensitivity.PUBLIC.value: 0,
    Sensitivity.PRIVATE.value: 1,
    Sensitivity.RESTRICTED.value: 2,
    Sensitivity.AUTHENTICATION.value: 3,
}


class ReviewService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_item(self, portfolio_item_id: str) -> dict[str, object]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_items WHERE portfolio_item_id = ?",
                (portfolio_item_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown portfolio item: {portfolio_item_id}")
        return {**proposal_payload(row), "proposal_sha256": proposal_sha256(row)}

    def get_item_evidence(self, portfolio_item_id: str) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    sp.url,
                    sp.title AS source_title,
                    sp.captured_at,
                    sp.content_sha256,
                    o.observation_id,
                    o.observation_kind,
                    o.raw_text,
                    o.confidence,
                    ca.relative_path AS artifact_relative_path,
                    ca.sha256 AS artifact_sha256
                FROM portfolio_item_claims pic
                JOIN claim_evidence ce ON ce.claim_id = pic.claim_id
                JOIN observations o ON o.observation_id = ce.observation_id
                LEFT JOIN source_pages sp ON sp.source_page_id = o.source_page_id
                LEFT JOIN capture_artifacts ca
                  ON ca.capture_artifact_id = o.capture_artifact_id
                WHERE pic.portfolio_item_id = ?
                ORDER BY o.observed_at, o.observation_id
                """,
                (portfolio_item_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_items(self, *, status: ReviewStatus | None = None) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM portfolio_items ORDER BY created_at, portfolio_item_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM portfolio_items
                    WHERE review_status = ?
                    ORDER BY created_at, portfolio_item_id
                    """,
                    (status.value,),
                ).fetchall()
        return [{**proposal_payload(row), "proposal_sha256": proposal_sha256(row)} for row in rows]

    def list_claim_contradictions(self) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            pairs = connection.execute(
                """
                SELECT a.claim_id AS first_claim_id, b.claim_id AS second_claim_id
                FROM claims a
                JOIN claims b
                  ON b.subject_entity_id = a.subject_entity_id
                 AND b.predicate = a.predicate
                 AND b.claim_id > a.claim_id
                WHERE a.superseded_by_claim_id IS NULL
                  AND b.superseded_by_claim_id IS NULL
                  AND a.status != ?
                  AND b.status != ?
                  AND COALESCE(a.object_text, '') != COALESCE(b.object_text, '')
                ORDER BY a.created_at, b.created_at, a.claim_id, b.claim_id
                """,
                (ReviewStatus.SUPERSEDED.value, ReviewStatus.SUPERSEDED.value),
            ).fetchall()
            contradictions = []
            for pair in pairs:
                first = self._require_claim(connection, str(pair["first_claim_id"]))
                second = self._require_claim(connection, str(pair["second_claim_id"]))
                contradictions.append(
                    {
                        "subject_entity_id": first["subject_entity_id"],
                        "subject_name": first["subject_name"],
                        "predicate": first["predicate"],
                        "first": self._claim_review_payload(first),
                        "second": self._claim_review_payload(second),
                    }
                )
        return contradictions

    @staticmethod
    def _require_item(connection: sqlite3.Connection, portfolio_item_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM portfolio_items WHERE portfolio_item_id = ?",
            (portfolio_item_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown portfolio item: {portfolio_item_id}")
        return cast(sqlite3.Row, row)

    @staticmethod
    def _require_claim(connection: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT c.*, e.canonical_name AS subject_name
            FROM claims c
            LEFT JOIN entities e ON e.entity_id = c.subject_entity_id
            WHERE c.claim_id = ?
            """,
            (claim_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown claim: {claim_id}")
        return cast(sqlite3.Row, row)

    @staticmethod
    def _claim_review_payload(row: sqlite3.Row) -> dict[str, object]:
        payload = {
            "claim_id": str(row["claim_id"]),
            "subject_entity_id": row["subject_entity_id"],
            "subject_name": row["subject_name"],
            "predicate": str(row["predicate"]),
            "object_entity_id": row["object_entity_id"],
            "object_text": row["object_text"],
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "superseded_by_claim_id": row["superseded_by_claim_id"],
            "metadata": json.loads(str(row["metadata_json"])),
        }
        return {**payload, "claim_sha256": ReviewService._claim_sha256(row)}

    @staticmethod
    def _claim_sha256(row: sqlite3.Row) -> str:
        payload = {
            "claim_id": str(row["claim_id"]),
            "subject_entity_id": row["subject_entity_id"],
            "predicate": str(row["predicate"]),
            "object_entity_id": row["object_entity_id"],
            "object_text": row["object_text"],
            "status": str(row["status"]),
            "created_at": str(row["created_at"]),
            "superseded_by_claim_id": row["superseded_by_claim_id"],
            "metadata": json.loads(str(row["metadata_json"])),
        }
        return hashlib.sha256(canonical_json(payload).encode()).hexdigest()

    @staticmethod
    def _require_hash(row: sqlite3.Row, expected: str, operation: str) -> str:
        current = proposal_sha256(row)
        if current != expected:
            raise ReviewConflictError(
                f"proposal changed after it was presented for {operation}; refresh first"
            )
        return current

    @staticmethod
    def _validate_identity_reason(reviewer_identity: str, reason: str) -> None:
        if not reviewer_identity.strip() or not reason.strip():
            raise ValueError("reviewer_identity and reason are required")

    @staticmethod
    def _validate_draft(draft: ProposalDraft) -> ProposalDraft:
        values = (draft.slug, draft.item_type, draft.title, draft.summary, draft.body)
        if any(not value.strip() for value in values):
            raise ValueError("slug, item_type, title, summary, and body are required")
        return ProposalDraft(
            slug=draft.slug.strip(),
            item_type=draft.item_type.strip(),
            title=draft.title.strip(),
            summary=draft.summary.strip(),
            body=draft.body.strip(),
        )

    @staticmethod
    def _record_revision(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        operation: str,
        reviewer_identity: str,
        reason: str,
        now: str,
    ) -> str:
        revision_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO portfolio_item_revisions(
                portfolio_item_revision_id, portfolio_item_id, proposal_sha256,
                proposal_payload_json, operation, reviewer_identity, reason,
                created_at, retention_protected
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                revision_id,
                row["portfolio_item_id"],
                proposal_sha256(row),
                canonical_json(proposal_payload(row)),
                operation,
                reviewer_identity,
                reason,
                now,
            ),
        )
        return revision_id

    @staticmethod
    def _record_review_decision(
        connection: sqlite3.Connection,
        *,
        portfolio_item_id: str | None = None,
        claim_id: str | None = None,
        proposal_hash: str,
        decision: ReviewStatus,
        reviewer_identity: str,
        reason: str,
        now: str,
    ) -> str:
        if (portfolio_item_id is None) == (claim_id is None):
            raise ValueError("exactly one of portfolio_item_id or claim_id is required")
        review_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO review_decisions(
                review_decision_id, portfolio_item_id, claim_id, proposal_sha256, decision,
                reviewer_identity, decided_at, reason, retention_protected
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                review_id,
                portfolio_item_id,
                claim_id,
                proposal_hash,
                decision.value,
                reviewer_identity,
                now,
                reason,
            ),
        )
        return review_id

    @staticmethod
    def _replace_fts(
        connection: sqlite3.Connection,
        portfolio_item_id: str,
        *,
        title: str,
        summary: str,
        body: str,
    ) -> None:
        connection.execute(
            "DELETE FROM portfolio_fts WHERE portfolio_item_id = ?",
            (portfolio_item_id,),
        )
        connection.execute(
            """
            INSERT INTO portfolio_fts(portfolio_item_id, title, summary, body)
            VALUES (?, ?, ?, ?)
            """,
            (portfolio_item_id, title, summary, body),
        )

    @staticmethod
    def _insert_derived_item(
        connection: sqlite3.Connection,
        draft: ProposalDraft,
        *,
        sensitivity: str,
        metadata: Mapping[str, object],
        now: str,
    ) -> sqlite3.Row:
        portfolio_item_id = str(uuid4())
        try:
            connection.execute(
                """
                INSERT INTO portfolio_items(
                    portfolio_item_id, slug, item_type, title, summary, body,
                    sensitivity, review_status, publication_status, created_at,
                    updated_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    portfolio_item_id,
                    draft.slug,
                    draft.item_type,
                    draft.title,
                    draft.summary,
                    draft.body,
                    sensitivity,
                    ReviewStatus.PROPOSED.value,
                    PublicationStatus.UNPUBLISHED.value,
                    now,
                    now,
                    canonical_json(metadata),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ReviewError(f"unable to create derived proposal: {error}") from error
        ReviewService._replace_fts(
            connection,
            portfolio_item_id,
            title=draft.title,
            summary=draft.summary,
            body=draft.body,
        )
        return ReviewService._require_item(connection, portfolio_item_id)

    @staticmethod
    def _supersede_item(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        proposal_hash: str,
        operation: str,
        reviewer_identity: str,
        reason: str,
        now: str,
    ) -> None:
        ReviewService._record_revision(
            connection,
            row,
            operation=operation,
            reviewer_identity=reviewer_identity,
            reason=reason,
            now=now,
        )
        ReviewService._record_review_decision(
            connection,
            portfolio_item_id=str(row["portfolio_item_id"]),
            proposal_hash=proposal_hash,
            decision=ReviewStatus.SUPERSEDED,
            reviewer_identity=reviewer_identity,
            reason=reason,
            now=now,
        )
        connection.execute(
            """
            UPDATE portfolio_items
            SET review_status = ?, publication_status = ?, updated_at = ?
            WHERE portfolio_item_id = ?
            """,
            (
                ReviewStatus.SUPERSEDED.value,
                PublicationStatus.SUPERSEDED.value,
                now,
                row["portfolio_item_id"],
            ),
        )

    def approve(
        self,
        portfolio_item_id: str,
        *,
        expected_proposal_sha256: str,
        reviewer_identity: str,
        reason: str | None = None,
    ) -> ReviewResult:
        if not reviewer_identity.strip():
            raise ValueError("reviewer_identity is required")
        review_id = str(uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_items WHERE portfolio_item_id = ?",
                (portfolio_item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown portfolio item: {portfolio_item_id}")
            current_hash = proposal_sha256(row)
            if current_hash != expected_proposal_sha256:
                raise ReviewConflictError(
                    "proposal changed after it was presented for review; refresh before approving"
                )
            publication_status = (
                PublicationStatus.CANDIDATE
                if row["sensitivity"] == Sensitivity.PUBLIC.value
                else PublicationStatus.UNPUBLISHED
            )
            connection.execute(
                """
                INSERT INTO review_decisions(
                    review_decision_id, portfolio_item_id, proposal_sha256, decision,
                    reviewer_identity, decided_at, reason, retention_protected
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    review_id,
                    portfolio_item_id,
                    current_hash,
                    ReviewStatus.APPROVED.value,
                    reviewer_identity,
                    now,
                    reason,
                ),
            )
            connection.execute(
                """
                UPDATE portfolio_items
                SET review_status = ?, publication_status = ?, updated_at = ?
                WHERE portfolio_item_id = ?
                """,
                (
                    ReviewStatus.APPROVED.value,
                    publication_status.value,
                    now,
                    portfolio_item_id,
                ),
            )
            connection.execute(
                """
                UPDATE claims SET status = 'approved'
                WHERE claim_id IN (
                    SELECT claim_id FROM portfolio_item_claims WHERE portfolio_item_id = ?
                )
                """,
                (portfolio_item_id,),
            )
            connection.execute(
                """
                UPDATE ownership_assertions SET review_status = ?
                WHERE entity_id IN (
                    SELECT subject_entity_id FROM claims
                    WHERE claim_id IN (
                        SELECT claim_id FROM portfolio_item_claims WHERE portfolio_item_id = ?
                    )
                )
                """,
                (ReviewStatus.APPROVED.value, portfolio_item_id),
            )
        self.database.append_audit_event(
            "PORTFOLIO_REVIEW_APPROVED",
            {
                "review_decision_id": review_id,
                "portfolio_item_id": portfolio_item_id,
                "proposal_sha256": current_hash,
                "reviewer_identity": reviewer_identity,
                "publication_status": publication_status.value,
            },
        )
        return ReviewResult(
            review_decision_id=review_id,
            portfolio_item_id=portfolio_item_id,
            proposal_sha256=current_hash,
            decision=ReviewStatus.APPROVED,
            publication_status=publication_status,
        )

    def reject(
        self,
        portfolio_item_id: str,
        *,
        expected_proposal_sha256: str,
        reviewer_identity: str,
        reason: str,
    ) -> ReviewResult:
        if not reviewer_identity.strip() or not reason.strip():
            raise ValueError("reviewer_identity and rejection reason are required")
        review_id = str(uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_items WHERE portfolio_item_id = ?",
                (portfolio_item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown portfolio item: {portfolio_item_id}")
            current_hash = proposal_sha256(row)
            if current_hash != expected_proposal_sha256:
                raise ReviewConflictError(
                    "proposal changed after it was presented for review; refresh before rejecting"
                )
            connection.execute(
                """
                INSERT INTO review_decisions(
                    review_decision_id, portfolio_item_id, proposal_sha256, decision,
                    reviewer_identity, decided_at, reason, retention_protected
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    review_id,
                    portfolio_item_id,
                    current_hash,
                    ReviewStatus.REJECTED.value,
                    reviewer_identity,
                    now,
                    reason,
                ),
            )
            connection.execute(
                """
                UPDATE portfolio_items
                SET review_status = ?, publication_status = ?, updated_at = ?
                WHERE portfolio_item_id = ?
                """,
                (
                    ReviewStatus.REJECTED.value,
                    PublicationStatus.UNPUBLISHED.value,
                    now,
                    portfolio_item_id,
                ),
            )
        self.database.append_audit_event(
            "PORTFOLIO_REVIEW_REJECTED",
            {
                "review_decision_id": review_id,
                "portfolio_item_id": portfolio_item_id,
                "proposal_sha256": current_hash,
                "reviewer_identity": reviewer_identity,
                "reason": reason,
            },
        )
        return ReviewResult(
            review_decision_id=review_id,
            portfolio_item_id=portfolio_item_id,
            proposal_sha256=current_hash,
            decision=ReviewStatus.REJECTED,
            publication_status=PublicationStatus.UNPUBLISHED,
        )

    def supersede_claim(
        self,
        claim_id: str,
        *,
        replacement_claim_id: str,
        expected_claim_sha256: str,
        reviewer_identity: str,
        reason: str,
    ) -> ClaimSupersessionResult:
        self._validate_identity_reason(reviewer_identity, reason)
        if claim_id == replacement_claim_id:
            raise ValueError("replacement claim must be distinct")
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = self._require_claim(connection, claim_id)
            replacement = self._require_claim(connection, replacement_claim_id)
            if source["superseded_by_claim_id"] is not None:
                raise ReviewError("source claim is already superseded")
            if replacement["superseded_by_claim_id"] is not None:
                raise ReviewError("replacement claim is already superseded")
            if (
                source["subject_entity_id"] != replacement["subject_entity_id"]
                or source["predicate"] != replacement["predicate"]
            ):
                raise ReviewError("claim supersession requires the same subject and predicate")
            current_hash = self._claim_sha256(source)
            if current_hash != expected_claim_sha256:
                raise ReviewConflictError(
                    "claim changed after it was presented for supersession; refresh first"
                )
            affected_rows = connection.execute(
                """
                SELECT DISTINCT pi.*
                FROM portfolio_items pi
                JOIN portfolio_item_claims pic
                  ON pic.portfolio_item_id = pi.portfolio_item_id
                WHERE pic.claim_id = ?
                ORDER BY pi.created_at, pi.portfolio_item_id
                """,
                (claim_id,),
            ).fetchall()
            affected_ids = tuple(str(row["portfolio_item_id"]) for row in affected_rows)
            for row in affected_rows:
                self._record_revision(
                    connection,
                    row,
                    operation="claim_supersede",
                    reviewer_identity=reviewer_identity,
                    reason=reason,
                    now=now,
                )
            review_id = self._record_review_decision(
                connection,
                claim_id=claim_id,
                proposal_hash=current_hash,
                decision=ReviewStatus.SUPERSEDED,
                reviewer_identity=reviewer_identity,
                reason=reason,
                now=now,
            )
            connection.execute(
                """
                UPDATE claims
                SET status = ?, superseded_by_claim_id = ?
                WHERE claim_id = ?
                """,
                (ReviewStatus.SUPERSEDED.value, replacement_claim_id, claim_id),
            )
            if affected_ids:
                placeholders = ",".join("?" for _ in affected_ids)
                connection.execute(
                    f"""
                    UPDATE portfolio_items
                    SET review_status = ?, publication_status = ?, updated_at = ?
                    WHERE portfolio_item_id IN ({placeholders})
                    """,
                    (
                        ReviewStatus.PROPOSED.value,
                        PublicationStatus.UNPUBLISHED.value,
                        now,
                        *affected_ids,
                    ),
                )
        self.database.append_audit_event(
            "CLAIM_SUPERSEDED",
            {
                "review_decision_id": review_id,
                "claim_id": claim_id,
                "replacement_claim_id": replacement_claim_id,
                "claim_sha256": current_hash,
                "reviewer_identity": reviewer_identity,
                "reason": reason,
                "affected_portfolio_item_ids": affected_ids,
            },
        )
        return ClaimSupersessionResult(
            review_decision_id=review_id,
            claim_id=claim_id,
            replacement_claim_id=replacement_claim_id,
            claim_sha256=current_hash,
            affected_portfolio_item_ids=affected_ids,
        )

    def redact(
        self,
        portfolio_item_id: str,
        *,
        expected_proposal_sha256: str,
        title: str,
        summary: str,
        body: str,
        reviewer_identity: str,
        reason: str,
    ) -> RedactionResult:
        self._validate_identity_reason(reviewer_identity, reason)
        draft = self._validate_draft(
            ProposalDraft(
                slug="preserved",
                item_type="preserved",
                title=title,
                summary=summary,
                body=body,
            )
        )
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_item(connection, portfolio_item_id)
            current_hash = self._require_hash(row, expected_proposal_sha256, "redaction")
            self._record_revision(
                connection,
                row,
                operation="redact",
                reviewer_identity=reviewer_identity,
                reason=reason,
                now=now,
            )
            review_id = self._record_review_decision(
                connection,
                portfolio_item_id=portfolio_item_id,
                proposal_hash=current_hash,
                decision=ReviewStatus.REDACTED,
                reviewer_identity=reviewer_identity,
                reason=reason,
                now=now,
            )
            connection.execute(
                """
                UPDATE portfolio_items
                SET title = ?, summary = ?, body = ?, review_status = ?,
                    publication_status = ?, updated_at = ?
                WHERE portfolio_item_id = ?
                """,
                (
                    draft.title,
                    draft.summary,
                    draft.body,
                    ReviewStatus.PROPOSED.value,
                    PublicationStatus.UNPUBLISHED.value,
                    now,
                    portfolio_item_id,
                ),
            )
            self._replace_fts(
                connection,
                portfolio_item_id,
                title=draft.title,
                summary=draft.summary,
                body=draft.body,
            )
            updated = self._require_item(connection, portfolio_item_id)
            updated_hash = proposal_sha256(updated)
        self.database.append_audit_event(
            "PORTFOLIO_REVIEW_REDACTED",
            {
                "review_decision_id": review_id,
                "portfolio_item_id": portfolio_item_id,
                "previous_proposal_sha256": current_hash,
                "proposal_sha256": updated_hash,
                "reviewer_identity": reviewer_identity,
                "reason": reason,
            },
        )
        return RedactionResult(
            review_decision_id=review_id,
            portfolio_item_id=portfolio_item_id,
            previous_proposal_sha256=current_hash,
            proposal_sha256=updated_hash,
        )

    def merge(
        self,
        source_proposal_sha256: Mapping[str, str],
        *,
        draft: ProposalDraft,
        reviewer_identity: str,
        reason: str,
    ) -> DerivationResult:
        self._validate_identity_reason(reviewer_identity, reason)
        derived_draft = self._validate_draft(draft)
        source_ids = tuple(sorted(source_proposal_sha256))
        if len(source_ids) < 2:
            raise ValueError("merge requires at least two distinct source proposals")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("merge source proposals must be distinct")
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source_rows: list[sqlite3.Row] = []
            source_hashes: dict[str, str] = {}
            for source_id in source_ids:
                row = self._require_item(connection, source_id)
                if row["review_status"] == ReviewStatus.SUPERSEDED.value:
                    raise ReviewError(f"source proposal is already superseded: {source_id}")
                source_rows.append(row)
                source_hashes[source_id] = self._require_hash(
                    row,
                    source_proposal_sha256[source_id],
                    "merge",
                )
            try:
                sensitivity = max(
                    (str(row["sensitivity"]) for row in source_rows),
                    key=_SENSITIVITY_RANK.__getitem__,
                )
            except KeyError as error:
                raise ReviewError(f"unknown source sensitivity: {error.args[0]}") from error
            derived = self._insert_derived_item(
                connection,
                derived_draft,
                sensitivity=sensitivity,
                metadata={
                    "lineage": {
                        "operation": "merge",
                        "source_portfolio_item_ids": source_ids,
                    }
                },
                now=now,
            )
            derived_id = str(derived["portfolio_item_id"])
            for row in source_rows:
                source_id = str(row["portfolio_item_id"])
                connection.execute(
                    """
                    INSERT OR IGNORE INTO portfolio_item_claims(portfolio_item_id, claim_id)
                    SELECT ?, claim_id FROM portfolio_item_claims
                    WHERE portfolio_item_id = ?
                    """,
                    (derived_id, source_id),
                )
                self._supersede_item(
                    connection,
                    row,
                    proposal_hash=source_hashes[source_id],
                    operation="merge",
                    reviewer_identity=reviewer_identity,
                    reason=reason,
                    now=now,
                )
                connection.execute(
                    """
                    INSERT INTO portfolio_item_lineage(
                        portfolio_item_lineage_id, source_portfolio_item_id,
                        derived_portfolio_item_id, operation, source_proposal_sha256,
                        reviewer_identity, reason, created_at
                    ) VALUES (?, ?, ?, 'merge', ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        source_id,
                        derived_id,
                        source_hashes[source_id],
                        reviewer_identity,
                        reason,
                        now,
                    ),
                )
            derived_hash = proposal_sha256(derived)
        self.database.append_audit_event(
            "PORTFOLIO_PROPOSALS_MERGED",
            {
                "source_portfolio_item_ids": source_ids,
                "source_proposal_sha256": source_hashes,
                "derived_portfolio_item_id": derived_id,
                "derived_proposal_sha256": derived_hash,
                "reviewer_identity": reviewer_identity,
                "reason": reason,
            },
        )
        return DerivationResult(
            operation="merge",
            source_portfolio_item_ids=source_ids,
            derived_portfolio_item_ids=(derived_id,),
            derived_proposal_sha256=(derived_hash,),
        )

    def split(
        self,
        portfolio_item_id: str,
        *,
        expected_proposal_sha256: str,
        drafts: tuple[ProposalDraft, ...],
        reviewer_identity: str,
        reason: str,
    ) -> DerivationResult:
        self._validate_identity_reason(reviewer_identity, reason)
        if len(drafts) < 2:
            raise ValueError("split requires at least two derived proposals")
        derived_drafts = tuple(self._validate_draft(draft) for draft in drafts)
        slugs = [draft.slug for draft in derived_drafts]
        if len(slugs) != len(set(slugs)):
            raise ValueError("split proposal slugs must be unique")
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = self._require_item(connection, portfolio_item_id)
            if source["review_status"] == ReviewStatus.SUPERSEDED.value:
                raise ReviewError("source proposal is already superseded")
            source_hash = self._require_hash(source, expected_proposal_sha256, "split")
            derived_rows: list[sqlite3.Row] = []
            for draft in derived_drafts:
                derived = self._insert_derived_item(
                    connection,
                    draft,
                    sensitivity=str(source["sensitivity"]),
                    metadata={
                        "lineage": {
                            "operation": "split",
                            "source_portfolio_item_id": portfolio_item_id,
                            "claim_allocation": "all_source_claims",
                        }
                    },
                    now=now,
                )
                derived_id = str(derived["portfolio_item_id"])
                connection.execute(
                    """
                    INSERT INTO portfolio_item_claims(portfolio_item_id, claim_id)
                    SELECT ?, claim_id FROM portfolio_item_claims
                    WHERE portfolio_item_id = ?
                    """,
                    (derived_id, portfolio_item_id),
                )
                connection.execute(
                    """
                    INSERT INTO portfolio_item_lineage(
                        portfolio_item_lineage_id, source_portfolio_item_id,
                        derived_portfolio_item_id, operation, source_proposal_sha256,
                        reviewer_identity, reason, created_at
                    ) VALUES (?, ?, ?, 'split', ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        portfolio_item_id,
                        derived_id,
                        source_hash,
                        reviewer_identity,
                        reason,
                        now,
                    ),
                )
                derived_rows.append(derived)
            self._supersede_item(
                connection,
                source,
                proposal_hash=source_hash,
                operation="split",
                reviewer_identity=reviewer_identity,
                reason=reason,
                now=now,
            )
            derived_ids = tuple(str(row["portfolio_item_id"]) for row in derived_rows)
            derived_hashes = tuple(proposal_sha256(row) for row in derived_rows)
        self.database.append_audit_event(
            "PORTFOLIO_PROPOSAL_SPLIT",
            {
                "source_portfolio_item_id": portfolio_item_id,
                "source_proposal_sha256": source_hash,
                "derived_portfolio_item_ids": derived_ids,
                "derived_proposal_sha256": derived_hashes,
                "reviewer_identity": reviewer_identity,
                "reason": reason,
            },
        )
        return DerivationResult(
            operation="split",
            source_portfolio_item_ids=(portfolio_item_id,),
            derived_portfolio_item_ids=derived_ids,
            derived_proposal_sha256=derived_hashes,
        )

    def edit_proposal(
        self,
        portfolio_item_id: str,
        *,
        expected_proposal_sha256: str,
        title: str,
        summary: str,
        body: str,
        reviewer_identity: str,
        reason: str,
    ) -> dict[str, Any]:
        self._validate_identity_reason(reviewer_identity, reason)
        draft = self._validate_draft(
            ProposalDraft(
                slug="preserved",
                item_type="preserved",
                title=title,
                summary=summary,
                body=body,
            )
        )
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_item(connection, portfolio_item_id)
            self._require_hash(row, expected_proposal_sha256, "editing")
            self._record_revision(
                connection,
                row,
                operation="edit",
                reviewer_identity=reviewer_identity,
                reason=reason,
                now=now,
            )
            connection.execute(
                """
                UPDATE portfolio_items
                SET title = ?, summary = ?, body = ?, review_status = ?,
                    publication_status = ?, updated_at = ?
                WHERE portfolio_item_id = ?
                """,
                (
                    draft.title,
                    draft.summary,
                    draft.body,
                    ReviewStatus.PROPOSED.value,
                    PublicationStatus.UNPUBLISHED.value,
                    now,
                    portfolio_item_id,
                ),
            )
            self._replace_fts(
                connection,
                portfolio_item_id,
                title=draft.title,
                summary=draft.summary,
                body=draft.body,
            )
        return self.get_item(portfolio_item_id)

    def revoke(
        self,
        portfolio_item_id: str,
        *,
        expected_proposal_sha256: str,
        reviewer_identity: str,
        reason: str,
    ) -> str:
        if not reviewer_identity.strip() or not reason.strip():
            raise ValueError("reviewer_identity and revocation reason are required")
        revocation_id = str(uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM portfolio_items WHERE portfolio_item_id = ?",
                (portfolio_item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown portfolio item: {portfolio_item_id}")
            current_hash = proposal_sha256(row)
            if current_hash != expected_proposal_sha256:
                raise ReviewConflictError(
                    "proposal changed after it was presented for revocation; refresh first"
                )
            publication = connection.execute(
                """
                SELECT pi.publication_version_id
                FROM publication_items pi
                JOIN publication_versions pv
                  ON pv.publication_version_id = pi.publication_version_id
                WHERE pi.portfolio_item_id = ?
                ORDER BY pv.version_number DESC LIMIT 1
                """,
                (portfolio_item_id,),
            ).fetchone()
            if publication is None:
                raise ReviewError("portfolio item has not been published")
            connection.execute(
                """
                INSERT INTO revocations(
                    revocation_id, publication_version_id, portfolio_item_id,
                    reason, revoked_at, reviewer_identity
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    revocation_id,
                    publication["publication_version_id"],
                    portfolio_item_id,
                    reason,
                    now,
                    reviewer_identity,
                ),
            )
            connection.execute(
                """
                UPDATE portfolio_items
                SET publication_status = ?, updated_at = ?
                WHERE portfolio_item_id = ?
                """,
                (PublicationStatus.REVOKED.value, now, portfolio_item_id),
            )
        self.database.append_audit_event(
            "PORTFOLIO_ITEM_REVOKED",
            {
                "revocation_id": revocation_id,
                "portfolio_item_id": portfolio_item_id,
                "proposal_sha256": current_hash,
                "reviewer_identity": reviewer_identity,
                "reason": reason,
            },
        )
        return revocation_id
