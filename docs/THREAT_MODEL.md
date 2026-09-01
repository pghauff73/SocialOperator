# SocialOperator Threat Model

**Assessment date:** 2026-08-31
**Scope:** Current local synthetic-fixture implementation
**Real-site status:** Disabled

## Protected Assets

- Dedicated browser profile, cookies, local storage, and authenticated sessions.
- Private SQLite knowledge database.
- Screenshots, OCR, source text, and downloaded artifacts.
- Source-account identity mappings.
- Review tokens, reviewer decisions, and unpublished portfolio proposals.
- Public snapshot and publication manifests.
- Future deployment credentials.

## Trust Boundaries

1. The user is the authority for authentication, approval, release, revocation, and deletion.
2. Browser pages, DOM text, OCR text, links, files, redirects, and dialogs are untrusted data.
3. OCR is uncertain evidence and cannot independently authorize an action or claim.
4. A model, when added, will be an untrusted proposal generator.
5. Native mouse input is authorized only by deterministic policy, target evidence, foreground identity, geometry, and postcondition verification.
6. The private database is authoritative only after migration, integrity, foreign-key, and provenance checks.
7. The public snapshot is authoritative only after exact-hash review, allowlisted field selection, integrity checks, and manifest verification.

## Primary Threats And Controls

| Threat | Current controls | Remaining work |
|---|---|---|
| Credential capture | Manual privacy mode, password/OTP/passkey/CAPTCHA page detection, browser-chrome sensitive X11 window detection, screenshot/OCR refusal, fail-closed X11 discovery handling, and ignored profile/storage files | Real-login pilot and production native-dialog evidence |
| Existing browser takeover | Dedicated profile path, exclusive profile lock, no attachment to ordinary profile | Production process/window identity report |
| Click confusion | DOM/ARIA/OCR fusion, unique target threshold, visual viewport calibration, foreground guard, post-move calibration, target re-observation, element-under-pointer check, and 100-trial acquisition evidence | Broader moving-overlay corpus |
| Prompt injection in page text | Page text is stored as data; action and scope authority remain deterministic; A3/A4 actions are blocked | Formal malicious-page fixture corpus and future model-output quarantine |
| Third-party private-data ingestion | Exclusion phrases, ownership taxonomy, uncertainty quarantine, real-site capture disabled | Site-specific exhaustive coverage matrices |
| Runaway read session | Page, action, time, and capture-byte budgets pause the operator before further observation or action | Real-site budget tuning |
| Self-reading contamination | Operator UI is a separate origin/process; X11 operator-window discovery excludes browser content windows, clips overlapping owned windows into screenshot coordinates, and redacts them before OCR input | Production multi-window regression captures |
| Private database publication | Separate public schema and files, field and asset allowlists, exact-hash approval, deliberate secret leakage test, path scan, and forbidden-content scanner | Deployment-specific inspection |
| Stale approval | Proposal hash excludes workflow state but includes all public content; edit, redaction, merge, and split invalidate or supersede approval | Real-data review evidence |
| Crash repeats click | Recovery enters `PAUSED_RECOVERY`; all operator states have a no-replay kill-point recovery test | Production interruption evidence |
| User cannot halt running operator | Emergency mouse fail-safe, stop(), SQLite pause/resume/stop request queue, and pre-capture/pre-action polling | Production operator-loop drill |
| Site drift | Versioned adapter invariants, drift errors, registry disable state | First real adapter and live drift evidence |
| Browser or window movement | Screenshot-to-desktop calibration, post-move recalibration, resize/DPR invalidation, and foreground-loss injection tests | Multi-monitor event invalidation |
| Malicious public snapshot | Read-only connection, allowed-table check, integrity and item-count check, version manifest | Signed releases if remote deployment is enabled |
| Local data theft | `0700` private directories, `0600` private files, at-rest protection report, SQLite codec detection, active full-disk acceptance records, and real-data fail-closed readiness check | Application-level encryption or explicit recorded acceptance of full-disk encryption |
| CSRF or unauthorized review | HTTP Basic, separate API token, CSRF token, exact proposal hash | Session expiry and operator-facing token rotation command |

## Fail-Closed Rules

- Real-site capture remains disabled while application-level encryption is required but absent, or while full-disk acceptance is required but not recorded.
- Authentication-sensitive fields disable capture and OCR.
- Unknown origins, paths, adapters, actions, ownership, and sensitivity states are rejected or quarantined.
- Ambiguous or stale targets are not clicked.
- A possible external side effect is never automatically retried.
- An approved item whose public content changes cannot be published under the old decision.
- A public snapshot with unknown tables, integrity failure, count mismatch, or manifest mismatch is rejected.

## Residual Risks

- Browser chrome and native passkey dialogs are detected only through X11 metadata in the current Linux release.
- Operator-window discovery depends on X11 client metadata; production regression captures must prove local window-manager behavior.
- X11 permits broad input and screenshot access to processes in the same session.
- OCR can misread stylized, low-contrast, or non-English text.
- Site policies and terms may restrict automation even when the user owns the account.
- A public portfolio may expose information the user later decides to withdraw; revocation requires rebuilding or rolling back the active snapshot.
- The local review token currently depends on caller-managed secrecy and rotation.

Real-site pilot work must not begin until the at-rest decision, first site, permitted scope, and adapter evidence are explicitly approved.
