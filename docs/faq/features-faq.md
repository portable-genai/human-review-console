# Features FAQ

### What does Hrz7 own?

Hrz7 owns deterministic maker-checker decisions, the tenant-partitioned review queue, case state
transitions, clock calculations, escalation into human review, and the sign-off evidence contract.
It records approval state but never executes the underlying business action.

### What evidence does a reviewer see?

The live console groups each item by state and severity, shows producer citations, completed
independent checks, the approval count, gaps, and the next action. `make demo-selftest` drives this
real surface with fictional data and asserts each state.

### Which adjacent capabilities belong elsewhere?

| Concern | Catalog owner | Hrz7 boundary |
|---|---|---|
| Guardrail and DLP policy | Hrz1 | redact before Hrz7 evidence intake where customer PII is possible |
| Registry, identity, entitlements | Hrz3 | supply verified principals and approver groups |
| Promotion evaluation | Hrz4 | own the release promotion verdict |
| Enterprise traces and WORM audit | Hrz5 | own the production evidence sink |
| Multi-application journey hosting | Hrz9 | embed or link Hrz7 without reimplementing review |
| Exit and concentration planning | Rgc9 | assess the migration plan; Hrz7 supplies its adapter evidence |

### Is the case engine a separate service?

No. The case, clock, and workflow scope is a module in this service, so a case and the review it
creates share one process and one evidence boundary. The `ReviewRouterPort` is still a port, so an
adopter can choose a split deployment without changing domain code.

