# SocialOperator Implementation Status

**Status date:** 2026-08-31
**Plan authority:** `IMPLEMENTATION_PLAN.md`
**Source state:** Active uncommitted implementation on branch `main`

This report records current evidence. It does not replace the completion definition in the implementation plan and does not claim that the full objective is complete.

## Current Work-Package Status

| Work package | Status | Current evidence | Remaining gap |
|---|---|---|---|
| WP00 | Implemented with deferred decisions | `docs/DECISIONS.md` records X11, visible mouse, excluded messages, disabled real-site capture, local-only publication, fail-closed encryption defaults, auditable at-rest reporting, and explicit full-disk acceptance tooling. | User must select the first real site and either enable application-level encryption or explicitly accept the full-disk boundary before real data. |
| WP01 | Implemented | Git repository, `pyproject.toml`, `uv.lock`, Python 3.13 environment, CLI, doctor, fixture server, source manifest, Ruff, mypy, pytest, Playwright Chromium. | CI service is not configured; local validation is authoritative. |
| WP02 | Implemented initial scope | Canonical IDs, coordinate types, lifecycle enums, action/ownership/sensitivity enums, strict TOML configuration, site policy validation. | Cross-platform configuration is deferred. |
| WP03 | Implemented initial scope | Seven SQLite migrations, all planned table families, revision and lineage history, control-request queue, site-scope approval records, full-disk acceptance records, FTS5, WAL, foreign keys, integrity checks, backup, restore, deletion, guarded pruning, and pruning protection. | Later migrations may extend real-site adapter evidence. |
| WP04 | Implemented initial scope | Hash-chained audit events, content-addressed artifact store, session recovery to `PAUSED_RECOVERY`, no automatic action replay, private JSON/Markdown incident bundles with hashed evidence manifests, and a repeatable synthetic incident-drill command. | Production incident drill and optional time-based retention automation remain. |
| WP05 | Implemented fixture scope | Dedicated persistent Playwright profile, profile lock, manual privacy mode, password/OTP/passkey/CAPTCHA page detection, browser-chrome sensitive X11 window detection, capture suppression, approved-origin resume, and fail-closed X11 discovery handling. | Real-login pilot and production native-dialog evidence remain. |
| WP06 | Implemented X11 fixture scope | Window metrics, exact visual screenshot-to-desktop calibration, stale privacy block, content-addressed screenshot support, and action-time movement/resize/DPR invalidation. | Multi-monitor production evidence remains. |
| WP07 | Implemented fixture scope | URL/title/viewport/scroll, headings, readable text, ARIA snapshot, visible target inventory, target geometry, same-origin frame contexts, shadow-root targets, and cross-origin frame boundaries. | Broader site-specific frame coverage remains for real adapters. |
| WP08 | Implemented Tesseract scope | Tesseract engine/version, token confidence and geometry, exact 400x400 crop, screenshot redaction, fixture screenshot OCR, deterministic OCR golden-corpus metrics, and operator-window mask clipping before OCR input. | Broader real-screenshot corpus and optional PaddleOCR adapter remain. |
| WP09 | Implemented fixture scope | DOM/accessibility/OCR target ranking, exact-name support, ambiguity halt, duplicate-target fixture, moving-target rejection, and target re-observation after pointer travel. | Broader adversarial overlay corpus remains. |
| WP10 | Implemented X11 fixture scope | PyAutoGUI native adapter, X11 active-window title/class guard, emergency fail-safe, inside-target verification, and 100/100 isolated native acquisition report. | Multi-monitor and live-user-desktop evidence remains. |
| WP11 | Implemented fixture scope | State transitions, visual calibration, native movement, post-move geometry revalidation, hover verification, physical click, native wheel scroll, selector/URL/title/text/selector-text/popup/download/scroll postconditions, pagination fixture verification, before/after hashes, SQLite action record, and page/action/time/capture-byte session budgets. | Broader real-site pagination corpus remains. |
| WP12 | Implemented initial scope | Domain/action policy, explicit-host validation, exact real-site policy hashes, site-scope approval records, ownership taxonomy, exclusion and third-party detection, fail-closed uncertainty. | Real-site ownership manifests and exhaustive content coverage matrix remain. |
| WP13 | Implemented initial scope | Source account/page, immutable DOM/OCR observations, entity, claim, evidence link, ownership assertion, sensitivity decision, FTS, portfolio proposal, contradiction detection, and exact-hash claim supersession. | General entity matching and real-data contradiction corpus remain. |
| WP14 | Implemented fixture scope | Exact proposal hash, approval conflict detection, protected decisions, rejection, exact-hash edit/redaction, append-only revisions, merge/split supersession lineage, claim contradiction UI/API, token-protected API, HTTP Basic review UI, CSRF protection, and evidence displayed beside proposals. | Keyboard audit of merge/split and contradiction bulk workflows remains. |
| WP15 | Implemented fixture scope | Physically separate public schema, field and asset allowlists, exact-hash review enforcement, approved public asset copy, versioned manifest, integrity/table/count/hash checks, content leakage scanner, active snapshot, retained published items, rollback, and revocation propagation. | Deployment-specific inspection remains. |
| WP16 | Implemented fixture scope | Read-only SQLite portfolio repository, `/health`, profile/projects/works/timeline/skills sections, index, item and asset routes, metadata and structured data, server-rendered templates, empty state, static export, and HTML accessibility probes. | Deployment-specific inspection remains. |
| WP17 | Partial | Versioned declarative adapter interface, registry, required heading/target invariants, drift error, automatic disable state, real-site policy loading, policy SHA-256 reporting, and exact-hash site-scope approval gating are implemented for local/example policies. | User-approved real site, observe-only pilot, real adapter fixtures, and live drift evidence. |
| WP18 | Partial | Fail-closed config, privacy boundary, prompt/data separation, ambiguity halt, all-state kill-point recovery matrix, profile-lock tests, tamper detection, leakage trap, at-rest protection report with SQLite codec detection, active full-disk acceptance gate, budget circuit breakers, SQLite pause/resume control queue, X11 operator-window mask discovery, browser-chrome sensitive window halt, synthetic incident drill, moving-target/timeout/outside-policy/resize/foreground-loss injections, `docs/THREAT_MODEL.md`, `docs/SECURITY_PRIVACY_REVIEW.md`, and `docs/REMEDIATION_LOG.md`. | User at-rest decision, production privacy/window-mask regression capture, and final release security review. |
| WP19 | Partial | The row-per-requirement matrix covers all 39 `FR-*` and `SP-*` identifiers, current source evidence is regenerated, wheel and source distributions build, packaged templates are verified, leakage scans reject private runtime files, key material, databases, and absolute user-home paths, release evidence indexes source/session/at-rest/OCR/action/pointer/incident/package reports, exact-hash approval tooling exists, and the 100-trial pointer report passes. | Real-site pilot, release-candidate freeze, and exact-hash user approval. |

## Current Verified Commands

```bash
uv sync --extra dev
uv run socialoperator doctor
uv run socialoperator security at-rest-report
uv run socialoperator security at-rest-acceptance-status
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run python tools/check_requirement_matrix.py
uv run socialoperator ocr golden --output reports/ocr-golden.json
uv run socialoperator source-manifest --output reports/current-source-manifest.json
uv run socialoperator session report --output reports/current-session-report.json
uv run socialoperator release evidence --output reports/release-candidate.json
uv build
xvfb-run -a -s '-screen 0 1600x1200x24' \
  uv run python tools/action_postcondition_fixture_test.py
xvfb-run -a -s '-screen 0 1600x1200x24' \
  uv run python tools/native_pointer_fixture_test.py --trials 100 --report reports/native-pointer-100-trial.json
```

## Current Deterministic Evidence

- Managed Chromium installed through Playwright.
- Doctor reports Python, SQLite JSON/FTS5, X11, Chrome, Tesseract, and required modules ready.
- SQLite schema version 7 passes `integrity_check` and `foreign_key_check`.
- Real-site policies can be parsed and hashed, but a headed session is blocked unless configuration, at-rest protection, and active exact-hash site-scope approval all pass.
- The at-rest report verifies configured private file/directory modes and reports that real-site data remains blocked unless application-level SQLite encryption is available or an active full-disk acceptance record exists.
- Browser authentication, page-visible passkey, browser-chrome passkey/security-key window titles, and CAPTCHA fixtures block screenshots and OCR.
- X11 operator-window mask discovery excludes browser content windows and clips owned-window rectangles into screenshot coordinates before OCR input.
- Tesseract reads the synthetic fixture screenshot.
- Native pointer acquisition passed 100/100 isolated X11 trials with median latency 1.217 seconds.
- Popup, download, pagination selector-text, native wheel scroll, URL navigation, moving-target, timeout, outside-policy, resize, and foreground-loss cases pass the real-pointer fixture.
- The synthetic incident drill records a failed action, preserves audit-chain evidence, emits private `0600` JSON/Markdown incident bundles, and verifies bundle checks.
- Exact visual calibration located the viewport at zero sampled pixel error in the isolated native-pointer run.
- A deliberate private secret inserted into the private database is absent from the public snapshot.
- The dynamic and static portfolios render approved synthetic items and approved public assets from the public read-only database.
- Ruff, mypy, and all 80 pytest cases pass; the only warning is an upstream Starlette `TestClient` deprecation notice.
- The requirement matrix covers all 39 plan requirement identifiers with no missing or extra IDs.
- The wheel contains the review and portfolio templates; both distributions contain no private runtime files, SQLite databases, private keys, or absolute user-home paths.
- Release evidence tooling hashes current source, session, at-rest, OCR, action, pointer, incident, and package reports into a candidate evidence file; approval tooling requires the candidate file SHA-256 plus `APPROVE-RELEASE`.
- Distribution hashes are checked after each release-candidate build.
- Generated source, session, at-rest, OCR, incident, pointer, package, and release-candidate reports are the hash authority for the current tree.
- The release-candidate evidence correctly reports `release_ready=false` while real-site capture is blocked by disabled real-site capture configuration and unresolved at-rest readiness.
- The current source manifest is regenerated from the active tree and stores only the logical root `.`.

## Next Critical Path

1. Obtain the user's at-rest decision before any real-site capture: application-level encryption or explicit full-disk acceptance.
2. Obtain the user-selected first real site and approved ownership/path scope.
3. Complete production privacy/window-mask regression capture, production incident drill evidence, and deployment-specific inspection.
4. Run the observe-only and live read-only real-site pilot.
5. Freeze an exact release candidate for user approval after pilot review.
