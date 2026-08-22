# Compliance FAQ

### Does Hrz7 auto-approve business actions?

No. Hrz7 determines whether a human disposition is eligible and records the result. The consuming
system retains execution authority. Escalation raises the review bar and never lowers it.

### How can an auditor recompute a result?

Maker-checker eligibility, state transitions, clock maths, and escalation are deterministic
stdlib functions with pinned tests. Evidence records carry the decision, actor, state, findings,
and citations without relying on model output.

### Who owns production promotion?

Hrz4 owns the authoritative AI quality and model-risk promotion decision. Hrz7's offline eval is
a merge smoke check for its own deterministic invariants and must not be relabelled as a
production approval.

### Who owns regulator mapping?

The adopting institution's compliance function owns its regulator-specific crosswalk. Rsk1 owns
regulatory knowledge and can support cited analysis; Rgc9 owns exit-risk planning. This repository
does not claim that those systems have approved an Hrz7 deployment.

### How is the case, clock, and workflow scope governed?

Case transitions, clocks, escalation, and history use the same identity, tenant, audit, residency,
and release controls as the review console. The module is not a second control plane.

