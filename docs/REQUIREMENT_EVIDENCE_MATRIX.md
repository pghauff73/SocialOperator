# Requirement-To-Evidence Matrix

**Audit date:** 2026-08-31
**Source:** `IMPLEMENTATION_PLAN.md`
**Status meanings:** Implemented, Partial, Deferred, or Blocked

| Requirement | Status | Current evidence | Remaining proof |
|---|---|---|---|
| FR-01 | Implemented | `BrowserSession`, dedicated profile and lock tests | Real-login pilot |
| FR-02 | Implemented fixture scope | `LOGIN_REQUIRED`, privacy mode, explicit `resume_after_login` | User-facing live handoff |
| FR-03 | Implemented fixture scope | Password/OTP/passkey/CAPTCHA page detection, browser-chrome sensitive X11 window detection, capture refusal tests, and fail-closed X11 discovery handling | Real-login secret scan |
| FR-04 | Implemented fixture scope | `PageObserver`, context-attributed frame and shadow-root fixture tests | Real-adapter frame coverage |
| FR-05 | Implemented fixture scope | Tesseract token geometry, confidence, version, artifact provenance, and deterministic OCR golden-corpus term-recall report | Broader real-screenshot accuracy corpus |
| FR-06 | Implemented initial | Target fusion and ambiguity tests | Larger adversarial corpus |
| FR-07 | Implemented X11 fixture | PyAutoGUI isolated native-pointer 100-trial report | Live user-desktop evidence |
| FR-08 | Implemented fixture scope | Pointer arrival, re-observation, element-under-pointer, and moving-target rejection | Broader overlay corpus |
| FR-09 | Implemented fixture scope | Selector/URL/title/text/selector-text/popup/download/scroll postconditions and action fixture with pagination text verification | Broader real-site postcondition corpus |
| FR-10 | Implemented fixture scope | Native wheel scroll executor records before/after viewport scroll provenance and passes action fixture pagination and scroll cases | Broader real-site pagination corpus |
| FR-11 | Implemented initial | Domain/path policies, origin resume block, exact policy hash, real-site policy report, and SQLite site-scope approval gate | Real adapter path matrix |
| FR-12 | Implemented initial | Ownership, exclusion, sensitivity, uncertainty policy tests | Real-site exhaustive taxonomy |
| FR-13 | Implemented | Immutable captures, protected observations, hash-chained audit events, guarded prune CLI | Optional time-based pruning scheduler |
| FR-14 | Implemented initial | Entity, claim, relationship-ready schema, portfolio proposal | General entity resolution |
| FR-15 | Implemented | `claim_evidence` constraint and review evidence display | Multi-source corroboration tests |
| FR-16 | Implemented fixture scope | Duplicate hash checks, claim contradiction listing, exact-hash claim supersession, and affected item unpublication | Real-data contradiction corpus |
| FR-17 | Implemented fixture scope | Authenticated evidence-rich review UI/API, CSRF, exact-hash redaction, merge/split API, contradiction UI/API | Keyboard audit of merge/split and contradiction workflows |
| FR-18 | Implemented fixture scope | Approval, rejection, redaction, append-only revisions, merge/split supersession, claim supersession, revocation | Real-data review evidence |
| FR-19 | Implemented fixture scope | Separate versioned public SQLite snapshot, approved asset copy, public scanner | Deployment inspection |
| FR-20 | Implemented fixture scope | Read-only dynamic FastAPI/Jinja portfolio, profile/project/work/timeline/skills sections, asset routes, metadata, structured data, static export, accessibility probes | Deployment inspection |
| FR-21 | Implemented initial | Backup, export, restore, database deletion | Evidence-manifest deletion report |
| FR-22 | Implemented fixture scope | Recovery to `PAUSED_RECOVERY`, no replay test, all-state kill-point matrix | Production kill evidence |
| FR-23 | Implemented fixture scope | In-process privacy, state transition, stop, emergency mouse fail-safe, SQLite control queue, CLI pause/resume/stop requests, and running-session polling | Production operator-loop drill |
| FR-24 | Implemented fixture scope | `session report` output, private JSON/Markdown incident bundles with hashed evidence manifests, and repeatable synthetic incident-drill command | Production incident drill |
| SP-01 | Implemented fixture scope | No credential schema, password/OTP/passkey/CAPTCHA capture suppression, browser-chrome sensitive X11 window detection, and fail-closed X11 discovery handling | Real-login secret scan |
| SP-02 | Implemented | `.gitignore`, package inspection gate, source/report path sanitization | Release secret scan evidence |
| SP-03 | Implemented | A0/A1 policy only, explicit-host validation, and real-site scope approval gate | Real-site action inventory |
| SP-04 | Implemented by block | A2 requires approval; A3/A4 blocked | Later approved side-effect workflow |
| SP-05 | Implemented | A3/A4 authorization rejection tests | None for initial release |
| SP-06 | Implemented fixture scope | Ambiguity, origin, drift, foreground, geometry, resize, timeout, and moving-target halts | Dialog/CAPTCHA corpus |
| SP-07 | Implemented fixture scope | Redaction functions, public content scanner, configuration, X11 operator-window discovery, browser-title exclusion, viewport clipping, and screenshot redaction tests | Production multi-window regression capture |
| SP-08 | Implemented initial | Third-party and private-message exclusions | Real-site data-category audit |
| SP-09 | Implemented | Public snapshot has a distinct schema and path | Deployment inspection |
| SP-10 | Implemented | Exact-hash review required for publication | User real-data approval evidence |
| SP-11 | Partial | `0700` directories, `0600` private files, at-rest protection report, SQLite codec detection, active full-disk acceptance records, CLI revoke/status tooling, and fail-closed real-data readiness check | User at-rest decision and application-level encryption or explicit full-disk acceptance evidence |
| SP-12 | Implemented | Reviewer identity, timestamp, exact hash, protected decision | Identity integration if multi-user |
| SP-13 | Implemented | Uncertain ownership raises policy error | Real adapter coverage matrix |
| SP-14 | Implemented by design | No side-effect action executor or retry exists | Later remote-effect failure tests |
| SP-15 | Implemented | No model is present; deterministic authorities only | Model quarantine tests when added |

The project cannot pass G8, G9, or G10 while real-site selection, the at-rest decision, pilot evidence, production privacy/window-mask regression capture, and exact release approval remain absent.
