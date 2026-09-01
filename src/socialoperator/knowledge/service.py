from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from socialoperator.browser.actions import observation_sha256
from socialoperator.browser.models import PageObservation
from socialoperator.config import SitePolicy
from socialoperator.knowledge.database import Database, canonical_json, utc_now
from socialoperator.ocr.engine import OcrResult
from socialoperator.policy.domains import is_url_allowed
from socialoperator.policy.relevance import ScopeClassifier, ScopeDecision
from socialoperator.types import PublicationStatus, ReviewStatus


class KnowledgePolicyError(RuntimeError):
    """Raised when observed material is outside the accepted knowledge policy."""


@dataclass(frozen=True, slots=True)
class PortfolioProposal:
    portfolio_item_id: str
    proposal_sha256: str
    source_page_id: str
    entity_id: str
    claim_id: str
    decision: ScopeDecision


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "portfolio-item"


def proposal_payload(row: Any) -> dict[str, object]:
    return {
        "portfolio_item_id": str(row["portfolio_item_id"]),
        "slug": str(row["slug"]),
        "item_type": str(row["item_type"]),
        "title": str(row["title"]),
        "summary": str(row["summary"]),
        "body": str(row["body"]),
        "sensitivity": str(row["sensitivity"]),
        "metadata": json.loads(str(row["metadata_json"])),
    }


def proposal_sha256(row: Any) -> str:
    encoded = json.dumps(proposal_payload(row), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class KnowledgeService:
    def __init__(
        self, database: Database, *, scope_classifier: ScopeClassifier | None = None
    ) -> None:
        self.database = database
        self.scope_classifier = scope_classifier or ScopeClassifier()

    def ingest_page_observation(
        self,
        observation: PageObservation,
        *,
        site_policy: SitePolicy,
        ocr_result: OcrResult | None = None,
        capture_artifact_id: str | None = None,
    ) -> PortfolioProposal:
        if not is_url_allowed(observation.url, site_policy):
            raise KnowledgePolicyError(
                f"page URL is outside the approved site policy: {observation.url}"
            )
        combined_text = "\n".join(
            value
            for value in (observation.readable_text, ocr_result.text if ocr_result else "")
            if value
        )
        decision = self.scope_classifier.classify(combined_text, site_policy)
        if (
            not decision.accepted_for_private_knowledge
            or not decision.eligible_for_portfolio_review
        ):
            raise KnowledgePolicyError(
                f"page is not eligible for knowledge ingestion: {decision.ownership_class.value}"
            )
        account_identifier = site_policy.account_identifiers[0]
        source_account_id = str(
            uuid5(NAMESPACE_URL, f"socialoperator:{site_policy.site_id}:{account_identifier}")
        )
        source_page_id = str(uuid4())
        entity_id = str(uuid4())
        claim_id = str(uuid4())
        portfolio_item_id = str(uuid4())
        observed_at = utc_now()
        title = observation.headings[0] if observation.headings else observation.title
        lines = [line.strip() for line in observation.readable_text.splitlines() if line.strip()]
        summary = next((line for line in lines if line != title), title)[:280]
        item_type = "project" if "project" in combined_text.lower() else "profile"
        content_hash = observation_sha256(observation)
        slug = _slugify(title)
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO source_accounts(
                    source_account_id, site_id, account_identifier, display_name,
                    ownership_status, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, account_identifier) DO UPDATE SET
                    display_name = excluded.display_name,
                    ownership_status = excluded.ownership_status
                """,
                (
                    source_account_id,
                    site_policy.site_id,
                    account_identifier,
                    account_identifier,
                    decision.ownership_class.value,
                    canonical_json({"policy": str(site_policy.source_path)}),
                ),
            )
            connection.execute(
                """
                INSERT INTO source_pages(
                    source_page_id, source_account_id, url, title, captured_at,
                    visibility, content_sha256, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_page_id,
                    source_account_id,
                    observation.url,
                    observation.title,
                    observed_at,
                    decision.sensitivity.value,
                    content_hash,
                    canonical_json({"headings": observation.headings}),
                ),
            )
        dom_observation_id = self.database.add_observation(
            source_page_id=source_page_id,
            capture_artifact_id=capture_artifact_id,
            observation_kind="dom_accessibility",
            raw_text=observation.readable_text,
            normalized_text=" ".join(observation.readable_text.split()),
            confidence=1.0,
            retention_protected=True,
            metadata={"aria_snapshot": observation.aria_snapshot},
        )
        if ocr_result is not None:
            self.database.add_observation(
                source_page_id=source_page_id,
                capture_artifact_id=capture_artifact_id,
                observation_kind="ocr",
                raw_text=ocr_result.text,
                normalized_text=" ".join(ocr_result.text.split()),
                confidence=(
                    sum(token.confidence for token in ocr_result.tokens) / len(ocr_result.tokens)
                    if ocr_result.tokens
                    else None
                ),
                retention_protected=True,
                metadata={
                    "engine": ocr_result.engine,
                    "engine_version": ocr_result.engine_version,
                    "soft_miss": ocr_result.soft_miss,
                },
            )
        now = utc_now()
        metadata = {
            "source_page_id": source_page_id,
            "ownership_class": decision.ownership_class.value,
            "ownership_reasons": decision.reasons,
        }
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO entities(
                    entity_id, entity_type, canonical_name, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (entity_id, item_type, title, canonical_json(metadata), now),
            )
            connection.execute(
                """
                INSERT INTO claims(
                    claim_id, subject_entity_id, predicate, object_text, status,
                    created_at, metadata_json
                ) VALUES (?, ?, 'description', ?, 'proposed', ?, ?)
                """,
                (claim_id, entity_id, observation.readable_text, now, canonical_json(metadata)),
            )
            connection.execute(
                """
                INSERT INTO claim_evidence(
                    claim_evidence_id, claim_id, observation_id, evidence_role
                ) VALUES (?, ?, ?, 'support')
                """,
                (str(uuid4()), claim_id, dom_observation_id),
            )
            connection.execute(
                """
                INSERT INTO ownership_assertions(
                    ownership_assertion_id, entity_id, ownership_class, reason,
                    confidence, review_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    entity_id,
                    decision.ownership_class.value,
                    "; ".join(decision.reasons),
                    decision.confidence,
                    ReviewStatus.PROPOSED.value,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO sensitivity_decisions(
                    sensitivity_decision_id, entity_id, sensitivity, reason, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    entity_id,
                    decision.sensitivity.value,
                    "deterministic scope policy",
                    now,
                ),
            )
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
                    slug,
                    item_type,
                    title,
                    summary,
                    observation.readable_text,
                    decision.sensitivity.value,
                    ReviewStatus.PROPOSED.value,
                    PublicationStatus.UNPUBLISHED.value,
                    now,
                    now,
                    canonical_json(metadata),
                ),
            )
            connection.execute(
                """
                INSERT INTO portfolio_item_claims(portfolio_item_id, claim_id)
                VALUES (?, ?)
                """,
                (portfolio_item_id, claim_id),
            )
            connection.execute(
                """
                INSERT INTO entities_fts(entity_id, canonical_name, aliases)
                VALUES (?, ?, '')
                """,
                (entity_id, title),
            )
            connection.execute(
                """
                INSERT INTO portfolio_fts(portfolio_item_id, title, summary, body)
                VALUES (?, ?, ?, ?)
                """,
                (portfolio_item_id, title, summary, observation.readable_text),
            )
            row = connection.execute(
                "SELECT * FROM portfolio_items WHERE portfolio_item_id = ?",
                (portfolio_item_id,),
            ).fetchone()
        return PortfolioProposal(
            portfolio_item_id=portfolio_item_id,
            proposal_sha256=proposal_sha256(row),
            source_page_id=source_page_id,
            entity_id=entity_id,
            claim_id=claim_id,
            decision=decision,
        )

    def list_proposals(self) -> list[dict[str, object]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM portfolio_items
                WHERE review_status = ?
                ORDER BY created_at, portfolio_item_id
                """,
                (ReviewStatus.PROPOSED.value,),
            ).fetchall()
        return [{**proposal_payload(row), "proposal_sha256": proposal_sha256(row)} for row in rows]
