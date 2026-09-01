# SocialOperator

SocialOperator is a supervised local browser operator that will combine browser accessibility evidence, screenshot OCR, visible native mouse movement, provenance-aware SQLite storage, user review, and a sanitized public portfolio snapshot.

The implementation authority is [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md). The project is currently implementing the foundational work packages before enabling real-site browsing.

Current security posture and open release blockers are tracked in `docs/SECURITY_PRIVACY_REVIEW.md` and `docs/REMEDIATION_LOG.md`.

## Safety Baseline

- The user performs login, MFA, passkey, and CAPTCHA steps.
- Authentication-sensitive screens and passkey/security-key browser windows are outside capture and OCR scope.
- Real-site capture is disabled in the default configuration.
- Browser profiles, SQLite databases, screenshots, logs, and generated snapshots are ignored by Git.
- SocialOperator-owned X11 windows are masked from screenshot OCR input when redaction is enabled.
- Read-only actions are the default; external side effects remain blocked.
- The private knowledge database is never served by the public portfolio.

## Development Setup

```bash
uv sync --extra dev
uv run socialoperator doctor
uv run socialoperator init
uv run pytest
```

Install the Playwright-managed Chromium binary when browser work begins:

```bash
uv run playwright install chromium
```

## Current Commands

```text
socialoperator doctor
socialoperator init
socialoperator kb verify
socialoperator kb backup
socialoperator kb export
socialoperator kb restore
socialoperator kb delete
socialoperator kb prune --before <iso-datetime> --confirm PRUNE
socialoperator security at-rest-report
socialoperator security accept-full-disk --accepted-by <name> --summary <text> --confirm ACCEPT-FULL-DISK
socialoperator security at-rest-acceptance-status
socialoperator security revoke-at-rest-acceptance --acceptance-id <id>
socialoperator site policy-report --policy <path>
socialoperator site approve-scope --policy <path> --approver <name> --summary <text> --confirm APPROVE-SCOPE
socialoperator site scope-status
socialoperator site revoke-scope --approval-id <id>
socialoperator session report
socialoperator session incident --session-id <id> --summary <text> --output-dir <directory>
socialoperator session incident-drill --output-dir <directory>
socialoperator session pause --session-id <id> --reason <text>
socialoperator session resume --session-id <id> --reason <text>
socialoperator session stop --session-id <id> --reason <text>
socialoperator session control-status
socialoperator fixture serve
socialoperator ocr golden
socialoperator source-manifest
socialoperator release evidence
socialoperator release approve --candidate <path> --expected-sha256 <sha256> --approver <name> --confirm APPROVE-RELEASE
socialoperator review serve
socialoperator publish build
socialoperator publish verify
socialoperator publish rollback --version <number>
socialoperator portfolio serve
socialoperator portfolio export --output-dir <directory>
```

## Fixture Site

```bash
uv run socialoperator fixture serve --port 8765
```

Then open `http://127.0.0.1:8765` in a browser. The fixture is synthetic and exists to validate the observe-plan-move-verify-record loop before any real account is used.

## Review, Publication, And Portfolio

The review API requires a caller-supplied local token:

```bash
SOCIALOPERATOR_REVIEW_TOKEN='replace-with-a-local-secret' \
  uv run socialoperator review serve
```

After exact-hash approval, build and verify the physically separate public snapshot:

```bash
uv run socialoperator publish build
uv run socialoperator publish verify
uv run socialoperator portfolio serve
uv run socialoperator portfolio export --output-dir data/public/static
```

The public portfolio opens at `http://127.0.0.1:8001` by default. It reads `data/public/portfolio-public.sqlite` in SQLite read-only mode and cannot query the private knowledge database.
Static exports contain only the verified public snapshot fields and approved public assets.

## Private Operations

Retention pruning is explicit and confirmation-gated. Protected observations are retained:

```bash
uv run socialoperator kb prune --before 2026-09-01T00:00:00+00:00 --confirm PRUNE
```

Incident bundles are private JSON and Markdown summaries with hashed action and audit evidence:

```bash
uv run socialoperator session incident \
  --session-id <id> \
  --summary "reason for the incident package" \
  --output-dir reports/incidents/<id>
```

The synthetic incident drill verifies bundle file permissions, manifest hashes, audit evidence, and failed-action evidence:

```bash
uv run socialoperator session incident-drill --output-dir reports/incidents/drill
```

Running sessions poll a SQLite control queue before captures and actions:

```bash
uv run socialoperator session pause --session-id <id> --reason "user pause"
uv run socialoperator session resume --session-id <id> --reason "user resume"
uv run socialoperator session control-status --session-id <id>
```

At-rest reporting checks private file modes and confirms whether real-site data capture is still blocked:

```bash
uv run socialoperator security at-rest-report
uv run socialoperator security at-rest-acceptance-status
uv run socialoperator security accept-full-disk \
  --accepted-by <user-name> \
  --summary "accepted existing full-disk encryption boundary" \
  --confirm ACCEPT-FULL-DISK
```

Real-site policies are parsed, hashed, and blocked until explicitly approved in the private SQLite database:

```bash
uv run socialoperator site policy-report --policy config/sites/real_site.example.toml
uv run socialoperator site approve-scope \
  --policy config/sites/real_site.example.toml \
  --approver <user-name> \
  --summary "approved paths and ownership scope" \
  --confirm APPROVE-SCOPE
```

Release evidence hashes the regenerated source, session, at-rest, OCR, action, pointer, incident, and package reports. Approval is intentionally separate and requires the exact candidate file SHA-256:

```bash
uv run socialoperator release evidence --output reports/release-candidate.json
sha256sum reports/release-candidate.json
uv run socialoperator release approve \
  --candidate reports/release-candidate.json \
  --expected-sha256 <sha256-from-above> \
  --approver <user-name> \
  --output reports/release-approval.json \
  --confirm APPROVE-RELEASE
```
