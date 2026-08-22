# Contributing - Hrz7 Human-Review & Maker-Checker Console

## The hard gate (green before anything lands)

```bash
make check      # ruff check + ruff format --check + mypy src (strict) + pytest + eval
```

Every one of these must pass, SDK-free, on the `local` profile:

- `ruff check src tests eval` and `ruff format --check src tests eval` (ruff pinned exactly).
- `mypy src` in strict mode.
- `pytest -m 'not integration'`.
- `python eval/run_eval.py` (offline smoke; both metrics meet threshold).

CI runs the same gate plus `docker build`, `npm audit --audit-level=high` on `ui/`, and `pip-audit`
on both lockfiles. The gate installs only the `[dev]` extra, never the cloud SDK: passing with no
Google Cloud SDK installed is the portability proof.

## Hexagon rules

1. **Keep the domain pure.** Nothing under `domain/` imports a web framework or a cloud SDK. The
   maker-checker decision reads no clock and no randomness; pass `as_of` in.
2. **Lazy SDK imports in gcp adapters.** Every `google.*` import lives inside a method, so the
   `local` / `onprem` profiles import cleanly with no SDK installed.
3. **One adapter constructor:** `def __init__(self, settings: Settings)`.
4. **Identity from the principal, never the body.** No request schema carries `maker`, `checker`,
   `tenant` or `actor`. Add none.
5. **Fail closed.** Any eligibility finding denies. Tenant isolation is enforced in the domain AND
   the store. A new consequential path defaults to deny / escalate, never allow.
6. **Redact before audit.** Anything written to the WORM sink runs through `pii-kit` first.
7. **Contract test for parity.** If you add a port, add it to `ports/__init__.py` `__all__`, the
   reverse-complete protocol map, and the binding table; give it local, gcp, platform, and onprem
   bindings.
8. **Tests are the spec.** Every new eligibility finding or state transition gets a test that
   triggers exactly it, plus a not-falsely-green test if it feeds an eval metric.

## Commits

Work on a feature branch and keep each slice independently reviewable. Commits are authored solely
by the repository owner (no co-author trailers). No em-dashes in markdown, HTML, commit messages
or PR bodies. Synthetic, obviously fictional data only.

## Adding an adapter

1. Implement `Adapter(settings)` in the correct profile family.
2. Keep cloud SDK imports lazy.
3. Add the exact dotted binding in `config.py`.
4. Extend constructor, Protocol-conformance, fail-fast, and behavioral-parity tests.
5. Update the port table, runbook, adoption guide, and bounded portability proof when the claim
   changes.

## Adding a port or sub-service

1. Add one `@runtime_checkable` Protocol file and re-export it from `ports/__init__.py`.
2. Add it to the reverse-complete protocol map in the contract test.
3. Implement local, gcp, platform, and onprem adapters with the single-settings constructor.
4. Add exact bindings and a typed cached property to `Container`.
5. Wire the orchestrator and inbound API or CLI without importing adapters into the domain.
6. Add structural tests, deterministic behavior tests, and a fail-fast onprem test.
7. Update `ARCHITECTURE.md`, `SPEC.md`, `COMPLIANCE.md`, `docs/ADOPTING.md`, FAQs, demo,
   portability proof, and `docs/practices-audit.md`.
8. Run the Python hard gate, UI tests and build, demo self-test, portability proof, dependency
   audits, container build, Terraform checks, and link checks.

## Do not hardcode counts

Enumerate ports, findings and controls by name (one row each), never by a running total. The
`ports/__init__.py` `__all__` plus the parity test are the source of truth for what exists.
