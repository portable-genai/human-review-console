# Adopting `human-review-console` as an institutional base

`human-review-console` is a reusable case, workflow, and human-review platform. A regulated institution can fork it
to own its maker-checker service while retaining the deterministic domain rules, typed ports,
tenant boundary, immutable evidence contract, and offline gate.

Read this guide with [`ARCHITECTURE.md`](../ARCHITECTURE.md),
[`CONTRIBUTING.md`](../CONTRIBUTING.md), the role-specific [`faq/`](faq/).

## 1. Kernel and vertical boundary

| Ownership | Paths | Adoption rule |
|---|---|---|
| Upstream kernel | `domain/kernel.py`, `domain/cases/kernel.py`, clock maths, state-machine mechanics, ports, container wiring, contract tests, eval harness mechanics | Take upstream fixes. Avoid institution-specific policy here. |
| Institution policy | routing floors in `config/policy.json` (or your own file via `REVIEW_POLICY_PATH`), workflow definitions, holiday calendars, entitlement group names, case severities and clocks | Replace with approved policy, configuration, and regression tests. |
| Institution integration | `adapters/onprem/`, deployment variables, identity registrations, `agent-registry` and `agent-observability` bindings, UI branding | Own these files and review them on every upstream release. |
| Institution evidence | synthetic fixtures, eval golden sets, compliance crosswalk, operational evidence | Rebuild and approve for the institution. Do not inherit reference evidence as production proof. |

The kernel defines stable evidence and decision types. The product models in
`domain/models.py` and `domain/cases/models.py` import from the kernel, never the other way around.

## 2. Upstream merge strategy

Track upstream with semantic-version tags. Rebase the
institution-owned files above onto each release instead of continuously merging upstream `main`.
Run the complete gate after every rebase. If an upstream change alters a port, apply the full
extension touch list in [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## 3. Mechanical rename

Preview the package, command, environment prefix, distribution, and resource changes:

```bash
python scripts/rename_fork.py \
  --package acme_review_platform \
  --cli acme-review \
  --env-prefix ACME_REVIEW \
  --resource acme-review-platform \
  --dry-run
```

Apply only after reviewing the output:

```bash
python scripts/rename_fork.py \
  --package acme_review_platform \
  --cli acme-review \
  --env-prefix ACME_REVIEW \
  --resource acme-review-platform \
  --yes
```

Recreate the virtual environment after the package rename, install the locked dependencies, and
run `make check`, `make demo-selftest`, and `make portability-demo`.

## 4. Human decisions the script cannot make

1. **Region and residency.** Select the approved location, Org Policy scope, encryption keys,
   retention, backup, and disaster-recovery owner.
2. **Identity and entitlement.** Register IAP or the institutional identity provider, map tenant
   and approver groups through `agent-registry`, and keep local personas restricted to local loopback demos.
3. **Workflow policy.** Approve every state, legal transition, terminal state, clock, holiday
   calendar, escalation trigger, and severity rule.
4. **Maker-checker policy.** Approve the minimum reviewer count, segregation groups, delegated
   authority, rejection and amendment reasons, and high-value step-up requirements.
5. **PII jurisdiction pack.** Select the institution's jurisdictions and test planted identifiers
   independently from the runtime redactor.
6. **Evidence and fixtures.** Replace the fictional examples and rebuild the eval golden set.
7. **Regulatory crosswalk.** Compliance owns the regulator-specific mapping. The appendix
   "Regulator crosswalk (adopter-owned)" in [`../COMPLIANCE.md`](../COMPLIANCE.md) is the MAS
   template to start from: name the accountable owner (Head of Compliance or the equivalent
   second-line control owner), re-review every row with local counsel, and record the owner and
   review date in your own control register. `compliance-advisory` can provide regulatory knowledge, but this
   repository must not claim a crosswalk the adopter has not approved.
8. **Managed integrations.** Wire `agent-observability` as the enterprise WORM and observability owner, `model-quality-gate` as
   promotion authority, and `journey-portal` as a journey host where required.

## 5. Adoption checklist

- [ ] Previewed and applied `scripts/rename_fork.py`, then recreated the environment.
- [ ] Chosen region, encryption, retention, backup, restore, and incident owners.
- [ ] Registered production identity and `agent-registry` entitlement mappings.
- [ ] Replaced and approved workflow and maker-checker policy.
- [ ] Selected PII jurisdictions and independent false-green fixtures.
- [ ] Rebuilt synthetic fixtures, eval data, and the adopter-owned regulator crosswalk.
- [ ] Wired `agent-observability` and `model-quality-gate` promotion integrations.
- [ ] Ran `make check`, `make demo-selftest`, `make portability-demo`, the UI build, dependency
  audits, container build, and Terraform validation.
- [ ] Recorded the upstream tag and all institution-owned divergences.

