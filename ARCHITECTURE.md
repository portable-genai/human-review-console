# ARCHITECTURE - `human-review-console` Case, Workflow & Human-Review Platform

## The hexagon

Two co-resident pure-stdlib domain cores (the review console and the case-workflow
engine) surrounded by typed ports, with adapter families selected by one env var. Every
consequential decision (four-eyes / SoD / N-eyes on the review side; transition legality, clock
breach and escalation on the case side) lives entirely in a domain and does no I/O; storage,
timers, events, audit and identity are reached only through ports. The `audit` and `identity` ports
are shared by both cores.

```
                 inbound (driving)                         outbound (driven)
        +-----------------------------+          +-------------------------------+
        |  api/app.py  (FastAPI)      |          |  ReviewStorePort              |
HTTP -> |    /v1/reviews*  /v1/cases* |          |  CaseStorePort                |
        |  cli/main.py (argparse)     |          |    local: in-memory (partition)|
        +--------------+--------------+          |    gcp:   Firestore (CMEK)     |
                       |                         |    onprem: fail-fast           |
                       v                         +-------------------------------+
        +-----------------------------+          +-------------------------------+
        |  domain/ (PURE, stdlib)     |          |  TimerPort (Cloud Tasks)       |
        |  - maker_checker_service    |  ports   |  EventPublisherPort (Pub/Sub)  |
        |    (four-eyes / SoD / N-eyes)+--------> |  AuditSinkPort (shared WORM)   |
        |  - console_service (orchestr)|         |  IdentityPort (shared, kit)    |
        |  domain/cases/ (PURE)       |          |    local: seeded personas      |
        |  - state_machine / clock    |          |    gcp:   IAP assertion         |
        |  - assessment               |          |    onprem: fail-fast           |
        |  - workflow_service (orchestr|         +-------------------------------+
        |    -> in-process router)    |          |  ReviewRouterPort              |
        +-----------------------------+          |    in-process -> this console  |
                       ^                         |    (split deploy: remote adptr)|
                       +-------------------------+-------------------------------+
```

## Layers

Review core:

- **`domain/kernel.py`** - vertical-neutral taxonomies (`Severity`, `Disposition`, `ReviewState`,
  `EligibilityFinding`, `Decision`) as commons `LenientStrEnum`s, plus `Citation` and the
  already-redacted `SignOffEvent`. Its `Decision` is `ALLOWED` / `DENIED`.
- **`domain/models.py`** - the artifact types: `ReviewRequest`, `ReviewDecision`, `Approval`, and
  the `ReviewItem` queue aggregate (request + state + collected approvals).
- **`domain/maker_checker_service.py`** - the pure engine: `RoutingPolicy` (consumer config),
  `check_eligibility`, and `dispose` returning a `DispositionOutcome`. No I/O, no clock, no
  randomness.
- **`domain/console_service.py`** - the orchestrator: submit / queue / dispose, redact-before-audit,
  one WORM sign-off per attempt, tenant-scoped loads. Never auto-executes.

Case core (`domain/cases/`):

- **`domain/cases/kernel.py`** - case taxonomies (`ClockKind`, `CaseFinding`, and `CaseDecision`).
  `CaseDecision` is `ALLOWED` / `ESCALATED` / `REJECTED`, distinct from the review `Decision` and
  never merged with it; plus the already-redacted `CaseAuditEvent`.
- **`domain/cases/models.py`** - `ClockSpec`, the consumer-supplied `WorkflowDefinition`,
  `Transition`, the `Case` aggregate (state + full history + attributes), `DeadlineStatus`,
  `CaseAssessment`.
- **`domain/cases/clock.py`** - the pure business-day / calendar deadline maths.
- **`domain/cases/state_machine.py`** - legal-transition validation and history append.
- **`domain/cases/assessment.py`** - the pure `assess`: compute clocks, flag findings, decide
  escalation.
- **`domain/cases/workflow_service.py`** - the orchestrator: open / transition / evaluate, wiring
  the pure engines to the case store / timer / event / audit ports, redacting before every audit
  write, and routing an escalation through the `ReviewRouterPort` (in-process).
- **`domain/cases/sample_workflows.py`** - an illustrative `complaint` definition so the API, CLI
  and demo run out of the box; a deployment replaces it.

Shared edges:

- **`ports/`** - `ReviewStorePort`, `CaseStorePort`, `TimerPort`, `EventPublisherPort`,
  `AuditSinkPort`, `ReviewRouterPort` (and `IdentityPort` from the commons), plus
  `ports/identity.py`: what an identity adapter DECLARES about the end-user authentication it
  provides (`VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`) and the refusal type that carries a
  status and a reason. The loopback exposure guard is derived from that declaration and from
  nothing else, least of all from a service credential.
- **`adapters/{local,gcp,onprem}/`** - the implementation families; gcp SDK imports are lazy.
  The explicit `platform` profile selects the reviewed gcp family because `human-review-console` is itself the
  shared platform service.
  `adapters/review_router.py` holds the in-process router (see below).
- **`api/`, `cli/`** - thin inbound adapters translating requests into domain calls; the CLI adds a
  `cases` subcommand.
- **`config.py`** - `Settings` + `Container`: the exact dotted `module:Class` binding table per
  runtime/data profile, a separate exact identity map, the shared `console` service, and the
  in-process `review_router`. Unknown profiles fail before adapter construction.

## The decision flow (a disposition)

1. `api/app.py` resolves the checker `Principal` (identity port); the client-asserted actor is
   discarded.
2. `console_service.dispose` loads the item within the checker's own tenant (a cross-tenant id is
   simply not found).
3. `maker_checker_service.dispose` runs `check_eligibility`. Any finding -> `DENIED` outcome, the
   item is returned unchanged, nothing is persisted as an approval.
4. On `ALLOWED`, the new item is stored; an approval that meets the required count flips the state
   to `approved`.
5. Either way, one already-redacted `SignOffEvent` is appended to the WORM sink.
6. The API returns 200 (allowed) or 403 (denied, with findings). The underlying action is never
   executed here; the consuming vertical acts on an `approved` item.

## The case lifecycle flow

1. **Open.** `api/app.py` resolves the `Principal`; `workflow_service.open_case` creates the case in
   the definition's initial state, schedules a timer per clock (Cloud Tasks in prod), emits
   `case.opened`, and writes a redacted `ALLOWED` case audit event.
2. **Transition.** The state machine validates the edge. Legal -> new immutable case + history entry
   + `case.transitioned` event + `ALLOWED` audit; on a terminal state, the clocks are cancelled.
   Illegal -> `REJECTED` audit event and a 409.
3. **Evaluate.** `assess` computes each clock's status and the findings. A load-bearing finding sets
   `requires_human_review`, records an `ESCALATED` audit event, emits `case.escalated`, and hands
   the case to the `ReviewRouterPort`, which opens a review in this service (see below). Nothing
   auto-advances.

## R8 self-routing is in-process

When a workflow escalates, `workflow_service` routes the case into human review through the
`ReviewRouterPort`. In this merged service the bound adapter (`adapters/review_router.py`,
`InProcessReviewRouter`) is wired to the SAME `ConsoleService` the review API serves, so an escalated
case becomes a queued review by a direct in-process call, with no network hop and no
service-to-service token exchange.

The case engine and the console share a process rather than reaching each other over a
signed S2S call through a `review-kit` client, so no kit router, signing key or
cross-service URL is needed between the two halves.

The `ReviewRouterPort` seam is kept precisely so a split deployment remains possible: a client who
wants the case engine and the console in separate services can bind a different `ReviewRouterPort`
adapter that targets a remote console over the network, with no change to `workflow_service`. The
port is the boundary; only the bound adapter differs.

## Why deterministic, and why soft

The maker-checker verdict, the transition legality, the clock breach and the escalation are exactly
the kind of consequential decisions the `deterministic-domain-service` discipline says must be pure
code an auditor can re-run, never an LLM. There is no LLM anywhere in this repo. And by P-06 the
console only records the human's sign-off and the case engine only flags and notifies (a human, via
the console, disposes); both escalate softly and never auto-execute, which is why the whole catalog
can route its `requires_human_review` escalations here, and every workflow vertical can inherit the
case spine, without granting `human-review-console` any execution authority.

## Dependencies

- `hex-service-kit` (pinned by tag): identity, S2S transport hardening, fail-closed network
  defaults, the hash-chained WORM log, the `StrEnum` kernel.
- `agent-eval-kit` (pinned by tag): the `--mode smoke|gate` eval scaffold and `assert_can_go_red`.
- `pii-kit` (pinned by tag): the jurisdiction PII pattern pack used to redact before audit.

Mandatory catalog dependencies at runtime: `agent-registry` (identity / entitlements) and `agent-observability` (WORM audit
trail). The case-workflow engine is not a separate runtime dependency: it is a module of this
service, so a case and the review it escalates share one process, one store and one audit
trail.
