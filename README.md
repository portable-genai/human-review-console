# human-review-console (`human-review-console`)

**Case, Workflow & Human-Review Platform.** One deployable service that pairs a tenant-partitioned
human-review console (four-eyes / segregation-of-duties routing, approve / reject / amend with a
reason, a write-once (WORM) sign-off trail) with the deterministic case spine that feeds it (a
legal-transitions state machine, SLA and regulatory clocks with business-day deadline maths, and
soft escalation). The case-workflow engine is a module of this service (`domain/cases/`): a
workflow that breaches or stalls escalates a case straight into the review queue, in-process.

The console half is the enforcer for principle **P-06** ("escalates softly to a human, never
auto-executes"). Across the catalog that posture was asserted in many rows but had no system behind
it: an escalation terminated in a per-repo boolean with no queue, no reviewer UI and no sign-off
evidence. `human-review-console` gives P-06 a real, auditable destination that serves every built vertical and every
planned one. The case half is the shared deterministic case spine workflow verticals inherit
instead of rebuilding, so a regulatory-clock bug is fixed once, here, rather than in every vertical.

The platform owns **no vertical policy**. Each consumer supplies its own routing (how many
approvals an action needs, which segregation group a maker sits in) and its own workflow (states,
transitions, clocks, escalation rules, as a `WorkflowDefinition`), exactly as `agent-guardrail-gateway` the Guardrail
Gateway owns no vertical prompt. What `human-review-console` owns is the deterministic maker-checker decision, the
case mechanics (is this transition legal, has this clock breached, is this case stuck, does this
escalate), and the sign-off trail.

One Cloud Run service (port 8087) serves both API families: the human-review console API
(`/v1/reviews*`, `/v1/service/reviews`) and the case/workflow engine (`/v1/cases*`,
`/v1/workflows`). The review API surface is frozen and unchanged (external consumers pin it); the
case and workflow routes are purely additive.

## What it guarantees

### Human review (the console)

- **Four-eyes, mechanically.** A maker can never approve their own work. `SELF_APPROVAL` is a
  fail-closed eligibility finding in a pure domain function, not a convention someone has to
  remember. It cannot be shaped around by the request body, because the checker's identity comes
  only from the server-verified principal.
- **Segregation of duties.** A checker who shares the maker's SoD group is refused
  (`SEGREGATION_OF_DUTIES`), configurable per consumer.
- **N-eyes / dual control.** Consequential actions can require two or more *distinct* approvals
  (none of them the maker, none of them each other); severity drives the default.
- **Least privilege.** Only a principal holding the approver entitlement may dispose
  (`INSUFFICIENT_ROLE`).
- **Tenant isolation, fail-closed.** The queue is partitioned by tenant. A reviewer in one tenant
  can neither see nor act on another tenant's items; a cross-tenant id returns 404, never a leak.
- **WORM sign-off.** Every disposition attempt, allowed or denied, writes one immutable,
  already-redacted, hash-chained sign-off record. PII is redacted before the write.
- **Nothing auto-executes.** The console records the human's sign-off and returns the outcome; the
  consuming vertical acts on an `approved` item. That is the whole point of P-06.

### Cases and workflow (the engine)

- **A legal-transitions state machine.** A case only moves along edges the consumer declared; an
  illegal transition is refused (409) and recorded, never silently applied. Every change is appended
  to an immutable transition history.
- **Correct regulatory-clock maths.** "Within N business days" is a compliance phrase (MAS, APRA,
  HKMA turnaround rules), and weekend / holiday counting is where it goes wrong. The business-day
  and calendar-day deadline maths is pure, holiday-aware, and exhaustively unit-tested, so it is
  right once for every consumer.
- **Deterministic assessment.** Given a case and an `as_of` instant, the engine computes each
  clock's status (breached / approaching / on track) and flags a stalled case, always the same way.
- **Soft escalation, in-process.** A breach or a stall sets `requires_human_review` and routes the
  case straight into this service's own review queue via an in-process call. The engine records and
  notifies; it never advances a case on a consumer's behalf.

### Two decision vocabularies, kept distinct

The review side records a `ReviewDecision` of `ALLOWED` or `DENIED` (a disposition either passed
the four-eyes / SoD checks or it did not). The case side records a `CaseDecision` of `ALLOWED`,
`ESCALATED` (routed to a human, never auto-executed) or `REJECTED` (an illegal transition refused).
The two enums have different members and are kept separately named, never merged.

## Architecture

Hexagonal ports-and-adapters on the catalog commons. Two co-resident hexagons (the review console
and the case-workflow engine) share the `audit` and `identity` ports. The domain core is
pure standard library; every external edge is a `typing.Protocol` port with swappable adapter
families selected by one env var, `REVIEW_PROFILE`:

| Profile | Role | Backed by |
|---|---|---|
| `local` | dev / tests / CI, selected explicitly (`REVIEW_PROFILE=local`); never the container default | SDK-free in-memory queue + case store + in-memory timers / events + hash-chained WORM log + seeded personas |
| `gcp` | managed cloud | Firestore (tenant-partitioned) + Cloud Tasks timers + Pub/Sub events + Cloud Logging WORM sink + IAP identity (SDK imports lazy) |
| `platform` | explicit deployment of the `human-review-console` shared service | the same reviewed managed adapters as `gcp`; no delegation to another `human-review-console` |
| `onprem` | portability proof | fail-fast placeholders that satisfy the ports; the client wires their own store / timers / events / sink / IdP |

Ports (one row per port; the parity contract test and `ports/__init__.py` `__all__` are the
source of truth):

| Port | Responsibility |
|---|---|
| `ReviewStorePort` | tenant-partitioned review queue + sign-off store |
| `CaseStorePort` | tenant-partitioned case state + transition history |
| `TimerPort` | schedule / cancel a case deadline timer (Cloud Tasks) |
| `EventPublisherPort` | publish content-free case lifecycle events (Pub/Sub) |
| `AuditSinkPort` | append-only, already-redacted WORM trail (shared by both hexagons) |
| `IdentityPort` (from `hex-service-kit`) | resolve a server-verified `Principal` (checker / maker / actor, their tenant, their groups) |
| `ReviewRouterPort` | the R8 escalation seam: route an escalated case into human review (bound in-process to this service's own console; a split deployment can bind a remote-console adapter instead) |

The cross-cutting service layer (identity, S2S transport hardening, fail-closed network defaults,
the hash-chained WORM log, the `StrEnum` kernel) comes from
[`hex-service-kit`](https://github.com/portable-genai/hex-service-kit); the eval scaffold from
[`agent-eval-kit`](https://github.com/portable-genai/agent-eval-kit); the jurisdiction PII pattern
pack from [`pii-kit`](https://github.com/portable-genai/pii-kit). All three are pinned by tag.

## Documentation authority

When documents conflict, `SPEC.md` owns locked behavior, `ARCHITECTURE.md` owns boundaries and
sequences, `COMPLIANCE.md` maps those decisions to controls, and this README is the entry point.
Treat stale downstream wording as a defect and update it with the behavior change.

## Quick start

```bash
make install          # editable install with the dev toolchain (SDK-free)
make check            # the hard gate: ruff + mypy + pytest + eval
make run-api          # serve on http://127.0.0.1:8087 (local profile, loopback)
make demo             # headed, presenter-paced real API and UI walkthrough
make demo-selftest    # start the real API and UI, then assert every browser step
make portability-demo # bounded executable profile and audit proof
```

CLI (review commands, plus a `cases` subcommand for the case engine):

```bash
review-console submit disburse "Acme Holdings (FICTIONAL)" --severity high --maker demo.analyst@bank.example
review-console queue --tenant demo-bank
# A distinct approver may approve; the maker themselves is refused (four-eyes).
review-console decide <review_id> approve --checker demo.approver@bank.example

# The case, clock & workflow engine (a sample "complaint" workflow ships so it runs out of the box):
review-console cases open complaint --tenant demo-bank      # -> opened <id> [received]
review-console cases transition <id> under_review
review-console cases evaluate <id>                          # clocks + escalation
review-console cases list --tenant demo-bank
```

HTTP contract (all identity comes from the verified principal; no `actor` in any body). The review
routes are the frozen surface external consumers pin; the case and workflow routes are additive:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/reviews` | submit an item for review (maker + tenant from the principal) |
| `GET` | `/v1/reviews` | the pending queue for the caller's tenant |
| `GET` | `/v1/reviews/{id}` | one item within the caller's tenant (404 across tenants) |
| `POST` | `/v1/reviews/{id}/decision` | approve / reject / amend (checker from the principal; 403 on a fail-closed finding) |
| `POST` | `/v1/service/reviews` | S2S producer intake: a trusted service asserts maker + tenant |
| `POST` | `/v1/cases` | open a case (actor + tenant from the principal) |
| `GET` | `/v1/cases` | the caller's tenant's cases |
| `GET` | `/v1/cases/{id}` | one case + history + legal next states (404 across tenants) |
| `POST` | `/v1/cases/{id}/transition` | advance state (409 on an illegal edge) |
| `POST` | `/v1/cases/{id}/evaluate` | assess clocks + findings + escalation (a breach escalates in-process) |
| `GET` | `/v1/workflows` | the registered workflow definitions |
| `POST` | `/v1/audit/ping` | S2S liveness, fail-closed calling-service auth |
| `GET` | `/healthz` | status / profile / region (open) |
| `GET` | `/v1/personas` | seeded dev personas for the local picker (empty outside `local`) |

## The console UI

`ui/` is an embeddable Next.js micro-frontend (per the `embeddable-secure-ui` pattern): a queue
view and a per-item approve / reject / amend panel with a reason box, a local persona picker, and
CSP `frame-ancestors` set at both the API and the document layer so it drops into a host app
same-origin. See [`docs/embedding-and-identity.md`](docs/embedding-and-identity.md).

## Documentation

- [SPEC.md](SPEC.md) - the wire contract, profiles, and the eligibility rules in full.
- [ARCHITECTURE.md](ARCHITECTURE.md) - the hexagon, the ports, and the decision flow.
- [COMPLIANCE.md](COMPLIANCE.md) - each principle P-01..P-13 and rule R1..R7 mapped to a control.
- [docs/runbook.md](docs/runbook.md) - operate it: deploy, roll back, watch, respond.
- [docs/onprem-migration.md](docs/onprem-migration.md) - the sovereign-exit guide.
- [docs/ADOPTING.md](docs/ADOPTING.md) - fork boundary, rename tool, and human decisions.
- [docs/faq/](docs/faq/) - role-specific security, portability, feature, adoption, and compliance answers.
- [docs/practices-audit.md](docs/practices-audit.md) - A1 through G7 verdicts and evidence.
- [DEMO.md](DEMO.md) - the offline demo and the managed-cloud demo.
- [CONTRIBUTING.md](CONTRIBUTING.md) - the hard gate and the hexagon rules.

Region is pinned to `asia-southeast1`. Only synthetic, obviously fictional data appears anywhere
in this repo.
