# Portability FAQ

### What portability does `human-review-console` prove?

`make portability-demo` proves four bounded properties offline: complete explicit profile maps,
the same deterministic domain result across fresh local stacks, a verifiable local audit chain,
and an on-prem placeholder that fails fast instead of silently using GCP.

### What are the profiles?

- `local` is the working SDK-free stack for development, test, CI, and demos.
- `gcp` selects the managed Firestore, Cloud Tasks, Pub/Sub, WORM, and IAP adapters.
- `platform` explicitly selects the same managed adapters because `human-review-console` is itself the shared
  platform service. It does not delegate to another `human-review-console`.
- `onprem` is the reviewed adapter contract and migration boundary. It is not a completed
  sovereign deployment.

### Does the script prove full portability?

No. It does not claim live GCP behavior, a completed on-prem implementation, cross-store export
and reload, production identity, or every UI channel. Those require their own integration and
migration evidence. See [`docs/onprem-migration.md`](../onprem-migration.md).

### Is the UI portable?

The Next.js UI can run standalone or under a same-origin reverse-proxy subpath in embed mode.
That demonstrates channel packaging only. It does not prove runtime, identity, data, or audit
portability by itself.

