# SPEC - `human-review-console` Case, Workflow & Human-Review Platform

## 1. Purpose and scope

`human-review-console` is one service with two co-resident halves:

- **The human-review console.** The shared destination for every `requires_human_review`
  escalation the catalog raises: a tenant-partitioned review queue, a deterministic four-eyes /
  segregation-of-duties engine, approve / reject / amend disposition with a reason, and an immutable
  WORM sign-off record. It is the system enforcer for principle P-06.
- **The case, clock & workflow engine** (`domain/cases/`). The shared deterministic
  case spine catalogue workflow systems inherit: a legal-transitions state machine with full
  history, SLA / regulatory clocks with business-day deadline maths, severity / routing and
  escalation, and a tenant-partitioned case store. A breach or a stall escalates a case straight
  into the review queue, in-process.

Out of scope by design: `human-review-console` does not execute the underlying action, does not own any vertical
policy (state machines, business rules, transitions, clocks, prompts are all consumer-supplied),
contains no LLM, and does not compute severity, eligibility or escalation from anything other than
the inputs a consumer gives it plus the server-verified principal.

## 2. Deployment profiles

Selected by the `REVIEW_PROFILE` env var, resolved in exactly one place
(`config.resolve_profile`). An unset variable selects the SDK-free adapter family, because the
alternative imports cloud SDKs that are not installed, but it is never read as consent: the
seeded-persona identity adapter refuses to serve, service-to-service authentication returns 401
because no scheme was chosen, CORS gets no allowlist, `X-Dev-Persona` is not accepted, HSTS is
emitted, and the bind stays on loopback. The shipped container image sets `gcp`. One profile
selects the adapter family for every port of both halves.

An unknown or mis-capitalised value is not a fourth case: `resolve_profile` validates what it
reads, and `api/app.py` resolves at module scope, so `REVIEW_PROFILE=bogus` or the typo
`REVIEW_PROFILE=Local` fails the process at boot instead of producing an app that already chose
its postures from a string nothing binds.

Residual limit, deliberately not closed here: with `REVIEW_PROFILE=local` chosen deliberately and
`REVIEW_S2S_TOKEN` unset, the `/v1/service/*` endpoints are unauthenticated. That is the
zero-secret offline demo posture, bounded by exposure rather than by authentication. The bound is
a guard on the app OBJECT (`add_loopback_exposure_guard`), which refuses that posture to any peer
that is not loopback or that arrives through a proxy, so it holds however the process was
started; the loopback bind check in `main()` is the same bound applied a second time, at
start-up, and covers only that one entry point. `REVIEW_ALLOW_INSECURE_DEMO=1` is the single
documented opt-out.

**What turns that bound on is the IDENTITY BINDING, and nothing else.** An end-user route is
authenticated when the identity adapter the active binding names can produce a verified
principal without trusting a header the client wrote, and the adapter DECLARES that on itself
(`src/review_console/ports/identity.py`):

| Profile | Identity binding | Declares | Guard |
|---|---|---|---|
| unset or set to an empty value | seeded personas, which refuse to construct | (no consent) | ON |
| `local` | `LocalIdentityAdapter`, seeded personas on `X-Dev-Persona` | client-asserted | ON |
| `onprem` | `OnPremIdentityAdapter`, a placeholder resolving nobody | unimplemented | ON |
| `gcp`, `platform` | `IapIdentityAdapter`, a verified IAP assertion | verified | OFF |

`REVIEW_S2S_TOKEN` takes no part in that decision. It authenticates a calling SERVICE and no end
user, so SETTING it does NOT switch the guard off and does not make the console safe to expose:
it closes `/v1/service/*` and nothing else. While it did decide the guard, setting it left a LAN
peer holding no credential able to submit, read and sign off maker-checker items as the seeded
approver persona. An on-premises deployment lifts the bound by binding its own verifying IdP
adapter under `_IDENTITY_BINDINGS['onprem']` (see `docs/onprem-migration.md`), which the guard
reads directly, not by setting a secret.

| Profile | Stores | Timers | Events | Audit sink | Identity | Cloud SDK |
|---|---|---|---|---|---|---|
| `local` | durable SQLite review queue plus in-memory case store | in-memory register | in-memory list | hash-chained WORM log (hex-service-kit) | seeded dev personas | none |
| `gcp` | Firestore native (per-tenant path, CMEK) | Cloud Tasks | Pub/Sub | Cloud Logging locked WORM bucket | IAP signed assertion | lazy |
| `platform` | explicit `human-review-console` managed binding, same adapters as `gcp` | Cloud Tasks | Pub/Sub | Cloud Logging locked WORM bucket | IAP signed assertion | lazy |
| `onprem` | fail-fast placeholder | fail-fast | fail-fast | fail-fast placeholder | fail-fast placeholder | none |

Any other profile value is rejected. Identity uses its own exact profile map, so a channel or
identity selector cannot silently alter the runtime/data profile.

## 3. The maker-checker decision (review, deterministic core)

Given a `ReviewItem` and a checker (identity, tenant, groups), `check_eligibility` returns every
reason the checker may not dispose of the item. Any non-empty result is a fail-closed denial.

| Finding | Fires when |
|---|---|
| `WRONG_TENANT` | the checker's tenant differs from the item's tenant |
| `SELF_APPROVAL` | the checker is the maker (four-eyes, P-06) |
| `SEGREGATION_OF_DUTIES` | SoD is enforced and the checker shares the maker's SoD group |
| `INSUFFICIENT_ROLE` | the checker lacks the approver entitlement (`group:approver`) |
| `DUPLICATE_APPROVER` | the checker already provided an approval on this item (N-eyes distinctness) |

Routing is consumer-supplied (`RoutingPolicy`): `required_approvals` is the stricter of the
request's ask and the per-severity floor. The shipped default floors critical and high at 2
approvals (dual control) and medium / low at 1. An `approve` that reaches the required count of
distinct approvals moves the item to `approved`; below it, the item stays `pending` awaiting the
next eye. `reject` and `amend` are terminal. A disposition on a terminal item is a 409.

The decision is pure: no clock read, no randomness, no I/O. The same inputs always yield the same
outcome and the same resulting item, so an auditor can re-run it and a test can pin it.

The review side records a `ReviewDecision` of `ALLOWED` or `DENIED`. The case side (below) records
a `CaseDecision` of `ALLOWED`, `ESCALATED` or `REJECTED`. The two enums have different members and
are kept separately named, never merged.

## 4. The case state machine (deterministic core)

A `WorkflowDefinition` (consumer-supplied) declares the states, the legal `(from, to)` transition
edges, the terminal states, the clocks, the escalation triggers, and the per-state dwell limits.
`transition()` moves a case along a legal edge and appends an immutable `Transition` to its history;
an illegal edge raises `IllegalTransition` (HTTP 409) and is recorded as a `REJECTED` case audit
event. The transition is pure: `as_of` is passed in, and the resulting `Case` is a new immutable
value.

## 5. The clocks (the primitive the engine exists to get right)

Each `ClockSpec` is a named deadline of `duration_days` from a start state, counted as `calendar`
or `business` days. The business-day maths skips weekends and a configurable holiday set:

- `add_business_days(anchor, n, holidays)` advances n business days, preserving time of day.
- `business_days_between(a, b, holidays)` is a signed business-day count.
- `deadline_for(spec, anchor, as_of, holidays)` returns a `DeadlineStatus`: the due instant, days
  remaining (negative if overdue), a `breached` flag, and an `approaching` flag (inside the
  `warn_ratio` window). A clock whose start state has not been reached is dormant (`due_at` null).

"Within N business days" is a regulatory phrase (MAS, APRA, HKMA turnaround rules), and the maths
is exhaustively unit-tested so it is right once for every consumer.

## 6. Case assessment and escalation

`assess(case, definition, as_of, holidays)` computes each clock's status and returns a
deterministic `CaseAssessment`: the deadlines, the findings (`SLA_BREACH`, `APPROACHING_DEADLINE`,
`STUCK_IN_STATE`, in a canonical order), and `requires_human_review` (true when any finding is in
the definition's `escalate_on`). A case that must escalate routes into this service's own review
queue via an in-process call (the `ReviewRouterPort` seam, bound in-process), records an
`ESCALATED` case audit event, and emits a content-free `case.escalated` lifecycle event. The engine
records and notifies; it never advances a case itself and never auto-executes.

## 7. Identity and tenancy

Identity is always a server-verified `Principal` (from `hex-service-kit`): the maker at submit
time and the checker at decision time on the review side, the actor on the case side, their tenant,
and their groups all come from the principal, never from the request body. No request schema
carries a `maker`, `checker`, `tenant` or `actor` field. Both the review queue and the case store
are partitioned by tenant, and a cross-tenant read returns 404 rather than confirming another
tenant's ids exist.

In `gcp` and `platform`, the adapter verifies the assertion against the exact
`REVIEW_IAP_AUDIENCE`, IAP public keys, and IAP issuer. The exact verified email or subject must
then exist in the reviewed `REVIEW_IAP_ENTITLEMENTS_JSON` `agent-registry` export, which supplies tenant,
expected hosted domain, and principals. A missing mapping, domain mismatch, or absent
`group:approver` fails closed; no entitlement is inferred from browser input or email domain.

## 8. HTTP contract

The review routes are the frozen surface external consumers pin; the case and workflow routes are
additive.

| Method | Path | Auth | Body | Returns |
|---|---|---|---|---|
| `POST` | `/v1/reviews` | principal | action, subject, summary, severity, required_approvals, sod_group, case_ref, citations | 201 `ReviewItem` |
| `POST` | `/v1/service/reviews` | S2S | the above + maker, tenant | 201 `ReviewItem` (the rule-R8 producer intake: a trusted service asserts maker + tenant) |
| `GET` | `/v1/reviews` | principal | - | 200 `[ReviewItem]` (pending, caller's tenant) |
| `GET` | `/v1/reviews/{id}` | principal | - | 200 `ReviewItem` / 404 |
| `POST` | `/v1/reviews/{id}/decision` | principal | disposition, reason, amendments | 200 allowed / 403 denied (with findings) / 404 / 409 |
| `POST` | `/v1/cases` | principal | case_type, severity, attributes, summary | 201 `Case` |
| `GET` | `/v1/cases` | principal | - | 200 `[CaseSummary]` (caller's tenant) |
| `GET` | `/v1/cases/{id}` | principal | - | 200 `Case` (+ history, legal next states) / 404 |
| `POST` | `/v1/cases/{id}/transition` | principal | to_state, reason | 200 `Case` / 409 illegal / 404 |
| `POST` | `/v1/cases/{id}/evaluate` | principal | - | 200 `Assessment` (deadlines, findings, escalation) |
| `GET` | `/v1/workflows` | open | - | 200 registered definitions |
| `POST` | `/v1/audit/ping` | S2S | - | 200 |
| `GET` | `/healthz` | open | - | 200 status/profile/region |
| `GET` | `/v1/personas` | open | - | 200 personas (empty outside local) |

A denied decision returns HTTP 403 with the eligibility findings in the body and records a
`DENIED` sign-off. Nothing auto-executes: an `approved` item is acted on by the consuming vertical.
An `evaluate` that escalates opens a review in this same service's queue (in-process) rather than
advancing the case.

## 9. Audit

Both halves share one WORM sink. Every disposition attempt, allowed or denied, writes one
`SignOffEvent`; every case action (open, transition, evaluate, and refused transitions) writes one
`CaseAuditEvent`. Each event is already redacted (reasons, summaries, case attributes run through
the shared `pii-kit` before the write) and carries no raw identifiers, only the decision, the
actors, the state and the citations. The local log is hash-chained and verifiable; the gcp sink is
a locked retention bucket.

## 10. The hard gate

`ruff check` + `ruff format --check` + `mypy src` (strict) + `pytest -m 'not integration'` +
`python eval/run_eval.py`, all SDK-free on the local profile. The eval scores the review metrics
`four_eyes_integrity` (0.99) and `pii_safety` (0.99) alongside the case metrics
`clock_accuracy` (0.99), `escalation_accuracy` (0.90) and `case_pii_safety` (0.99); the safety
metrics each have a not-falsely-green test proving they can go red.
