# Security FAQ

### Can a browser assert its own actor or tenant?

No. Per-user routes resolve a server-side `Principal`; request models do not carry actor, checker,
maker, or tenant fields. The local persona header is accepted only by the local profile.

### How is object isolation enforced?

Review and case stores key every lookup by tenant. The API always supplies the verified
principal's tenant, and cross-tenant identifiers resolve as not found. The browser self-test
proves that an other-tenant persona sees an empty queue.

### How is service intake authenticated?

`/v1/service/reviews` requires the shared S2S verifier. A service may carry the originating maker
and tenant only after caller authentication. Per-hop on-behalf-of token exchange remains a
documented future hardening layer.

### Where does immutable audit live?

The local profile writes an append-only hash chain through `hex-service-kit`. Production writes
to the locked WORM sink owned operationally by `agent-observability`. The local chain is useful tamper evidence,
but it is not a replacement for external anchoring and locked retention.

### Are secrets committed?

No. The repository names environment variables and Terraform inputs. Production secret values,
identity registrations, and keys belong in the institution's approved secret and key managers.

