# Security And Privacy Review

**Review date:** 2026-08-31
**Scope:** local synthetic-fixture implementation
**Real-site status:** disabled

## Current Decision

SocialOperator remains safe only for synthetic/local fixture data. Real-site capture is blocked until the user approves the first site scope and resolves at-rest protection by either enabling application-level database encryption or recording an explicit full-disk encryption boundary acceptance.

## Verified Controls

- Authentication capture is blocked by manual privacy mode and page-visible password, OTP, passkey, security-key, and CAPTCHA detectors.
- Browser-chrome passkey and security-key dialogs are treated as sensitive X11 windows and block capture in the headed Linux release.
- SocialOperator-owned X11 windows are discovered, clipped into viewport screenshot coordinates, and redacted before OCR input.
- Page text, OCR text, links, redirects, popups, and downloads remain untrusted data and cannot change deterministic action or publication policy.
- Actions are limited to A0/A1 in the initial release; A3/A4 destructive and external side-effect actions are blocked.
- Native mouse actions require policy authorization, calibrated coordinates, foreground checks, post-move geometry validation, target re-observation, and postcondition verification.
- Session page, action, time, and capture-byte budgets pause the operator before continued capture or action.
- Running sessions poll SQLite pause, resume, and stop requests before captures and actions.
- Real-site sessions require enabled real-site capture configuration, at-rest readiness, and active SQLite approvals for both the exact site-policy hash and the accepted full-disk boundary when application-level encryption is disabled.
- Private artifacts, incident bundles, and runtime directories use configured private filesystem modes.
- Public portfolio generation reads a separate sanitized SQLite snapshot, never the private knowledge database.

## Residual Release Blockers

- Application-level SQLite encryption is unavailable in the current Python SQLite build; real data remains blocked until the user records full-disk acceptance or supplies application-level encryption.
- Production privacy/window-mask regression captures have not been produced on the user's actual window manager and display layout.
- No user-selected real site, path allowlist, ownership scope, or real adapter fixture has been approved.
- No observe-only or live read-only real-site pilot evidence exists.
- No exact-hash release candidate has been approved by the user.

## Required Evidence Before Real Data

```bash
uv run socialoperator security at-rest-report
uv run socialoperator security at-rest-acceptance-status
uv run socialoperator ocr golden --output reports/ocr-golden.json
uv run socialoperator session incident-drill --output-dir reports/incidents/drill
uv run pytest -q
uv run python tools/check_requirement_matrix.py
```

The commands above are necessary but not sufficient for release. Real-site G8, G9, and G10 gates still require the user-approved site scope, production pilot, and exact release approval.
