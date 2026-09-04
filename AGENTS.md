# human-review-console

The shared working agreement is [`.github/AGENTS.md`](https://github.com/portable-genai/.github/blob/main/AGENTS.md).
It carries the architecture rules, the gate contract, the fleet invariants, the
falsification discipline, versions and house style, and it holds in every repository
here. Read it first. This file carries only what is specific to this one.

## What this is

Catalog id `human-review-console`. The shared destination for every requires_human_review escalation
the catalog raises: a tenant-partitioned review queue, four-eyes / segregation-of-duties
routing, approve / reject / amend with a reason, and a WORM sign-off record proving who
approved what and when.

## Concrete bindings

| | |
|---|---|
| Catalog id | `human-review-console` |
| Package | `src/review_console/` |
| Profile variable | `REVIEW_PROFILE` |
| Adapter families | `gcp`, `local`, `onprem` |
| Gate | `make check` |

That variable is read in one module and resolved in three states: unset is no choice,
set-and-empty raises rather than inheriting the unset behaviour, and an unknown value
raises. Both raises happen before the process can serve a request.

## What this repository still owes

The `Capability gaps` cell on this repository's row in the maintainer's system tracker
is the authoritative list. Its verdict against the shared checks, including the ones it
does not pass, is in [`docs/practices-audit.md`](docs/practices-audit.md).
