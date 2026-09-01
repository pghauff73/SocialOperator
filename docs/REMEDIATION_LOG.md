# Remediation Log

**Last updated:** 2026-08-31
**Scope:** current local implementation

## Addressed

| Area | Remediation | Evidence |
|---|---|---|
| Operator self-reading | Added X11 SocialOperator window discovery, browser-title exclusion, viewport clipping, and OCR screenshot redaction metadata. | `src/socialoperator/browser/window_masks.py`, `tests/test_x11_guard.py` |
| Browser-chrome authentication dialogs | Added sensitive X11 window detection for passkey, security-key, WebAuthn, CAPTCHA, and verification-code titles; discovery failure blocks capture. | `src/socialoperator/browser/window_masks.py`, `src/socialoperator/browser/session.py`, `tests/test_browser.py` |
| OCR quality evidence | Added deterministic golden-corpus term-recall and confidence reporting with CLI output. | `src/socialoperator/ocr/golden.py`, `tests/fixtures/ocr/golden.json`, `tests/test_ocr.py` |
| Incident evidence | Added a synthetic incident drill that records a failed action, preserves audit-chain evidence, emits private bundles, and verifies bundle checks. | `src/socialoperator/audit/incidents.py`, `tests/test_cli.py` |
| At-rest readiness | Added a protection report for private filesystem modes, SQLite codec detection, active full-disk acceptance records, revoke/status tooling, and fail-closed real-data readiness. | `src/socialoperator/security/at_rest.py`, `src/socialoperator/knowledge/database.py`, `tests/test_cli.py` |
| Real-site scope control | Added real-site policy loading, explicit-host validation, policy hashing, SQLite site-scope approvals, CLI scope reporting, and BrowserSession launch gating. | `src/socialoperator/config.py`, `src/socialoperator/knowledge/database.py`, `src/socialoperator/browser/session.py`, `tests/test_browser.py` |

## Open

| Area | Required decision or evidence |
|---|---|
| Real private data | User must approve the first real site, path scope, ownership scope, and at-rest protection approach. |
| At-rest decision | Enable application-level SQLite encryption or record explicit acceptance of an existing full-disk encryption boundary before real-site capture. |
| Production display privacy | Capture production regression evidence for operator-window masks and native authentication dialogs on the user's actual X11 window manager. |
| Real adapter | User must select the site; then build its adapter, drift fixtures, observe-only pilot report, and live read-only pilot evidence. |
| Release | Freeze an exact source state, regenerate evidence, rebuild packages, and obtain explicit user approval for the release candidate hash. |
