# On-prem migration (the sovereign-exit guide) - Hrz7

The reversibility proof for principle P-12. The domain cores (the review console and the
case-workflow engine) are pure standard library and every external edge is a port, so moving the
service off Google Cloud is a matter of writing the outbound adapters, not rewriting the system. The
`onprem` profile ships fail-fast placeholders that already satisfy the port Protocols, so the shape
is fixed and the contract test proves parity.

## What has to be rebound

| Port | GCP adapter | On-prem replacement |
|---|---|---|
| `ReviewStorePort` | Firestore (per-tenant path, CMEK) | any tenant-partitioned store: PostgreSQL / an internal document DB. Key by `(tenant, review_id)`; scope every query to the tenant. |
| `CaseStorePort` | Firestore (per-tenant path, CMEK) | the same store, keyed by `(tenant, case_id)` and holding the case state plus its transition history. |
| `TimerPort` | Cloud Tasks (case deadline timers) | any deferred-callback mechanism: a durable job queue or scheduler that fires a deadline callback per clock. |
| `EventPublisherPort` | Pub/Sub (case lifecycle events) | any message bus, or a no-op sink if the client does not consume lifecycle events. |
| `AuditSinkPort` | Cloud Logging locked WORM bucket | the client's own append-only / WORM store (a retention-locked object store, or the shared hash-chained log persisted to disk). Shared by both halves. |
| `IdentityPort` (commons) | IAP-signed assertion | the client's OIDC / SAML IdP: verify the token, map it to a `Principal` (subject, tenant, groups). |

The identity replacement carries one extra obligation, and it is what lets the deployment serve
anything but loopback. The shipped `onprem` placeholder declares `end_user_auth = UNIMPLEMENTED`
(`src/review_console/ports/identity.py`), so the loopback exposure guard treats the deployment as
one that can authenticate nobody and refuses every non-loopback peer. Bind the real adapter under
`_IDENTITY_BINDINGS['onprem']` in `config.py` and declare `end_user_auth = VERIFIED` on it, which
is a claim that it resolves a principal from something it verifies SERVER SIDE (signature, issuer,
expiry) rather than from a header the caller wrote. The guard reads the binding, so that
declaration alone lifts the bound. Setting `REVIEW_S2S_TOKEN` does not and must not: it
authenticates a calling service and no end user.

Nothing else changes: the maker-checker engine, the case state machine and clocks, the
orchestrators, the API and the CLI are all profile-agnostic. The `ReviewRouterPort` stays bound
in-process (an escalated case opens a review in the same process), so it needs no on-prem adapter
unless the client splits the two halves into separate services.

## Steps

1. Implement the three adapters under `src/review_console/adapters/onprem/`, each with the single
   `__init__(self, settings: Settings)` constructor, replacing the `NotImplementedError` bodies.
2. Point the bindings at them (they are already wired in `config.py` `_BINDINGS["...":"onprem"]`).
3. Run the contract-parity test: it constructs every port under the `onprem` profile and asserts
   Protocol conformance, so a missing method fails fast.
4. Run the full gate under `REVIEW_PROFILE=onprem` for the adapters you can exercise offline.
5. Map the residency and CMEK controls to the on-prem equivalent (disk encryption, network
   perimeter); the `infra/terraform` controls in `COMPLIANCE.md` name what each one protects.

## What stays identical off-cloud

- The four-eyes / SoD / N-eyes decision (pure code, no cloud dependency).
- The redact-before-audit discipline (`pii-kit` is pure stdlib).
- The tenant partition (enforced in the domain, independent of the store).
- The sign-off record shape and its hash chain, if you reuse the shared `HashChainedAuditLog`.

The SDK-free hard gate is the guarantee: it already runs the whole system with no Google Cloud SDK
installed, so the on-prem target is a rebinding exercise, not a port.
