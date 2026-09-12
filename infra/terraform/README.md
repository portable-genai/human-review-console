# infra/terraform - deploy posture for `human-review-console`

Terraform that makes the console's cloud posture enforceable at plan time, not merely documented.
The reference cloud is Google Cloud; the shape (region allowlist, location Org Policy,
customer-managed keys, immutable audit, least privilege) maps to any managed cloud.

This is ONE deployable service that serves both the human-review APIs and the merged case/workflow
engine: a single Cloud Run service (port 8087), a single runtime service account, and a single CMEK
key set. The only additive infra the case side needs is a Cloud Tasks queue (deadline timers) and a
Pub/Sub topic (lifecycle events); case state lives in the same Firestore `(default)` database as the
review queue, partitioned by tenant.

`project_id`, `container_image`, the IAP inputs and `worm_locked` are the required inputs; residency
is pinned in `locals.tf` and validated in `variables.tf`, so a plan is rejected if a deploy would
place data out of country. `worm_locked` has no default on purpose: the sign-off bucket's lock is
irreversible, so a plan refuses until the deployment states it. A production deployment sets
`worm_locked = true` with `retention_days = 2557` (the ~7-year floor binds only when locked); a
reference or evaluation deployment sets `worm_locked = false` with its reason and stays destroyable.

| File | Control |
|---|---|
| `org_policy.tf` | residency: `gcp.resourceLocations` allowlist + no service-account keys (Workload Identity) |
| `kms.tf` | one regional CMEK key, per-service IAM bindings (Firestore, WORM bucket, Cloud Run) |
| `firestore.tf` | single `(default)` store, tenant-partitioned (reviews + cases subcollections), in-region, CMEK, delete-protected |
| `tasks_events.tf` | Cloud Tasks queue (case deadline timers) + Pub/Sub topic (case-lifecycle events), in-region |
| `logging_worm.tf` | retention bucket + sink for the sign-off trail; `worm_locked` has no default, a production deployment locks it (immutable, ~7 years), the reference deployment declines the lock and says so |
| `iam.tf` | least-privilege runtime SA + Cloud Tasks OIDC invoker SA (no exported keys) |
| `cloud_run.tf` | one internal-only service (8087), CMEK revision, `REVIEW_PROFILE=gcp` opt-in, exact IAP audience plus reviewed `agent-registry` entitlements, `REVIEW_*` case env, `/healthz` probes |
| `apis.tf` | enables only the managed services this stack uses (incl. cloudtasks + pubsub) |

```bash
cp terraform.tfvars.example terraform.tfvars   # fill in project_id + image
terraform init
terraform plan                                 # rejects an out-of-region value
```

The residency allowlist here is the same one the application validates at settings load, so code
and infra share one source of truth. Each control maps to a principle in
[`../../COMPLIANCE.md`](../../COMPLIANCE.md).
