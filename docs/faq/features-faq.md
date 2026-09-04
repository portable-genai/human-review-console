# Features FAQ

### What does `human-review-console` own?

`human-review-console` owns deterministic maker-checker decisions, the tenant-partitioned review queue, case state
transitions, clock calculations, escalation into human review, and the sign-off evidence contract.
It records approval state but never executes the underlying business action.

### What evidence does a reviewer see?

The live console groups each item by state and severity, shows producer citations, completed
independent checks, the approval count, gaps, and the next action. `make demo-selftest` drives this
real surface with fictional data and asserts each state.

### Which adjacent capabilities belong elsewhere?

| Concern | Catalog owner | `human-review-console` boundary |
|---|---|---|
| Guardrail and DLP policy | `agent-guardrail-gateway` | redact before `human-review-console` evidence intake where customer PII is possible |
| Registry, identity, entitlements | `agent-registry` | supply verified principals and approver groups |
| Promotion evaluation | `model-quality-gate` | own the release promotion verdict |
| Enterprise traces and WORM audit | `agent-observability` | own the production evidence sink |
| Multi-application journey hosting | `journey-portal` | embed or link `human-review-console` without reimplementing review |
| Exit and concentration planning | `operational-resilience-mapping` | assess the migration plan; `human-review-console` supplies its adapter evidence |

### Is the case engine a separate service?

No. The case, clock, and workflow scope is a module in this service, so a case and the review it
creates share one process and one evidence boundary. The `ReviewRouterPort` is still a port, so an
adopter can choose a split deployment without changing domain code.

