# Adoption FAQ

### How do we rebrand the repository?

Use `scripts/rename_fork.py --dry-run` first, then `--yes`. It covers the Python package, command,
environment prefix, distribution, and resource stem. Human policy and integration choices remain
in [`docs/ADOPTING.md`](../ADOPTING.md).

### How do we take upstream fixes?

Track semantic-version tags. Keep institution policy,
identity registration, on-prem adapters, evidence, and branding in the adopter-owned paths named
by `ADOPTING.md`, then rebase those changes onto each upstream release.

### How do we add a port?

Follow the full touch list in [`CONTRIBUTING.md`](../../CONTRIBUTING.md). The reverse-complete
contract test requires the Protocol map, binding map, profile coverage, adapters, container
property, behavior test, docs, and evidence to agree.

### Can we use the reference fixtures in production?

No. They are fictional demo evidence. Rebuild workflows, holidays, PII packs, policy, and eval
golden sets under institutional approval.

