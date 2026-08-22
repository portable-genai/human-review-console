# DEMO - Hrz7 Case, Workflow & Human-Review Platform

Two halves to see: the human-review console and the case, clock and workflow engine. Each
runs offline (no cloud, deterministic) and on managed cloud. One service serves both.

## Presenter-paced browser demo

Install the Python and locked UI dependencies once, including Chromium:

```bash
make install
cd ui && npm ci && npx playwright install chromium && cd ..
make demo
```

The runner starts its own local API and Next.js UI, opens a headed browser, prints narration-ready
notes only in the terminal, completes each action and proof, then waits for Enter. It uses a
temporary demo-owned review database and removes it on exit.

Useful controls:

```bash
node ui/scripts/console-demo-playwright.mjs --list
node ui/scripts/console-demo-playwright.mjs --from deny-self-approval
node ui/scripts/console-demo-playwright.mjs --no-pause --headless
node ui/scripts/console-demo-playwright.mjs --no-pause --headless \
  --screenshots /tmp/hrz7-demo-shots
```

The walkthrough proves, in order:

1. An analyst submits a high-severity disbursement for review. High severity routes to dual
   control (two distinct approvals required).
2. The analyst tries to approve their own item. Four-eyes refuses: `DENIED ['self_approval']`.
   Nothing is recorded as an approval.
3. A distinct approver provides the first eye. The item stays `pending` (1 of 2).
4. A second distinct approver clears it. The item is `approved` (2 of 2).
5. A second independent approver clears it and the item leaves the pending queue.
6. An other-tenant persona sees an empty queue while the real item exists.

Run the exact unattended CI path with `make demo-selftest`. The script asserts live state from the
running API and UI; it does not compare against canned screenshots.

## Offline domain and audit output

```bash
make demo-json
```

This deterministic script runs the same maker-checker domain service without a browser, prints the
four-eyes and dual-control trace, verifies the hash-chained sign-off trail, and writes
`console_demo.json`.

### The API, offline

```bash
make run-api     # http://127.0.0.1:8087, local profile, loopback bind
```

```bash
# Submit as the analyst persona (maker + tenant come from the persona, not the body).
curl -s localhost:8087/v1/reviews -H 'X-Dev-Persona: analyst' \
  -H 'Content-Type: application/json' \
  -d '{"action":"disburse_facility","subject":"Acme (FICTIONAL)","severity":"medium"}'

# The same persona cannot approve it (four-eyes -> 403). A distinct approver can.
curl -s -X POST localhost:8087/v1/reviews/<id>/decision -H 'X-Dev-Persona: approver' \
  -H 'Content-Type: application/json' -d '{"disposition":"approve","reason":"within limits"}'
```

Switch personas with the `X-Dev-Persona` header (`analyst`, `approver`, `auditor`, `other-tenant`).
The `other-tenant` persona sees an empty queue and gets a 404 on a demo-bank item: the tenant
partition, demonstrated.

### The console UI

```bash
cd ui && npm install && npm run dev    # http://localhost:3000
```

The queue view lists the tenant's pending items; open one to approve / reject / amend with a
reason. The persona picker (top of the page) switches the acting reviewer so four-eyes and the
tenant partition are visible in the browser.

## Case & workflow demo (local profile, no cloud)

The case engine ships a sample `complaint` workflow, so it runs out of the box. Drive it
from the CLI:

```bash
make install
review-console cases open complaint --tenant demo-bank     # -> opened <id> [received]
review-console cases transition <id> resolved              # REFUSED: illegal edge from "received"
review-console cases transition <id> under_review          # legal: received -> under_review
review-console cases evaluate <id>                         # prints clocks + escalation
review-console cases list --tenant demo-bank
```

`evaluate` computes each clock against the current instant. When the acknowledgement clock breaches,
`SLA_BREACH` is flagged, the case escalates softly, and the escalation opens a review in this same
service's queue (in-process), so the same `review-console queue --tenant demo-bank` now shows the
case waiting for a human. A planted, obviously fictional borrower identifier in the case attributes
is already redacted in every case audit record.

### The case API, offline

```bash
make run-api     # http://127.0.0.1:8087, local profile, loopback bind

# Open a case as the analyst persona (actor + tenant come from the persona, not the body).
curl -s localhost:8087/v1/cases -H 'X-Dev-Persona: analyst' -H 'Content-Type: application/json' \
  -d '{"case_type":"complaint","severity":"medium"}'

# Advance it along a legal edge; an illegal edge is a 409.
curl -s -X POST localhost:8087/v1/cases/<id>/transition -H 'X-Dev-Persona: analyst' \
  -H 'Content-Type: application/json' -d '{"to_state":"under_review"}'

# Assess its clocks and escalation.
curl -s -X POST localhost:8087/v1/cases/<id>/evaluate -H 'X-Dev-Persona: analyst'

# The registered workflow definitions.
curl -s localhost:8087/v1/workflows
```

The `other-tenant` persona gets a 404 on a demo-bank case: the tenant partition, demonstrated on the
case side too.

## Managed-cloud demo (gcp profile)

Prerequisites: a project with the APIs in `infra/terraform/apis.tf`, and `terraform apply` from
`infra/terraform` (fill in `terraform.tfvars` from the example). The service deploys behind an
internal load balancer with Cloud IAP, Firestore (CMEK) as the store (one `(default)` database with
`reviews` and `cases` subcollections per tenant), the Cloud Tasks queue for case deadline timers,
the Pub/Sub topic for case lifecycle events, and the Cloud Logging locked WORM bucket as the shared
sign-off / audit sink.

```bash
gcloud run services describe human-review-console --region asia-southeast1
```

Identity is the IAP-signed assertion (no persona picker outside `local`); the tenant comes from the
verified principal. Everything else behaves exactly as the offline demo, which is the point of the
SDK-free gate: the offline run is a faithful rehearsal of production.

Only synthetic, obviously fictional data appears in any demo.

## Bounded portability proof

```bash
make portability-demo
```

The proof executes exact profile-map coverage, deterministic local reruns, the local hash chain,
the explicit managed `platform` binding, the fail-fast onprem boundary, and unknown-selector
rejection. It does not prove live GCP, a completed onprem adapter, channel portability,
cross-store export and reload, or production identity.

## Stop and cleanup

Press Ctrl-C in an interactive walkthrough. The runner closes the browser, stops both child
services, and removes only its temporary demo database. For a separately started API or UI, stop
the terminal process that owns it.
