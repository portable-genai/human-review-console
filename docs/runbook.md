# Runbook - `human-review-console` Human-Review & Maker-Checker Console

Operating the console: deploy, observe, respond, roll back.

## Service shape

- Cloud Run v2 service `human-review-console`, region `asia-southeast1`, internal +
  load-balancer ingress only, behind Cloud IAP.
- Store: Firestore native (per-tenant collection path, CMEK, delete-protected).
- Sign-off sink: Cloud Logging locked WORM bucket (`review-console-signoff`, 7-year retention).
- Identity: exact-audience IAP verification followed by the reviewed `agent-registry` subject map in
  `REVIEW_IAP_ENTITLEMENTS_JSON` (`REVIEW_PROFILE=gcp`).

## Deploy

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id + digest-pinned image
terraform init && terraform plan               # rejects an out-of-region value
terraform apply
```

The image must be built from a clean `main` (the CI `docker` job proves it builds). The image
itself defaults to the secure profile (`REVIEW_PROFILE=gcp`), and the Cloud Run service sets the
same value explicitly, so an image run without the Terraform environment fails closed on identity
rather than serving seeded dev personas. Only a dev or demo run opts down to
`REVIEW_PROFILE=local`, and that choice must be explicit: with the variable unset the seeded
personas are refused.

## The loopback exposure guard

`add_loopback_exposure_guard`, registered on the app OBJECT in `api/app.py`, refuses every route
to a peer that is not loopback (or that arrives through a proxy) while this deployment cannot
authenticate an end user. It is on the app object, not in `main()`, because the Dockerfile `CMD`
and `make run-api` both hand `review_console.api.app:app` to uvicorn and never call `main()`.

**One thing switches it off: the identity adapter the active binding names declaring that it
VERIFIES the end user** (`src/review_console/ports/identity.py`). Three situations therefore keep
it on, and all three are bounded:

1. no profile was chosen, so nobody selected an identity scheme at all;
2. `REVIEW_PROFILE=local`, where a seeded persona arrives on the `X-Dev-Persona` header the
   caller wrote, which is a picker and not authentication;
3. `REVIEW_PROFILE=onprem`, where the identity placeholder resolves nobody until an IdP is bound.

`REVIEW_PROFILE=gcp` and `REVIEW_PROFILE=platform` bind the IAP adapter, which verifies a signed
assertion before reading a claim, so the guard stands down and the routes do the refusing: a
peer with no assertion gets 401 and `/healthz` keeps answering the platform's health checks.

**Setting `REVIEW_S2S_TOKEN` does NOT switch the guard off.** That secret authenticates a calling
SERVICE and no end user, so it closes `/v1/service/*` and changes nothing else. While it did
decide the guard, a deployment with the token set answered a LAN peer holding no credential with
the seeded persona list, the tenant's review queue, and a real maker-checker sign-off.

To serve an on-premises deployment off loopback, bind the client's own verifying IdP adapter
under `_IDENTITY_BINDINGS['onprem']` in `config.py` (see `docs/onprem-migration.md`) and declare
`end_user_auth = VERIFIED` on it. The guard reads the binding, so that alone lifts the bound.
`REVIEW_ALLOW_INSECURE_DEMO=1` is the only other way out, and it accepts the exposure rather than
removing it: use it for a demo on a trusted network, never for a deployment.

`scripts/prove-exposure-matrix.sh` drives the whole matrix (profile x token x persona header)
against uvicorn over a real socket from this machine's LAN address, and asserts every cell.

## Health and observability

- Liveness / readiness: `GET /healthz` (returns status, profile, region). Cloud Run probes hit it.
- The sign-off trail is the audit source of truth: query the `review-console-signoff` log for
  `decision`, `action`, `state`, `severity` and the actors. Records are already redacted and carry
  no raw identifiers.
- There is no model and no token spend to watch; the decision path is O(1) pure code.

## Common tasks

- **Confirm a specific approval happened:** filter the sign-off log by `review_id` and
  `decision="allowed"`; the `checker` and `state` fields are the evidence.
- **Investigate a refused approval:** filter by `decision="denied"`; the `findings` array names why
  (self-approval, wrong tenant, insufficient role, SoD, duplicate approver).
- **Verify chain integrity (local / export):** `HashChainedAuditLog.verify_chain()` (exposed via
  the local audit adapter) re-derives every hash and reports the first bad sequence.

## Alerts to wire (log-based)

- A spike in `decision="denied"` with `self_approval` may indicate a vertical is mis-wiring the
  maker identity.
- Any `WRONG_TENANT` finding in the sign-off trail: the domain caught a cross-tenant attempt that
  the store partition should already have blocked. Investigate the calling path.
- Cloud Run 5xx rate, and any Firestore permission-denied (CMEK / IAM drift).

## Roll back

Cloud Run keeps revisions; route traffic back to the last known-good revision:

```bash
gcloud run services update-traffic human-review-console \
  --region asia-southeast1 --to-revisions <previous-revision>=100
```

The store and the sign-off trail are append-only and forward-compatible (`dataclass_from_jsonable`
ignores unknown fields), so a rollback of the service never invalidates existing records.

## Failure modes

- **Firestore unreachable:** disposition and submit calls fail; nothing is silently approved. The
  client retries; no partial sign-off is written (the WORM record is written after the store put).
- **IAP misconfigured:** identity resolution raises and every guarded route returns 401. No request
  proceeds without a verified principal.
- **Entitlement map missing or stale:** a verified but unmapped subject receives 401. Update the
  reviewed `agent-registry` export; never infer approver groups from an email domain or browser field.
- **S2S secret rotation:** update `REVIEW_S2S_TOKEN` (or the allowed-callers audience) on the
  service; the S2S endpoint fails closed until the caller presents a valid token.
