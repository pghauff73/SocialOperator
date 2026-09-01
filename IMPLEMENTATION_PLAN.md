# SocialOperator Implementation Plan

**Plan version:** 0.1.0
**Date:** 2026-08-31
**Status:** Active implementation pending real-site and release approval
**Workspace:** repository root
**Current baseline:** Bootstrapped source tree with local synthetic-fixture evidence

## 1. Purpose

SocialOperator will be a supervised desktop browser operator that:

1. Opens a dedicated browser profile.
2. Pauses while the user performs login, MFA, passkey, or CAPTCHA steps.
3. Reads approved webpages using browser accessibility/DOM evidence plus screenshot OCR.
4. Moves the visible desktop mouse pointer and clicks buttons or links.
5. Verifies the result of every interaction before continuing.
6. Extracts only information created by, owned by, or directly about the user under explicit scope rules.
7. Stores observations, normalized knowledge, ownership decisions, and provenance in a private SQLite database.
8. Requires user review before knowledge is approved for publication.
9. Generates a separate sanitized public knowledge snapshot.
10. Renders a dynamic profile and portfolio website from the public snapshot.

This document is the execution and sequencing authority for the initial implementation. A completed work package is not sufficient to claim project completion. Completion requires all applicable local gates, master gates, validation suites, evidence records, and user approval described here.

## 2. Product Boundaries

### 2.1 In scope

- Linux/X11 as the first supported desktop environment.
- A headed Chromium-family browser in a dedicated profile.
- Manual login handoff to the user.
- Accessibility tree, DOM, screenshot, OCR, and visual target fusion.
- Visible desktop mouse movement, hover, click, scroll, and bounded keyboard navigation.
- Read-only navigation as the default operating mode.
- User-approved domain and path allowlists.
- Evidence-preserving extraction into SQLite.
- Ownership, relevance, sensitivity, and publication classification.
- Local review dashboard.
- Dynamic portfolio rendering from a sanitized public snapshot.
- Audit logs, recovery, rollback, deletion, export, and revocation.
- Deterministic local fixture sites and supervised real-site pilots.

### 2.2 Out of scope for the initial release

- Password entry, passkey handling, MFA entry, or CAPTCHA solving by the operator.
- Anti-bot evasion, stealth automation, rate-limit bypass, or terms-of-service circumvention.
- Autonomous posting, messaging, reactions, purchases, account changes, or deletion.
- General-purpose crawling of feeds, timelines, search results, or unrelated third-party material.
- Legal determination of copyright, ownership, licensing, or platform policy.
- Automatic publication without a user approval record.
- Cloud storage of the private knowledge base.
- Mobile browsers, Wayland, macOS, and Windows before the X11 release is accepted.
- An unrestricted LLM agent with direct browser, database, or publication authority.

## 3. Foundational Decisions

### 3.1 Hybrid perception is mandatory

OCR is required but is not the sole source of truth. The operator must combine:

- DOM and accessibility role/name/state.
- Element and viewport bounding boxes.
- Screenshot pixels.
- OCR text, confidence, and geometry.
- URL, page title, navigation state, and browser events.
- Before-and-after evidence for each action.

If evidence sources disagree and the conflict cannot be resolved deterministically, the operator must stop rather than click.

### 3.2 The physical pointer is a separate subsystem

The browser observer identifies targets. A native mouse adapter moves the visible system pointer. Browser-local synthetic input may be used for tests and diagnostics, but it does not replace native pointer acceptance tests.

### 3.3 Authentication remains user-controlled

The application may preserve a dedicated browser profile after the user logs in, but it must not record credentials or capture login secrets. Authentication screens create a privacy boundary in which screenshots, OCR, clipboard capture, and keystroke observation are disabled.

### 3.4 Knowledge and evidence are separate

An observation records what was seen. A claim records a normalized proposition. Evidence links a claim to one or more observations. A claim without evidence cannot be approved or published.

### 3.5 Private and public storage are physically separated

The private database is never deployed with the portfolio site. Publication creates a new sanitized snapshot containing only approved public records and assets.

### 3.6 Models are advisory only

Rules and deterministic parsers should perform navigation, authorization checks, target selection, provenance capture, and publication gating. A local or remote model may propose classification, summaries, tags, or entity matches, but its output remains unapproved until deterministic checks and user review succeed.

## 4. Initial Technology Baseline

The initial implementation should use a single Python application unless dependency validation proves that a split runtime is necessary.

- **Runtime:** Python, pinned by `pyproject.toml` and a reproducible lockfile.
- **Browser:** Playwright with headed Chromium and a persistent dedicated profile.
- **Native pointer:** adapter interface with an X11 implementation using PyAutoGUI or `xdotool`.
- **Screen capture:** native screenshot adapter, initially PyAutoGUI or MSS.
- **OCR:** installed Tesseract for the first engine; optional PaddleOCR adapter later.
- **Database:** Python `sqlite3`, SQLite migrations, foreign keys, WAL mode, FTS5, and JSON metadata.
- **Application API:** FastAPI or an equivalently small typed local HTTP service.
- **Admin UI:** server-rendered HTML with minimal JavaScript.
- **Portfolio UI:** server-rendered dynamic site backed only by the public snapshot.
- **Validation:** pytest, local fixture websites, golden screenshots, SQL integrity checks, and browser end-to-end tests.
- **Packaging:** local CLI plus service entry point; no privileged installation required for the MVP.

The local machine currently provides Python 3.14.6, Node 26.4.0, SQLite 3.53.3, Tesseract 5.5.2, X11, and Chrome. Dependency compatibility must be proven rather than assumed. If required Python packages do not support the system Python, the implementation must pin a supported Python interpreter instead of patching around incompatibilities.

## 5. Proposed Repository Structure

```text
SocialOperator/
├── IMPLEMENTATION_PLAN.md
├── README.md
├── pyproject.toml
├── uv.lock or equivalent lockfile
├── .gitignore
├── config/
│   ├── default.toml
│   ├── sites/
│   └── policies/
├── src/socialoperator/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── types.py
│   ├── browser/
│   │   ├── session.py
│   │   ├── login_handoff.py
│   │   ├── observer.py
│   │   ├── accessibility.py
│   │   ├── coordinate_map.py
│   │   ├── target_fusion.py
│   │   ├── native_mouse.py
│   │   ├── x11_mouse.py
│   │   ├── actions.py
│   │   └── navigator.py
│   ├── capture/
│   │   ├── screenshots.py
│   │   ├── artifacts.py
│   │   └── redaction.py
│   ├── ocr/
│   │   ├── engine.py
│   │   ├── tesseract.py
│   │   ├── paddle.py
│   │   └── normalization.py
│   ├── knowledge/
│   │   ├── database.py
│   │   ├── migrations.py
│   │   ├── repositories.py
│   │   ├── ownership.py
│   │   ├── extraction.py
│   │   ├── deduplication.py
│   │   └── publication.py
│   ├── policy/
│   │   ├── domains.py
│   │   ├── actions.py
│   │   ├── sensitivity.py
│   │   └── relevance.py
│   ├── audit/
│   │   ├── events.py
│   │   ├── sessions.py
│   │   └── recovery.py
│   ├── review/
│   │   ├── api.py
│   │   ├── views.py
│   │   └── forms.py
│   └── portfolio/
│       ├── app.py
│       ├── builder.py
│       └── manifests.py
├── migrations/
├── templates/
│   ├── review/
│   └── portfolio/
├── static/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   ├── golden/
│   ├── security/
│   └── e2e/
├── tools/
│   ├── run_fixture_site.py
│   ├── verify_database.py
│   ├── verify_public_snapshot.py
│   ├── build_source_manifest.py
│   └── package_evidence.py
├── data/
│   ├── private/
│   ├── public/
│   ├── artifacts/
│   └── runtime/
└── reports/
    ├── validation/
    ├── incidents/
    └── releases/
```

Runtime data, authentication profiles, databases, screenshots, downloads, logs containing private information, and generated public snapshots must be ignored by Git unless a specific sanitized fixture is intentionally checked in.

## 6. Functional Requirements

| ID | Requirement |
|---|---|
| FR-01 | Launch a dedicated headed browser profile without attaching to the user's ordinary browser profile. |
| FR-02 | Pause for manual login and resume only after explicit user input. |
| FR-03 | Disable capture and OCR while authentication-sensitive fields or pages are active. |
| FR-04 | Observe page structure through DOM/accessibility evidence and screenshots. |
| FR-05 | Produce OCR text with bounding boxes, confidence, engine identity, and capture provenance. |
| FR-06 | Identify interactive targets using fused DOM, accessibility, OCR, and pixel evidence. |
| FR-07 | Move the visible native mouse pointer to the selected target. |
| FR-08 | Verify hover alignment before clicking. |
| FR-09 | Verify the expected postcondition after every click or navigation action. |
| FR-10 | Scroll incrementally and preserve viewport and scroll provenance. |
| FR-11 | Restrict navigation to approved domains and allowed path patterns. |
| FR-12 | Classify observed material by ownership, relevance, sensitivity, and publication eligibility. |
| FR-13 | Store immutable source captures and append-only audit events. |
| FR-14 | Normalize observations into entities, claims, relationships, and portfolio candidates. |
| FR-15 | Link every normalized claim to exact source evidence. |
| FR-16 | Deduplicate without destroying competing evidence or prior observations. |
| FR-17 | Present proposed knowledge and portfolio items for user review. |
| FR-18 | Record approval, rejection, redaction, supersession, and revocation decisions. |
| FR-19 | Generate a physically separate public snapshot containing only approved public data. |
| FR-20 | Render the dynamic portfolio from the public snapshot. |
| FR-21 | Export and delete user data with verifiable manifests. |
| FR-22 | Recover from interruption without replaying unverified mouse actions. |
| FR-23 | Provide pause, resume, halt, and emergency-stop controls. |
| FR-24 | Produce a session report with sources visited, actions taken, records proposed, and failures. |

## 7. Safety And Privacy Requirements

| ID | Requirement |
|---|---|
| SP-01 | Never store passwords, one-time codes, passkeys, recovery codes, or raw authentication headers. |
| SP-02 | Never commit browser profiles, cookies, storage state, private databases, or sensitive screenshots. |
| SP-03 | Default to read-only actions. |
| SP-04 | Require explicit user approval for any action with an external side effect. |
| SP-05 | Block destructive, financial, account-security, and remote-content mutation actions in the initial release. |
| SP-06 | Stop on ambiguous targets, evidence conflicts, domain violations, CAPTCHA, or unexpected dialogs. |
| SP-07 | Redact SocialOperator's own windows and private overlays from OCR input. |
| SP-08 | Exclude third-party private information unless explicitly authorized and necessary. |
| SP-09 | Never publish from the private database directly. |
| SP-10 | Require evidence and user approval for every published portfolio item. |
| SP-11 | Use least-privilege file permissions for profiles, databases, artifacts, and reports. |
| SP-12 | Record all approvals with timestamp, item/action hash, and approving user identity. |
| SP-13 | Fail closed when ownership or publication eligibility cannot be established. |
| SP-14 | Do not automatically retry actions that may have succeeded remotely but failed local verification. |
| SP-15 | Do not use an LLM decision as the sole basis for clicking, ownership, sensitivity, or publication. |

## 8. Initial Ownership And Relevance Taxonomy

Every candidate record must receive one ownership class:

- `created_by_user`
- `owned_by_user`
- `about_user`
- `authorized_account_export`
- `third_party_reference`
- `uncertain`
- `excluded`

Every candidate must also receive:

- `relevance_reason`
- `ownership_reason`
- `source_account_id`
- `source_page_id`
- `sensitivity`
- `confidence`
- `review_status`
- `publication_status`

Starting publication policy:

| Ownership class | Private storage | Review eligibility | Automatic publication |
|---|---:|---:|---:|
| `created_by_user` | Yes | Yes | Never |
| `owned_by_user` | Yes | Yes | Never |
| `about_user` | Yes, if relevant | Yes, explicit confirmation | Never |
| `authorized_account_export` | Yes | Case-specific | Never |
| `third_party_reference` | Minimal metadata only | Case-specific | Never |
| `uncertain` | Quarantine only | Ownership review | Never |
| `excluded` | No, except rejection audit | No | Never |

## 9. Action Risk Model

| Level | Examples | Initial behavior |
|---|---|---|
| A0 Observe | screenshot, DOM read, OCR, page title | Automatic within allowlist |
| A1 Navigate | scroll, expand section, follow internal read-only link | Automatic with verification |
| A2 Boundary | new domain, download, popup, file preview | Pause and request approval |
| A3 External effect | like, follow, message, upload, submit, edit remote content | Blocked until a later approved release |
| A4 Destructive/security | delete, purchase, password, MFA, account settings | Always blocked |

An action record must include target evidence, risk level, expected postcondition, approval reference when applicable, before-state hash, after-state hash, result, and failure reason.

## 10. Operator State Machine

```text
STOPPED
  -> STARTING
  -> LOGIN_REQUIRED
  -> READY
  -> OBSERVING
  -> PLANNING_ACTION
  -> AWAITING_APPROVAL (when required)
  -> MOVING_POINTER
  -> VERIFYING_HOVER
  -> CLICKING
  -> VERIFYING_RESULT
  -> READY
```

Any state may transition to `PAUSED` or `HALTED`. Restart after a crash must enter `PAUSED_RECOVERY`; it must not replay the last action automatically.

## 11. Knowledge Lifecycle

```text
OBSERVED
  -> CLASSIFIED
  -> NORMALIZED
  -> PROPOSED
  -> USER_REVIEWED
  -> APPROVED
  -> PUBLISHED
  -> SUPERSEDED or REVOKED
```

Rejected and superseded records remain auditable. They must not disappear through ordinary deduplication or retention pruning.

## 12. SQLite Data Model

The initial schema must include at least the following canonical tables:

### 12.1 Operational tables

- `schema_migrations`
- `operator_sessions`
- `approved_origins`
- `source_accounts`
- `source_pages`
- `capture_artifacts`
- `observations`
- `ui_targets`
- `browser_actions`
- `audit_events`
- `incidents`

### 12.2 Knowledge tables

- `entities`
- `entity_aliases`
- `claims`
- `claim_evidence`
- `relationships`
- `ownership_assertions`
- `sensitivity_decisions`
- `portfolio_items`
- `portfolio_item_claims`
- `review_decisions`

### 12.3 Publication tables

- `publication_versions`
- `publication_items`
- `publication_assets`
- `revocations`

### 12.4 Search tables

- `observations_fts`
- `entities_fts`
- `portfolio_fts`

### 12.5 Required database invariants

- Foreign keys are enabled on every connection.
- Migrations are transactional and monotonically numbered.
- Source captures are immutable after insertion.
- Claims may be superseded but not silently overwritten.
- Every claim has at least one `claim_evidence` row before approval.
- Every published item points to an approved review decision.
- Public snapshot creation excludes all non-public sensitivity values.
- Authentication secrets have no schema destination.
- Content hashes use a single documented algorithm and canonical serialization.
- Database integrity and foreign-key checks run before and after publication.

## 13. Artifact And Provenance Model

Captured files should be stored under a content-addressed layout:

```text
data/private/artifacts/sha256/ab/cd/<full-hash>
```

Each artifact record must include:

- Hash algorithm and digest.
- Media type.
- Byte length.
- Original source URL when applicable.
- Capture session and timestamp.
- Browser viewport and device scale.
- Window geometry and scroll position.
- Redaction status.
- OCR engine and version when derived.
- Parent artifact when cropped or transformed.
- Sensitivity and retention class.

Derived OCR text, thumbnails, crops, and normalized documents must retain a parent reference rather than becoming independent unverifiable facts.

## 14. Evidence Classes

| Evidence | Description |
|---|---|
| E0 | User-approved scope, ownership policy, and action policy. |
| E1 | Reproducible environment manifest and dependency lock. |
| E2 | Source-tree manifest or Git commit hash. |
| E3 | Unit, integration, security, and end-to-end test output. |
| E4 | Browser screenshots, OCR results, DOM/accessibility snapshots, and action traces. |
| E5 | SQLite integrity checks, migration checks, and data-invariant reports. |
| E6 | Requirement-to-test and requirement-to-evidence coverage matrices. |
| E7 | Security and privacy review report. |
| E8 | Public snapshot diff, secret scan, and publication manifest. |
| E9 | User approval records bound to exact action or publication hashes. |
| E10 | Pilot session report and rollback/revocation proof. |

Evidence must be generated from the current source and current data. Historical green reports do not certify a changed tree or database.

## 15. Master Gates

| Gate | Requirement |
|---|---|
| G0 Plan acceptance | User approves scope, non-goals, action levels, ownership classes, and publication model. |
| G1 Reproducible foundation | Environment installs from lockfile; CLI, tests, and fixture server start from a clean checkout. |
| G2 Authentication boundary | Manual login works; capture is disabled during sensitive authentication; secrets do not enter logs or DB. |
| G3 Perception | DOM/accessibility, screenshot, OCR, redaction, and coordinate mapping pass fixture acceptance thresholds. |
| G4 Safe native interaction | Visible pointer movement, hover verification, click verification, ambiguity halt, and emergency stop pass. |
| G5 Provenance knowledge base | Schema, migrations, immutable evidence, claim links, deduplication, and integrity checks pass. |
| G6 Review authority | No item can become approved without an exact user decision; rejected and superseded history is retained. |
| G7 Publication isolation | Public snapshot is physically separate, contains only approved public fields, and passes privacy/secret tests. |
| G8 Site adapter pilot | One user-selected real site operates within approved scope without unverified clicks or unrelated ingestion. |
| G9 Reliability and security | Recovery, interruption, timeout, rate limit, popup, redirect, download, and privacy failure tests pass. |
| G10 Release readiness | Full validation, evidence package, current hashes, documentation, rollback, and explicit user release approval exist. |

No master gate may be waived silently. A waiver requires a written rationale, affected requirements, risk owner, expiration condition, and user approval.

## 16. Starting Acceptance Thresholds

These are initial engineering thresholds. Changes require a recorded decision and rationale.

- Native pointer fixture accuracy: at least 99 correct target acquisitions in 100 deterministic trials.
- Click-outside-target events: zero.
- Unapproved external side effects: zero.
- Domain allowlist violations resulting in action: zero.
- Credential strings persisted in logs, screenshots, database, or reports: zero.
- Published records without evidence and approval: zero.
- Private records present in the public snapshot: zero.
- OCR normalized text F1 on golden fixtures: at least 0.95 for supported English page text.
- OCR bounding-box intersection-over-union median: at least 0.70 on golden fixtures.
- Pointer-region OCR p95: no more than 500 ms on the target host after warmup.
- Full-viewport OCR p95: no more than 3 seconds on the target host after warmup.
- Action postcondition verification timeout: bounded and configurable; default 10 seconds.
- Automatic retries per read-only action: maximum two.
- Automatic retries for actions with possible external effects: zero.
- SQLite `integrity_check` and `foreign_key_check`: clean.
- Requirement coverage at release: 100 percent mapped to code, test, evidence, or explicit deferred status.

## 17. Work Packages

### WP00 — Plan Acceptance And Governance

**Dependencies:** None
**Goal:** Establish exact authority, scope, and completion semantics before implementation.

Microsteps:

1. Review this plan with the user.
2. Confirm the first supported operating system and display server.
3. Confirm whether mouse movement must always be physically visible.
4. Confirm initial approved websites or leave real-site selection deferred.
5. Confirm excluded data categories, especially messages, contacts, and private third-party material.
6. Confirm approval requirements for downloads and cross-domain navigation.
7. Confirm whether the private database relies on full-disk encryption or requires application-level encryption.
8. Confirm portfolio hosting target or retain local-only publication for the MVP.
9. Record accepted decisions in `docs/DECISIONS.md`.
10. Assign stable requirement and gate identifiers.

Deliverables:

- Accepted `IMPLEMENTATION_PLAN.md`.
- `docs/DECISIONS.md`.
- Initial policy configuration.

**Local gate L00:** All unresolved policy decisions are either accepted or explicitly marked deferred with a fail-closed default.

### WP01 — Repository And Reproducible Environment

**Dependencies:** WP00
**Goal:** Create a clean, reproducible source and test foundation.

Microsteps:

1. Initialize Git if approved.
2. Add `README.md`, `pyproject.toml`, `.gitignore`, and package skeleton.
3. Select and document the Python environment manager.
4. Attempt installation using the local Python version.
5. If compatibility fails, pin a supported interpreter and record the reason.
6. Lock all direct and transitive dependencies.
7. Install Playwright browser binaries in the project environment.
8. Add `socialoperator --version` and `socialoperator doctor` commands.
9. Add formatter, linter, type checker, and test configuration without unrelated tooling.
10. Add a source-manifest generator for non-Git evidence fallback.
11. Add CI or a local equivalent validation script.
12. Verify clean-environment installation and removal.

Deliverables:

- Reproducible dependency lock.
- CLI skeleton.
- Environment diagnostic report.
- Source manifest tool.

**Local gate L01:** A clean environment can install, run `doctor`, start the fixture server, and execute the empty test suite from documented commands.

### WP02 — Canonical Types, Configuration, And Policy Loading

**Dependencies:** WP01
**Goal:** Establish typed boundaries before subsystem implementation.

Microsteps:

1. Define typed IDs for sessions, pages, captures, observations, targets, actions, entities, claims, reviews, and publications.
2. Define coordinate-space types for desktop, window, viewport, screenshot, and device pixels.
3. Define enums for action risk, ownership, relevance, sensitivity, review status, and publication status.
4. Define immutable configuration models.
5. Define site-policy schema with domain, path, account identity, rate limit, and allowed action rules.
6. Define safe defaults for missing configuration.
7. Reject unknown high-risk configuration keys.
8. Add configuration precedence and provenance reporting.
9. Add policy validation with actionable errors.
10. Add unit tests for every enum transition and invalid configuration class.

Deliverables:

- Canonical typed models.
- Configuration loader.
- Policy schemas and tests.

**Local gate L02:** Every cross-subsystem identifier, coordinate, lifecycle state, and policy decision has one canonical typed representation.

### WP03 — SQLite Schema, Migrations, And Repositories

**Dependencies:** WP02
**Goal:** Implement durable, inspectable, migration-safe storage.

Microsteps:

1. Create migration runner and migration ledger.
2. Enable foreign keys and WAL mode on each connection.
3. Implement operational tables.
4. Implement knowledge tables.
5. Implement publication tables.
6. Implement FTS5 indexes and synchronization strategy.
7. Implement transaction boundaries for session, ingestion, review, and publication operations.
8. Add immutable capture enforcement.
9. Add claim-evidence approval constraints.
10. Add pinned or protected review/publication records that ordinary pruning cannot remove.
11. Add backup, restore, export, and deletion commands.
12. Add schema migration tests from every checked-in version.
13. Add integrity, foreign-key, and orphan checks.
14. Add fixture database generator.

Deliverables:

- Versioned schema.
- Repository layer.
- Database verification tool.
- Migration and integrity tests.

**Local gate L03:** Clean creation, migration, backup, restore, export, deletion, FTS search, integrity checks, and protected-record retention all pass.

### WP04 — Audit Events, Artifact Storage, And Session Recovery

**Dependencies:** WP02, WP03
**Goal:** Make every observation and action traceable and interruption-safe.

Microsteps:

1. Define structured audit event schema.
2. Implement append-only event writer.
3. Implement content-addressed artifact storage.
4. Hash screenshots and derived crops.
5. Link derived artifacts to parents.
6. Store bounded runtime status separately from immutable events.
7. Implement atomic session status updates.
8. Implement incident bundles containing relevant logs, state, and evidence hashes.
9. Implement startup stale-session detection.
10. Require restart into `PAUSED_RECOVERY`.
11. Prevent automatic replay of the last pointer action.
12. Add retention policies that cannot remove approved, rejected, superseded, revoked, or incident evidence without an explicit deletion workflow.

Deliverables:

- Event schema.
- Artifact store.
- Recovery manager.
- Incident package format.

**Local gate L04:** Forced termination at each operator state recovers to a correct paused state with no duplicate click and no missing committed evidence.

### WP05 — Dedicated Browser Session And Manual Login Handoff

**Dependencies:** WP01, WP02, WP04
**Goal:** Open an isolated headed browser while preserving user control of authentication.

Microsteps:

1. Create dedicated browser-profile directory with restrictive permissions.
2. Launch headed Chromium through Playwright.
3. Refuse to attach to the user's ordinary running profile.
4. Add profile lock and stale-lock detection.
5. Add `login-required`, `resume`, `pause`, and `stop` commands.
6. Detect password, OTP, passkey, and authentication-sensitive fields where browser evidence permits.
7. Disable screenshots, OCR, clipboard capture, and key observation during sensitive authentication.
8. Provide a manual privacy mode when automatic detection is uncertain.
9. Verify the user is on an approved origin before resuming automated observation.
10. Store session metadata without cookies or storage-state values.
11. Add tests proving browser-profile and authentication artifacts are ignored by Git.

Deliverables:

- Browser session manager.
- Login handoff UI/CLI.
- Authentication privacy tests.

**Local gate L05:** A fixture login flow proves manual entry, capture suppression, safe resume, profile persistence, and zero secret persistence.

### WP06 — Window Discovery, Screen Capture, And Coordinate Calibration

**Dependencies:** WP05
**Goal:** Establish deterministic mappings between page evidence and desktop coordinates.

Microsteps:

1. Discover the dedicated browser window by process and stable window identity.
2. Read window geometry and active-monitor geometry.
3. Capture the browser window without including unrelated desktop regions when possible.
4. Record desktop, window, viewport, screenshot, and device-pixel coordinate systems.
5. Calibrate browser chrome offsets.
6. Detect browser zoom and device pixel ratio.
7. Detect window movement, resize, monitor change, and scale change.
8. Invalidate calibration whenever geometry changes.
9. Add visual calibration fixture with known targets.
10. Add crop generation for pointer-local and target-local OCR.
11. Add redaction masks for SocialOperator windows and user-defined private regions.
12. Preserve original captures and derived-crop provenance.

Deliverables:

- Window locator.
- Screenshot adapter.
- Coordinate mapper.
- Calibration suite.

**Local gate L06:** Known fixture points transform correctly across all coordinate spaces, and stale calibration blocks actions.

### WP07 — DOM And Accessibility Observer

**Dependencies:** WP05, WP06
**Goal:** Produce structured page evidence for readable and interactive content.

Microsteps:

1. Capture URL, title, navigation timing, viewport, and scroll state.
2. Enumerate visible interactive elements.
3. Record role, accessible name, state, href, tag, and bounding box.
4. Record headings, landmark regions, labels, and relevant readable text.
5. Exclude hidden, disabled, zero-size, and off-viewport targets unless explicitly requested.
6. Handle same-origin frames.
7. Detect cross-origin frame boundaries and mark them as separate observation contexts.
8. Detect shadow DOM where Playwright exposes it.
9. Assign stable observation-local target IDs.
10. Hash normalized accessibility snapshots.
11. Add fixture pages covering links, buttons, dialogs, menus, tabs, forms, iframes, shadow roots, and dynamic changes.

Deliverables:

- Structured observer.
- Accessibility snapshot records.
- Interactive target inventory.

**Local gate L07:** The observer exactly identifies expected visible fixture targets and excludes prohibited hidden or disabled targets.

### WP08 — OCR Subsystem

**Dependencies:** WP04, WP06
**Goal:** Read visible text and return evidence-linked geometry and confidence.

Microsteps:

1. Define an OCR engine interface.
2. Implement Tesseract adapter with engine/version capture.
3. Normalize image color, scale, contrast, and orientation without replacing the source artifact.
4. Return text lines, words, confidence, and bounding boxes.
5. Implement full-viewport OCR.
6. Implement pointer-centered OCR with a configurable default crop.
7. Implement target-local OCR.
8. Treat empty OCR as a soft miss.
9. Treat engine failure as an observation failure, not permission to guess.
10. Redact operator windows and authentication-sensitive regions before OCR.
11. Create golden screenshot fixtures with exact expected text and geometry.
12. Benchmark cold and warm OCR latency.
13. Add optional PaddleOCR adapter behind the same interface only after Tesseract acceptance.

Deliverables:

- OCR interface and Tesseract implementation.
- Golden OCR corpus.
- OCR benchmark report.

**Local gate L08:** Golden accuracy, geometry, redaction, soft-miss, provenance, and latency thresholds pass on the target host.

### WP09 — Target Fusion And Ambiguity Resolution

**Dependencies:** WP07, WP08
**Goal:** Select targets using multiple evidence sources without blind OCR clicking.

Microsteps:

1. Define target evidence features.
2. Match OCR labels to accessibility names and DOM text.
3. Reconcile screenshot and DOM bounding boxes.
4. Score visibility, uniqueness, enabled state, and expected action compatibility.
5. Detect duplicate labels and overlapping targets.
6. Detect stale observations after page mutation.
7. Require a minimum evidence threshold.
8. Return a ranked explanation rather than only a coordinate.
9. Block when top candidates are too close or evidence conflicts.
10. Support deterministic site-policy overrides without bypassing verification.
11. Add adversarial fixtures with duplicate `Next`, hidden controls, deceptive overlays, moving buttons, and stale OCR.

Deliverables:

- Target fusion engine.
- Confidence and ambiguity report.
- Adversarial fixture suite.

**Local gate L09:** All deterministic target fixtures select the correct target or halt; no ambiguous fixture is clicked.

### WP10 — Native Mouse Executor And Emergency Controls

**Dependencies:** WP06, WP09
**Goal:** Move and click the visible desktop pointer safely.

Microsteps:

1. Define native mouse adapter interface.
2. Implement X11 pointer movement.
3. Implement configurable eased movement duration.
4. Implement hover without click.
5. Capture pointer position before and after movement.
6. Verify the pointer lies inside the current target polygon or bounding box.
7. Re-observe the target under the pointer before click.
8. Abort if the page, window, or target moves.
9. Implement single click and read-only scroll actions.
10. Add global pause and emergency-stop controls.
11. Add pointer-corner or dedicated-hotkey fail-safe.
12. Prevent clicks when the browser is not the expected foreground window.
13. Log the exact native action and post-action pointer state.
14. Run 100-trial deterministic acquisition tests.

Deliverables:

- Native mouse adapter.
- Emergency-stop controller.
- Pointer acquisition test report.

**Local gate L10:** Physical-pointer accuracy reaches the acceptance threshold with zero outside-target clicks and a functioning emergency stop.

### WP11 — Navigation State Machine And Postcondition Verification

**Dependencies:** WP05, WP07, WP09, WP10
**Goal:** Execute bounded read-only navigation with explicit expected outcomes.

Microsteps:

1. Define supported read-only actions.
2. Require an expected postcondition for each action.
3. Capture before-state evidence hash.
4. Execute pointer movement and hover verification.
5. Execute click or scroll.
6. Wait on bounded browser and visual conditions.
7. Capture after-state evidence.
8. Verify URL, title, DOM, accessibility, screenshot, or scroll changes.
9. Distinguish success, no-op, uncertain, possible-remote-success, and failure.
10. Retry only safe idempotent read-only actions.
11. Never retry possible remote-side-effect actions automatically.
12. Handle dialogs, popups, downloads, redirects, and new tabs through policy gates.
13. Add bounded pagination and infinite-scroll controls.
14. Add session budgets for pages, actions, time, and captured bytes.

Deliverables:

- Navigation state machine.
- Postcondition library.
- Failure classification and retry policy.

**Local gate L11:** End-to-end fixture navigation completes intended read-only tasks, halts correctly on uncertainty, and produces complete before/after evidence.

### WP12 — Scope, Ownership, Relevance, And Sensitivity Policy

**Dependencies:** WP02, WP03, WP07, WP08
**Goal:** Prevent broad or unjustified ingestion.

Microsteps:

1. Implement domain and path allowlists.
2. Implement source-account identity matching.
3. Define site-independent ownership evidence rules.
4. Define site-adapter ownership rules.
5. Separate `created_by_user`, `owned_by_user`, and `about_user` evidence.
6. Mark third-party comments, endorsements, reviews, and messages separately.
7. Implement sensitivity classification.
8. Quarantine uncertain ownership or relevance.
9. Require explicit reasons and evidence for each classification.
10. Allow advisory model proposals only after deterministic scope filtering.
11. Add fixtures for user work, profile mentions, shared organization assets, third-party comments, feeds, and unrelated recommendations.
12. Add a coverage matrix proving every observed content category has one policy outcome.

Deliverables:

- Scope engine.
- Ownership and sensitivity classifiers.
- Policy coverage matrix.

**Local gate L12:** Every classification fixture receives the expected single canonical outcome; uncertain cases quarantine and excluded cases are not retained as knowledge.

### WP13 — Extraction, Normalization, Entity Resolution, And Deduplication

**Dependencies:** WP03, WP08, WP12
**Goal:** Convert evidence into reviewable knowledge without losing provenance.

Microsteps:

1. Define canonical entity and claim forms.
2. Preserve raw observations unchanged.
3. Extract deterministic fields such as title, date, URL, author/account, and visible description.
4. Normalize whitespace, dates, and URLs with source preservation.
5. Generate entity-match candidates.
6. Preserve close competing entity matches instead of forcing a merge.
7. Generate claim candidates with evidence spans.
8. Add model-assisted summaries or tags only as proposals.
9. Deduplicate identical evidence by hash.
10. Link corroborating observations to existing claims.
11. Supersede changed claims rather than overwriting history.
12. Prevent self-generated operator text from entering the knowledge base.
13. Add regression fixtures for stale memory, duplicate pages, changed titles, contradictory dates, and partial OCR.

Deliverables:

- Extraction pipeline.
- Canonical entity/claim repositories.
- Deduplication and supersession logic.

**Local gate L13:** Every accepted claim has exact evidence; duplicates preserve provenance; contradictions remain visible; operator-generated text is excluded.

### WP14 — Review Queue And User Approval Interface

**Dependencies:** WP03, WP13
**Goal:** Make the user the authority over stored and published knowledge.

Microsteps:

1. Build local authenticated review UI.
2. Show source URL, capture time, screenshot crop, OCR/DOM text, and normalized proposal together.
3. Show ownership, relevance, sensitivity, and confidence explanations.
4. Support accept, reject, edit, redact, merge, split, supersede, and defer.
5. Require explicit publication fields separate from private knowledge approval.
6. Hash the exact reviewed proposal.
7. Bind review decisions to proposal hash and user identity.
8. Invalidate approval when publication-relevant content changes.
9. Preserve rejected and superseded decisions.
10. Add bulk operations only for records with identical policy and evidence class.
11. Add keyboard-accessible review workflows.
12. Add tests proving no API path can bypass approval invariants.

Deliverables:

- Review dashboard.
- Approval API.
- Review audit tests.

**Local gate L14:** Unapproved, changed-after-approval, rejected, uncertain, and private records cannot enter a publication version.

### WP15 — Public Snapshot Builder

**Dependencies:** WP03, WP14
**Goal:** Create a separate, minimal, reproducible public dataset.

Microsteps:

1. Define public schema independently of the private schema.
2. Select only approved and public records.
3. Copy only whitelisted fields.
4. Copy only approved public assets.
5. Remove private source crops, internal notes, confidence details, and account metadata unless explicitly approved.
6. Generate publication manifest with item and asset hashes.
7. Record source review decisions without exposing private evidence.
8. Run secret, PII, path, and schema scans.
9. Run public snapshot integrity checks.
10. Diff against the previous publication version.
11. Support rollback and revocation manifests.
12. Store immutable versioned snapshots.

Deliverables:

- Public snapshot schema.
- Snapshot builder.
- Publication manifest and verification tool.

**Local gate L15:** A seeded private database containing deliberate secrets and private rows produces a public snapshot with zero forbidden values and a complete reproducible manifest.

### WP16 — Dynamic Portfolio Website

**Dependencies:** WP15
**Goal:** Render the user's profile and portfolio exclusively from the public snapshot.

Microsteps:

1. Define portfolio information architecture.
2. Implement profile, projects, works, timeline, skills, and source-attribution views.
3. Query the public snapshot through a read-only connection.
4. Add stable slugs and canonical URLs.
5. Add responsive layout and accessible navigation.
6. Add metadata, structured data, and social preview support without inventing claims.
7. Display last-verified dates where appropriate.
8. Handle revoked and superseded items.
9. Add empty-state and incomplete-data presentation.
10. Add optional static export while retaining the dynamic application path.
11. Add snapshot compatibility version checks.
12. Add browser tests for all public routes.

Deliverables:

- Dynamic portfolio application.
- Templates and assets.
- Public route tests.

**Local gate L16:** The site renders every approved fixture item, renders no private fixture item, passes accessibility checks, and starts from a read-only public snapshot.

### WP17 — Site Adapter Framework And First Real Adapter

**Dependencies:** WP11, WP12, WP13
**Goal:** Add real-site support without placing site-specific assumptions in the core.

Microsteps:

1. Define site-adapter interface.
2. Define declarative adapter manifest.
3. Include allowed domains, paths, account identifiers, rate limits, expected content types, and ownership rules.
4. Support deterministic selector hints without treating selectors as permanent truth.
5. Add adapter versioning and fixture captures.
6. Require adapter-level tests for page types and failure modes.
7. Select one real site with the user.
8. Review that site's policies and permitted automation scope.
9. Capture user-approved account identifiers.
10. Run observe-only sessions before enabling pointer navigation.
11. Run supervised read-only navigation.
12. Extract a small bounded candidate set.
13. Require user review of every candidate.
14. Record site drift and disable the adapter when required invariants fail.

Deliverables:

- Adapter framework.
- First site adapter.
- Site-specific fixture and pilot report.

**Local gate L17:** The first adapter completes an approved bounded task with no off-scope navigation, unrelated ingestion, ambiguous click, or unreviewed publication.

### WP18 — Security, Privacy, Failure Injection, And Operational Hardening

**Dependencies:** WP04 through WP17
**Goal:** Prove the operator fails safely under realistic faults.

Microsteps:

1. Threat-model browser profile theft, screenshot leakage, database leakage, click confusion, prompt injection, malicious page text, and publication leakage.
2. Confirm file permissions for private runtime data.
3. Decide and implement database-at-rest protection.
4. Scan logs and reports for secrets and private data.
5. Treat webpage text as untrusted data, never instructions.
6. Reject page text attempting to alter operator policy or tool behavior.
7. Inject browser crashes, OCR failures, database locks, disk-full conditions, lost window focus, page movement, redirects, popup storms, and network timeouts.
8. Verify emergency stop under load.
9. Verify session budgets and circuit breakers.
10. Verify no action replay after recovery.
11. Verify deletion and revocation propagate to future public snapshots.
12. Verify private data remains absent from packaged releases.
13. Produce security and privacy review report.

Deliverables:

- Threat model.
- Failure-injection suite.
- Security/privacy report.
- Remediation log.

**Local gate L18:** All critical and high findings are resolved; medium findings are resolved or explicitly accepted by the user with mitigations and expiration conditions.

### WP19 — Full Validation, Pilot, Packaging, And Release Approval

**Dependencies:** WP00 through WP18
**Goal:** Establish release readiness from current source and current evidence.

Microsteps:

1. Check for leftover browser, fixture, OCR, and test processes.
2. Freeze the source state with Git hash or source manifest.
3. Recreate the environment from the lockfile.
4. Run formatting, lint, type, unit, integration, security, and end-to-end suites.
5. Run database migration and integrity suites.
6. Run golden OCR and pointer acquisition benchmarks.
7. Run authentication privacy tests.
8. Run public snapshot leakage tests.
9. Run dynamic portfolio route and accessibility tests.
10. Run one supervised real-site pilot from a clean runtime directory.
11. Review pilot actions and candidate knowledge with the user.
12. Build an evidence package indexed by requirement and gate.
13. Build distributable package and inspect its contents.
14. Verify rollback, revocation, export, and deletion procedures.
15. Document known limitations and deferred requirements.
16. Present exact release candidate hash and evidence summary.
17. Obtain explicit user approval of that exact release candidate.

Deliverables:

- Release candidate package.
- Full validation report.
- Requirement-to-evidence audit.
- Pilot report.
- Rollback and revocation proof.
- User release approval record.

**Local gate L19:** G0 through G10 pass against the exact release candidate, and no required evidence is historical, missing, stale, or generated from another source state.

## 18. Requirement-To-Work-Package Coverage

| Requirement group | Primary work packages |
|---|---|
| Dedicated browser and login | WP05, WP06 |
| DOM/accessibility observation | WP07 |
| OCR and redaction | WP06, WP08 |
| Target selection | WP09 |
| Physical mouse operation | WP10 |
| Safe navigation and verification | WP11 |
| Scope and ownership | WP12 |
| Knowledge extraction and provenance | WP03, WP04, WP13 |
| User review and approval | WP14 |
| Public snapshot isolation | WP15 |
| Dynamic portfolio | WP16 |
| Real-site support | WP17 |
| Security and recovery | WP04, WP18 |
| Release evidence | WP19 |

WP19 must expand this into a row-per-requirement matrix mapping every `FR-*` and `SP-*` requirement to implementation paths, tests, evidence files, current status, and unresolved gaps.

## 19. Test Strategy

### 19.1 Unit tests

- Coordinate transforms.
- Policy decisions.
- Ownership and sensitivity classification.
- Action-risk classification.
- State transitions.
- Hashing and canonical serialization.
- Schema repositories and constraints.
- OCR normalization.
- Target scoring and ambiguity.
- Publication field allowlists.

### 19.2 Integration tests

- Browser plus fixture site.
- Browser observation plus OCR.
- Target fusion plus native pointer.
- Action execution plus postcondition verification.
- Capture plus knowledge ingestion.
- Review plus publication snapshot.
- Snapshot plus portfolio rendering.

### 19.3 Golden fixtures

- Standard text page.
- High-DPI page.
- Zoomed page.
- Dark and light themes.
- Duplicate button labels.
- Canvas-rendered control.
- Modal overlay.
- Sticky header.
- Lazy-loaded content.
- Same-origin and cross-origin iframe.
- Shadow DOM.
- Moving target.
- Authentication form.
- Operator-window self-reading trap.
- Malicious webpage instructions.
- Third-party comments beside user-authored content.

### 19.4 Failure injection

- OCR timeout or malformed output.
- Browser process crash.
- Database locked.
- Disk full.
- Lost window focus.
- Window moved after calibration.
- Target moved during pointer travel.
- Redirect outside allowlist.
- Popup or new tab.
- Network timeout.
- Possible remote success with local verification failure.
- Runtime termination between click and verification.

### 19.5 Real-site validation

- Observe-only run first.
- User-present read-only navigation.
- Bounded number of pages and actions.
- No publication during the first pilot.
- Manual review of all captured records.
- Adapter disabled after material site drift until revalidated.

## 20. Security Model

### 20.1 Protected assets

- Browser profile and session cookies.
- Private SQLite database.
- Screenshots and OCR containing private information.
- User identity and account mapping.
- Review decisions and unpublished portfolio material.
- Public deployment credentials if introduced later.

### 20.2 Trust boundaries

- The user is the authentication and approval authority.
- The browser and webpages are untrusted input sources.
- OCR output is uncertain evidence.
- Model output is an untrusted proposal.
- The private database is trusted only after schema and integrity checks.
- The public snapshot is trusted only after deterministic publication validation.

### 20.3 Required controls

- Dedicated browser profile.
- Restrictive file permissions.
- Domain and path allowlists.
- Authentication privacy mode.
- Page-text prompt-injection rejection.
- Action risk enforcement.
- Emergency stop.
- Immutable evidence and audit events.
- Separate public snapshot.
- Secret and PII scans.
- Versioned publication and revocation.

## 21. Portfolio Publication Workflow

```text
Private observations
  -> normalized proposal
  -> ownership and sensitivity decision
  -> user review
  -> approved portfolio item
  -> public snapshot candidate
  -> deterministic privacy and integrity validation
  -> immutable publication version
  -> dynamic portfolio deployment
```

The workflow stops if any selected record lacks evidence, approval, a public sensitivity decision, valid asset rights metadata where applicable, or a clean publication validation report.

## 22. Operational Commands To Deliver

The exact CLI may evolve, but the initial command surface should cover:

```text
socialoperator doctor
socialoperator init
socialoperator browser start
socialoperator browser status
socialoperator login resume
socialoperator pause
socialoperator stop
socialoperator observe
socialoperator navigate --goal <bounded-goal>
socialoperator session report
socialoperator review serve
socialoperator kb verify
socialoperator kb backup
socialoperator kb export
socialoperator kb delete
socialoperator publish build
socialoperator publish verify
socialoperator portfolio serve
socialoperator evidence package
```

Commands that could expose private data must default to local-only output and must not print secrets or full private records to normal logs.

## 23. Risk Register

| Risk | Mitigation | Gate |
|---|---|---|
| OCR selects the wrong control | DOM/accessibility fusion, hover verification, ambiguity halt | G3, G4 |
| Window geometry changes | Calibration invalidation and action block | G3, G4 |
| Operator captures login secrets | Authentication privacy mode and secret regression tests | G2 |
| Site changes after adapter creation | Adapter drift detection and automatic disable | G8 |
| Feed ingestion exceeds user scope | Path allowlist, content taxonomy, bounded session budget | G5, G8 |
| Third-party data enters portfolio | Ownership and sensitivity gate plus user review | G5, G6, G7 |
| Private database is deployed | Physically separate public schema and leakage test | G7 |
| Operator reads its own output | Window redaction and self-content rejection | G3, G5 |
| Model output causes actions | Model remains advisory; deterministic action authority | G4, G9 |
| Crash repeats a click | Paused recovery and no automatic action replay | G9 |
| Historical reports certify changed source | Current source hash and regenerated evidence required | G10 |
| Existing browser session is disturbed | Dedicated profile and process identity checks | G2 |

## 24. Completion Definition

SocialOperator initial release is complete only when:

1. All applicable `FR-*` and `SP-*` requirements are implemented or explicitly deferred with user approval.
2. WP00 through WP19 local gates pass.
3. G0 through G10 pass.
4. The exact source state and dependency environment are recorded.
5. Full tests and current evidence are available.
6. Manual login privacy is proven.
7. Native mouse control is proven on the target X11 host.
8. One real-site adapter completes a bounded supervised pilot.
9. Every pilot-derived knowledge item has evidence and a user decision.
10. The private database remains local and protected.
11. The public snapshot leakage test reports zero forbidden data.
12. The dynamic portfolio renders only the approved public snapshot.
13. Recovery, rollback, revocation, export, and deletion are demonstrated.
14. Known limitations are documented.
15. The user approves the exact release candidate hash.

Focused tests, a successful demo, or a visually correct portfolio do not independently establish completion.

## 25. Recommended First Implementation Slice

The first executable slice should cover WP01 through a narrow portion of WP11:

1. Initialize the repository and reproducible Python environment.
2. Add the typed coordinate and action models.
3. Create the initial SQLite migration and audit event table.
4. Launch a dedicated headed browser profile.
5. Implement manual login pause/resume without capturing credentials.
6. Serve a deterministic local fixture page with one heading, one link, one button, and one modal.
7. Capture the browser window and calibrate coordinates.
8. Read the page through accessibility evidence and Tesseract OCR.
9. Fuse the evidence for one uniquely labeled button.
10. Move the visible X11 pointer to the button.
11. Verify hover alignment.
12. Click the button.
13. Verify that the modal opened.
14. Store before/after artifacts, OCR, target evidence, and action result in SQLite.
15. Generate a session report.

This slice must not access a real logged-in site or publish portfolio data. It establishes the minimum safe observe-plan-move-verify-record loop before broader extraction is attempted.

## 26. Immediate Approval Questions

Implementation should not begin beyond repository bootstrap until the user confirms:

1. X11-only support is acceptable for the first release.
2. Physical visible mouse movement is required for every click rather than only for acceptance testing.
3. The initial private-data exclusions, especially messages and third-party content.
4. Whether application-level database encryption is required.
5. The first real website to support after fixture validation.
6. Whether the first portfolio release is local-only or intended for public hosting.
