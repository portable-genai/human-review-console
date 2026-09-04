# COMPLIANCE - `human-review-console` Case, Workflow & Human-Review Platform

How this repo realizes each General Principle (P-01..P-13) and dependency rule (R1..R7). `human-review-console` is
the system enforcer for **P-06**: it is the destination the whole catalog's `requires_human_review`
escalations route to. It also hosts the case, clock & workflow engine (`domain/cases/`). Both
halves run in one service under one control posture: one runtime SA, one CMEK key set, one
residency pin, one WORM audit trail. Each control names the code or infra that implements it,
and where the case engine adds surface, the same control covers it.

## General Principles

| # | Principle | Control in this repo |
|---|---|---|
| P-01 | Hybrid on-prem + GCP | The `onprem` profile is a first-class target: every port has a fail-fast on-prem placeholder the client rebinds to their own store / sink / IdP. `infra/terraform` keeps ingress internal-only (`INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER`), no public egress. |
| P-02 | No vendor lock-in (ports & adapters) | Pure-stdlib domain core; every edge is a `typing.Protocol` with swappable adapters selected by `REVIEW_PROFILE`. The SDK-free gate is the portability proof. Open standards: identity via the shared kit, WORM via the shared kit. |
| P-03 | Single region by default | Region pinned to `asia-southeast1` in `config.py` (`REGION`) and `infra/terraform/locals.tf`; `variables.tf` validates the residency allowlist at plan; `org_policy.tf` enforces `gcp.resourceLocations`. |
| P-04 | Minimise data to the model | No model. Neither half sends anything to an LLM. Reasons and summaries (review) and case summaries and attributes (case) are still redacted via `pii-kit` before the audit write, so no raw identifier is retained. |
| P-05 | Grounding over fine-tuning | N/A: no model, no training. Decisions are deterministic code (maker-checker, state machine, clocks), not a learned function. |
| **P-06** | **Human-in-the-loop / maker-checker** | **The whole system.** `maker_checker_service.check_eligibility` enforces four-eyes (`SELF_APPROVAL`), SoD, least privilege and N-eyes distinctness as pure fail-closed code; `console_service` records a WORM sign-off and never auto-executes. The case engine reinforces it: a breach or stall sets `requires_human_review` and routes the case into this same console (in-process, via `ReviewRouterPort`), never advancing a case itself. This repo IS P-06's system enforcer. |
| P-07 | Auditable & explainable by design | One shared WORM sink for both halves. Every disposition attempt (allowed or denied) writes an immutable, hash-chained, already-redacted `SignOffEvent`; every case action (open, transition, evaluate, refused transition) writes a `CaseAuditEvent`, and the full transition history is kept on the case. `HashChainedAuditLog.verify_chain()` proves tamper-evidence; `logging_worm.tf` is the immutable cloud sink. |
| P-08 | Eval-gated promotion | `eval/run_eval.py` runs `--mode smoke` (offline) and `--mode gate` (the `model-quality-gate` promotion authority). Review metrics (`four_eyes_integrity`, `pii_safety`) and case metrics (`clock_accuracy`, `escalation_accuracy`, `case_pii_safety`) score together; the safety metrics each have a not-falsely-green test. |
| P-09 | Defense in depth / zero trust | Server-verified `Principal` only (client actor discarded); fail-closed S2S caller auth; tenant partition enforced in BOTH the domain and the store, for reviews and cases alike; CMEK (one key set), least-privilege runtime SA (one SA) and no SA-keys in `infra/terraform`. |
| P-10 | Resilience & graceful degradation | Fail-closed by construction: an ineligible or cross-tenant disposition denies rather than proceeding; a terminal item rejects re-disposition (409); an illegal case transition is refused (409); a cross-tenant case read is a 404. Case deadline timers (Cloud Tasks) fire even if no one polls, so a breach is not missed. The gcp adapters degrade to the on-prem placeholder contract when unbound. |
| P-11 | Cost & latency control | No model calls, so no token cost; every decision is pure O(1) / O(history) code. Cloud Run scales with request concurrency capped. |
| P-12 | Reversibility / documented exit | `docs/onprem-migration.md` is the exit guide; the `onprem` profile proves the domain runs with the client's own adapters and no GCP. |
| P-13 | Fair, consented marketing | N/A: `human-review-console` is a horizontal control plane, not a marketing surface. |

## Dependency rules

| # | Rule | Status for `human-review-console` |
|---|---|---|
| R1 | Customer/PII data -> depend on `agent-guardrail-gateway` | `human-review-console` holds no customer PII by design, but redacts review summaries / reasons and case summaries / attributes via the shared `pii-kit` before audit (defense in depth). A deployment fronting `human-review-console` with `agent-guardrail-gateway` loses nothing. |
| R2 | Production system -> depend on `agent-observability` | The shared `AuditSinkPort` is the seam for both halves: `local` is the hash-chained WORM log; `gcp` writes to the Cloud Logging WORM sink that `agent-observability` owns. |
| R3 | RAG / grounded -> depend on `enterprise-knowledge-base` | N/A: no retrieval, no grounding. |
| R4 | Deployed agent / exposed tool -> register in `agent-registry` | `human-review-console`'s identity / entitlement resolution is the `agent-registry` seam (`IdentityPort`); the approver entitlement (`group:approver`) is an `agent-registry`-scoped group in production. |
| R5 | Promoted to production -> pass `model-quality-gate` | `eval/run_eval.py --mode gate` calls the `model-quality-gate` promotion authority via `agent-eval-kit`. |
| R6 | New project -> pass `architecture-validator` at intake | This repo was scaffolded to the catalog build standard (ports-and-adapters, three profiles, the hard gate). |
| R7 | Marketing output -> pass `marketing-compliance-gate` | N/A. |

## The proposed new rule `human-review-console` will enforce

Finding 2 in the catalog build-status doc proposes the natural first dependency rule once `human-review-console` is
`Built`: **any consequential action that sets `requires_human_review` MUST route to `human-review-console`**. That is
P-06 getting a system enforcer instead of terminating in a per-repo boolean. The case half
satisfies that rule at source: a case that escalates routes into the console in-process, with
no separate service to reach.

## Same posture across the merge

The case engine adds domain surface, not a second control plane. It runs in the same Cloud Run
service, under the same runtime SA, the same CMEK key set, the same residency pin
(`asia-southeast1`) and the same WORM audit trail as the review console. The added infra (a Firestore
`(default)` database with `cases` and `reviews` subcollections per tenant, a Cloud Tasks queue for
deadlines, a Pub/Sub topic for lifecycle events) inherits those controls rather than introducing a
new trust boundary.

## Appendix: regulator crosswalk (adopter-owned)

**Accountable owner: the adopting institution's Head of Compliance (or the equivalent second-line
control owner named in the deployment's approval record).** Not the maintainers of this repository,
and not the deploying engineer. The mapping below is a starting template for the home jurisdiction,
not legal advice: the accountable owner re-reviews every row with local counsel before it is used
in a supervisory conversation, and owns any gap it leaves open. Record the named individual and
the review date in the adopter's own control register (see
[`docs/ADOPTING.md`](docs/ADOPTING.md), which lists this appendix as adopter-owned).

The `P-*` / `R*` columns above are this build's internal control language. A regulated adopter maps
them onto its own supervisor's requirements. The rows below are the **MAS (Singapore) reference
mapping**; a fork adds a table per additional regulator.

| `human-review-console` control | Evidence in this repo | MAS reference | What a supervisor looks for |
|---|---|---|---|
| P-06 four-eyes, SoD, N-eyes, fail-closed eligibility | `src/review_console/domain/maker_checker_service.py`, `tests/test_maker_checker_service.py` | MAS Notice 626 §6 (senior-management oversight); MAS FEAT (Accountability) | A qualified, independent human disposes of every consequential action; a maker can never approve their own work |
| P-06 approval floors owned by the institution | `config/policy.json`, `tests/test_routing_policy_config.py` | MAS Guidelines on Risk Management (delegated authority) | Approval thresholds are set by the bank's policy owner and evidenced, not hard-coded by a vendor |
| P-07 tamper-evident sign-off trail | `src/review_console/adapters/local/audit.py`, `infra/terraform/logging_worm.tf`, `tests/test_audit_anchor.py` | MAS Notice 626 §11 (record keeping, 5 years); MAS TRM (auditability) | An immutable, reproducible record of who approved what and when, and a stated retention window |
| P-09 verified identity, tenant isolation, least privilege | `src/review_console/adapters/gcp/identity.py`, `infra/terraform/iam.tf`, `tests/test_api.py` | MAS TRM (access control); MAS Notice 626 §8 | Server-verified identity, entitlement-gated approval rights, no cross-tenant visibility |
| P-03 residency, CMEK, perimeter | `src/review_console/config.py` (`RESIDENCY_ALLOWLIST`), `infra/terraform/org_policy.tf`, `kms.tf`, `vpc_sc.tf`, `tests/test_residency_parity.py` | MAS Outsourcing and Cloud guidelines; MAS TRM | In-country data residency, customer-managed keys, a controlled boundary and evidence of enforcement on the live project |
| P-10 clocks and escalation on regulated deadlines | `src/review_console/domain/cases/clock.py`, `tests/test_clock.py` | MAS Notice on complaints handling; FAA/SFA response windows | Regulated response windows are tracked, warned on and escalated rather than missed silently |
| P-12 documented exit | `docs/onprem-migration.md`, `scripts/portability_demo.py` | MAS Outsourcing (exit strategy) | A demonstrable, tested path off the managed stack |
| P-04 minimisation before logging | `src/review_console/domain/pii.py` (shared `pii-kit`), `tests/test_not_falsely_green.py` | PDPA (protection, data minimisation) | Personal data is redacted before it is retained anywhere it does not need to be |

**To add another regulator** (FCA, HKMA, RBI, OJK, APRA, ...): copy this table, replace the MAS
column with that supervisor's instrument and section numbers, and re-review the last column with
local counsel. The `human-review-console`-control and evidence columns are stable across regulators; only the mapping
changes. `compliance-advisory`'s control-mapping module (`domain/control_mapping/` in `compliance-advisory`)
generates and maintains these crosswalks at scale, so a large estate should integrate it rather
than hand-maintaining this table.
