# SocialOperator Decisions

## 2026-08-31 — Initial implementation defaults

The instruction to implement `IMPLEMENTATION_PLAN.md` authorizes repository bootstrap and the synthetic fixture foundation. Unresolved real-data decisions retain fail-closed defaults.

| Decision | Initial value | Consequence |
|---|---|---|
| First desktop target | Linux/X11 | Other display servers remain deferred. |
| Mouse behavior | Visible native movement for every accepted click | Browser-local synthetic input is test-only. |
| Private messages and contacts | Excluded | They cannot enter the knowledge pipeline. |
| Real-site capture | Disabled by default | Only synthetic fixture data may be stored until explicitly enabled and bound to active exact-hash site-scope and at-rest readiness approvals. |
| Database encryption | Required before real private data unless full-disk protection is explicitly accepted and recorded | Foundation databases contain synthetic data only. |
| First real website | Deferred | WP17 cannot pass until the user selects and approves one. |
| Portfolio deployment | Local-only initially | Public hosting requires a later deployment decision. |
| External side effects | Blocked | Posting, messaging, uploads, reactions, purchases, edits, and deletion remain unavailable. |

These decisions may be superseded only by a dated decision that identifies affected requirements and gates.
