from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str


MIGRATIONS = (
    Migration(
        1,
        "core_schema",
        r"""
CREATE TABLE operator_sessions (
    session_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ended_at TEXT,
    last_verified_action_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE approved_origins (
    origin_id TEXT PRIMARY KEY,
    scheme TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER,
    allowed_path_prefix TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    UNIQUE (scheme, host, port, allowed_path_prefix)
) STRICT;

CREATE TABLE source_accounts (
    source_account_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    account_identifier TEXT NOT NULL,
    display_name TEXT,
    ownership_status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE (site_id, account_identifier)
) STRICT;

CREATE TABLE source_pages (
    source_page_id TEXT PRIMARY KEY,
    source_account_id TEXT REFERENCES source_accounts(source_account_id),
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    visibility TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE capture_artifacts (
    capture_artifact_id TEXT PRIMARY KEY,
    source_page_id TEXT REFERENCES source_pages(source_page_id),
    parent_artifact_id TEXT REFERENCES capture_artifacts(capture_artifact_id),
    sha256 TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
    captured_at TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    redacted INTEGER NOT NULL DEFAULT 0 CHECK (redacted IN (0, 1)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE observations (
    observation_id TEXT PRIMARY KEY,
    source_page_id TEXT REFERENCES source_pages(source_page_id),
    capture_artifact_id TEXT REFERENCES capture_artifacts(capture_artifact_id),
    observation_kind TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    bbox_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(bbox_json)),
    confidence REAL,
    observed_at TEXT NOT NULL,
    retention_protected INTEGER NOT NULL DEFAULT 0 CHECK (retention_protected IN (0, 1)),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE ui_targets (
    target_id TEXT PRIMARY KEY,
    observation_id TEXT REFERENCES observations(observation_id),
    role TEXT,
    accessible_name TEXT,
    target_text TEXT,
    bbox_json TEXT NOT NULL CHECK (json_valid(bbox_json)),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    visible INTEGER NOT NULL CHECK (visible IN (0, 1)),
    confidence REAL NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE browser_actions (
    action_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES operator_sessions(session_id),
    target_id TEXT REFERENCES ui_targets(target_id),
    risk_level TEXT NOT NULL,
    action_type TEXT NOT NULL,
    expected_postcondition_json TEXT NOT NULL CHECK (json_valid(expected_postcondition_json)),
    before_state_sha256 TEXT NOT NULL,
    after_state_sha256 TEXT,
    approval_id TEXT,
    result TEXT NOT NULL,
    failure_reason TEXT,
    created_at TEXT NOT NULL,
    verified_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE audit_events (
    audit_event_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES operator_sessions(session_id),
    event_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    previous_event_sha256 TEXT,
    event_sha256 TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE incidents (
    incident_id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES operator_sessions(session_id),
    severity TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    evidence_manifest_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(evidence_manifest_json))
) STRICT;

CREATE TABLE entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    superseded_by_entity_id TEXT REFERENCES entities(entity_id)
) STRICT;

CREATE TABLE entity_aliases (
    entity_alias_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    alias TEXT NOT NULL,
    source_observation_id TEXT REFERENCES observations(observation_id),
    UNIQUE (entity_id, alias)
) STRICT;

CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY,
    subject_entity_id TEXT REFERENCES entities(entity_id),
    predicate TEXT NOT NULL,
    object_entity_id TEXT REFERENCES entities(entity_id),
    object_text TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    superseded_by_claim_id TEXT REFERENCES claims(claim_id),
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    CHECK (object_entity_id IS NOT NULL OR object_text IS NOT NULL)
) STRICT;

CREATE TABLE claim_evidence (
    claim_evidence_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    observation_id TEXT NOT NULL REFERENCES observations(observation_id),
    evidence_role TEXT NOT NULL,
    quote_start INTEGER,
    quote_end INTEGER,
    UNIQUE (claim_id, observation_id, evidence_role)
) STRICT;

CREATE TABLE relationships (
    relationship_id TEXT PRIMARY KEY,
    subject_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    predicate TEXT NOT NULL,
    object_entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE ownership_assertions (
    ownership_assertion_id TEXT PRIMARY KEY,
    entity_id TEXT REFERENCES entities(entity_id),
    claim_id TEXT REFERENCES claims(claim_id),
    ownership_class TEXT NOT NULL,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    review_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (entity_id IS NOT NULL OR claim_id IS NOT NULL)
) STRICT;

CREATE TABLE sensitivity_decisions (
    sensitivity_decision_id TEXT PRIMARY KEY,
    entity_id TEXT REFERENCES entities(entity_id),
    claim_id TEXT REFERENCES claims(claim_id),
    sensitivity TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK (entity_id IS NOT NULL OR claim_id IS NOT NULL)
) STRICT;

CREATE TABLE portfolio_items (
    portfolio_item_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    item_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    body TEXT NOT NULL,
    sensitivity TEXT NOT NULL,
    review_status TEXT NOT NULL,
    publication_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE TABLE portfolio_item_claims (
    portfolio_item_id TEXT NOT NULL REFERENCES portfolio_items(portfolio_item_id),
    claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    PRIMARY KEY (portfolio_item_id, claim_id)
) WITHOUT ROWID, STRICT;

CREATE TABLE review_decisions (
    review_decision_id TEXT PRIMARY KEY,
    portfolio_item_id TEXT REFERENCES portfolio_items(portfolio_item_id),
    claim_id TEXT REFERENCES claims(claim_id),
    proposal_sha256 TEXT NOT NULL,
    decision TEXT NOT NULL,
    reviewer_identity TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    reason TEXT,
    retention_protected INTEGER NOT NULL DEFAULT 1 CHECK (retention_protected IN (0, 1)),
    CHECK (portfolio_item_id IS NOT NULL OR claim_id IS NOT NULL)
) STRICT;

CREATE TABLE publication_versions (
    publication_version_id TEXT PRIMARY KEY,
    version_number INTEGER NOT NULL UNIQUE,
    manifest_sha256 TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    approved_review_sha256 TEXT NOT NULL,
    retention_protected INTEGER NOT NULL DEFAULT 1 CHECK (retention_protected IN (0, 1))
) STRICT;

CREATE TABLE publication_items (
    publication_version_id TEXT NOT NULL REFERENCES publication_versions(publication_version_id),
    portfolio_item_id TEXT NOT NULL REFERENCES portfolio_items(portfolio_item_id),
    item_sha256 TEXT NOT NULL,
    PRIMARY KEY (publication_version_id, portfolio_item_id)
) WITHOUT ROWID, STRICT;

CREATE TABLE publication_assets (
    publication_version_id TEXT NOT NULL REFERENCES publication_versions(publication_version_id),
    capture_artifact_id TEXT NOT NULL REFERENCES capture_artifacts(capture_artifact_id),
    public_relative_path TEXT NOT NULL,
    asset_sha256 TEXT NOT NULL,
    PRIMARY KEY (publication_version_id, capture_artifact_id)
) WITHOUT ROWID, STRICT;

CREATE TABLE revocations (
    revocation_id TEXT PRIMARY KEY,
    publication_version_id TEXT NOT NULL REFERENCES publication_versions(publication_version_id),
    portfolio_item_id TEXT REFERENCES portfolio_items(portfolio_item_id),
    reason TEXT NOT NULL,
    revoked_at TEXT NOT NULL,
    reviewer_identity TEXT NOT NULL
) STRICT;
""",
    ),
    Migration(
        2,
        "fts_indexes",
        r"""
CREATE VIRTUAL TABLE observations_fts USING fts5(
    observation_id UNINDEXED,
    raw_text,
    normalized_text
);

CREATE VIRTUAL TABLE entities_fts USING fts5(
    entity_id UNINDEXED,
    canonical_name,
    aliases
);

CREATE VIRTUAL TABLE portfolio_fts USING fts5(
    portfolio_item_id UNINDEXED,
    title,
    summary,
    body
);
""",
    ),
    Migration(
        3,
        "query_indexes",
        r"""
CREATE INDEX source_pages_url_idx ON source_pages(url);
CREATE INDEX observations_page_idx ON observations(source_page_id, observed_at);
CREATE INDEX observations_capture_idx ON observations(capture_artifact_id);
CREATE INDEX browser_actions_session_idx ON browser_actions(session_id, created_at);
CREATE INDEX audit_events_session_idx ON audit_events(session_id, created_at);
CREATE INDEX claims_subject_idx ON claims(subject_entity_id, predicate);
CREATE INDEX claim_evidence_claim_idx ON claim_evidence(claim_id);
CREATE INDEX ownership_entity_idx ON ownership_assertions(entity_id, ownership_class);
CREATE INDEX portfolio_status_idx
    ON portfolio_items(review_status, publication_status, sensitivity);
""",
    ),
    Migration(
        4,
        "portfolio_revision_and_lineage",
        r"""
CREATE TABLE portfolio_item_revisions (
    portfolio_item_revision_id TEXT PRIMARY KEY,
    portfolio_item_id TEXT NOT NULL REFERENCES portfolio_items(portfolio_item_id),
    proposal_sha256 TEXT NOT NULL,
    proposal_payload_json TEXT NOT NULL CHECK (json_valid(proposal_payload_json)),
    operation TEXT NOT NULL,
    reviewer_identity TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    retention_protected INTEGER NOT NULL DEFAULT 1 CHECK (retention_protected IN (0, 1))
) STRICT;

CREATE TABLE portfolio_item_lineage (
    portfolio_item_lineage_id TEXT PRIMARY KEY,
    source_portfolio_item_id TEXT NOT NULL REFERENCES portfolio_items(portfolio_item_id),
    derived_portfolio_item_id TEXT NOT NULL REFERENCES portfolio_items(portfolio_item_id),
    operation TEXT NOT NULL CHECK (operation IN ('merge', 'split')),
    source_proposal_sha256 TEXT NOT NULL,
    reviewer_identity TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (source_portfolio_item_id, derived_portfolio_item_id, operation)
) STRICT;

CREATE INDEX portfolio_revisions_item_idx
    ON portfolio_item_revisions(portfolio_item_id, created_at);
CREATE INDEX portfolio_lineage_source_idx
    ON portfolio_item_lineage(source_portfolio_item_id, operation);
CREATE INDEX portfolio_lineage_derived_idx
    ON portfolio_item_lineage(derived_portfolio_item_id, operation);
""",
    ),
    Migration(
        5,
        "operator_control_requests",
        r"""
CREATE TABLE operator_control_requests (
    control_request_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES operator_sessions(session_id),
    command TEXT NOT NULL CHECK (command IN ('pause', 'resume', 'stop')),
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'acknowledged', 'rejected')),
    requested_at TEXT NOT NULL,
    acknowledged_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE INDEX operator_control_session_idx
    ON operator_control_requests(session_id, status, requested_at);
""",
    ),
    Migration(
        6,
        "site_scope_approvals",
        r"""
CREATE TABLE site_scope_approvals (
    site_scope_approval_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    policy_sha256 TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    expires_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    scope_summary TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE (site_id, policy_sha256, approved_by)
) STRICT;

CREATE INDEX site_scope_approvals_lookup_idx
    ON site_scope_approvals(site_id, policy_sha256, status, expires_at);
""",
    ),
    Migration(
        7,
        "at_rest_acceptances",
        r"""
CREATE TABLE at_rest_acceptances (
    at_rest_acceptance_id TEXT PRIMARY KEY,
    protection_kind TEXT NOT NULL CHECK (protection_kind IN ('full_disk_encryption')),
    accepted_by TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    expires_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    evidence_summary TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE INDEX at_rest_acceptances_lookup_idx
    ON at_rest_acceptances(protection_kind, status, expires_at);
""",
    ),
)

LATEST_SCHEMA_VERSION = MIGRATIONS[-1].version
