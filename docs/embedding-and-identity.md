# Embedding and identity - Hrz7 review console

The review console (`ui/`) is an embeddable micro-frontend: it drops into a host application
same-origin, with the reviewer's identity server-verified and the client-asserted actor discarded.
This follows the catalog's `embeddable-secure-ui` pattern.

## Three deployment shapes

1. **Local, no auth (dev / demo).** `REVIEW_PROFILE=local`, and it must be set explicitly: with
   the variable unset the seeded-persona adapter refuses to construct and the `/v1/service/*`
   endpoints return 401 (no profile means no S2S scheme was chosen), so a missing environment
   cannot hand out an unauthenticated `group:approver` and cannot accept an unauthenticated
   service submission either. The API resolves a seeded persona from
   the `X-Dev-Persona` header; the UI shows a persona picker fed by `GET /v1/personas`. Loopback
   bind only (the fail-closed default refuses `0.0.0.0` without an explicit opt-out).
2. **Embedded same-origin behind a reverse proxy.** The host serves the API and the UI under one
   origin (for example `/review`). Set `NEXT_PUBLIC_BASE_PATH=/review` so the UI and its assets
   mount under the sub-path, and `NEXT_PUBLIC_EMBED=1` so the UI drops its own page chrome and the
   host owns the frame. The host's IdP fronts both; the API reads the verified identity.
3. **Standalone behind Cloud IAP.** `REVIEW_PROFILE=gcp`. IAP injects the signed assertion; the
   `IapIdentityAdapter` verifies its exact audience, IAP public-key signature, and issuer. It then
   maps the exact verified subject through a reviewed Hrz3 export to tenant and principals. No
   persona picker.

## The identity contract

- No request body ever carries a `maker`, `checker`, `tenant` or `actor` field. The maker (at
  submit) and the checker (at decision) are the server-verified `Principal`; tenant and groups
  come from the reviewed Hrz3 subject map after IAP verification. A caller cannot assert an
  entitlement they do not hold.
- The four-eyes rule is evaluated against that verified identity: `checker == maker` is a
  `SELF_APPROVAL` denial no matter what the client sends.
- Tenant isolation: the queue is partitioned by the principal's tenant; a cross-tenant id returns
  404, never a leak.

## The console's Content-Security-Policy (one module, two enforcement points)

The whole document policy is built in `ui/lib/security-headers.mjs` and nowhere else, then read at
exactly two enforcement points:

| Layer | Emits | Why there |
| --- | --- | --- |
| `ui/proxy.ts` (per request) | `Content-Security-Policy`, `X-Frame-Options` | The policy carries a per-request script nonce, and a static header table cannot produce one. |
| `ui/next.config.mjs` (static) | `X-Content-Type-Options`, `Referrer-Policy`, HSTS | The only headers a static table can honestly express. |

The CSP is deliberately absent from `next.config.mjs`. Two layers both emitting one gives the
browser two policies to intersect, with the stricter directive winning per directive, which is
how an un-nonced `script-src` would come back on a console whose scripts now carry only a nonce.

`script-src` is `'self' 'nonce-<per request>' 'strict-dynamic'`, with no `'unsafe-inline'`. Next
serves its hydration bootstrap as an INLINE script, so the nonce is what lets the page hydrate at
all, and `'strict-dynamic'` lets that nonced bootstrap load its own chunks without loosening
anything else. Two conditions have to hold together or the console silently ships dead markup:

1. `proxy.ts` sets the policy on the REQUEST headers as well as the response. The request header
   is where Next reads the nonce it stamps onto every script tag; the response header is what the
   browser enforces.
2. `app/layout.tsx` sets `export const dynamic = "force-dynamic"`. Next can only stamp a
   per-request nonce onto a dynamically rendered route. On a statically prerendered one the header
   advertises a nonce that nothing carries, and `'strict-dynamic'` switches off the `'self'`
   fallback, so the page loads strictly LESS than it did before the nonce was added.

`next.config.mjs` refuses to build or boot when condition 2 is missing, and
`ui/scripts/assert-hydratable.mjs` (wired into `make ui-check` and CI) starts the BUILT server,
fetches the served document and asserts every script tag carries the response nonce. That last
check is not redundant: the CSP header is byte-identical whether the console hydrates or not, so
no header assertion can tell the two apart.

`'unsafe-eval'` appears in exactly one place, the dev-server branch, and it is not decoration:
with it removed, `next dev` logs `eval() is not supported in this environment` from React's
development build and the page never attaches. A `next build` artefact needs neither it nor the
HMR websocket, and the hydration proof runs against that artefact.

`style-src` keeps `'unsafe-inline'`: the Next runtime injects critical CSS with no nonce path.

## Anti-clickjacking (frame-ancestors at both layers)

The backend's CSP middleware (`add_security_headers`) only covers API responses. The document a
browser frames is served by Next.js, so the same `Content-Security-Policy: frame-ancestors` policy
is emitted again from `ui/proxy.ts`. Set the allowlist at both layers:

- API: `REVIEW_FRAME_ANCESTORS='self' https://host-app.example.com`
- UI: `NEXT_PUBLIC_FRAME_ANCESTORS='self' https://host-app.example.com`

Never `*`. When the value is `'self'`, both layers also emit `X-Frame-Options: SAMEORIGIN`.

Both variables resolve in **three** states, because unset is not one of their valid values:

| State | Result |
| --- | --- |
| unset | the shipped default `'self'` |
| set, naming no origin (`""` or whitespace) | the layer REFUSES to start |
| set to one or more origins | exactly those origins |

The middle state would emit `Content-Security-Policy: ...; frame-ancestors ` with an empty
directive. Browsers discard an empty directive as a parse error, and the `'self'` branch that
adds `X-Frame-Options` is skipped too, so the clickjacking restriction would disappear from both
channels at once with nothing in the response to show it. A config template that renders either
variable empty now fails at boot instead, and `infra/terraform` refuses the same value at plan
time. To forbid all framing, say so explicitly with `'none'`.

The API half of this was inert until now: Terraform set `REVIEW_FRAME_ANCESTORS` on the Cloud Run
service and this page said the API honoured it, but the middleware was registered with no value,
so API responses always said `frame-ancestors 'self'` whatever the deployment configured. The API
reads the variable now.

## Config knobs

| Env | Layer | Purpose |
|---|---|---|
| `REVIEW_PROFILE` | API | `local` / `gcp` / `platform` / `onprem` |
| `REVIEW_CORS_ORIGINS` | API | explicit CORS allowlist (never `*`; empty outside local) |
| `REVIEW_FRAME_ANCESTORS` | API | CSP frame-ancestors for API responses |
| `REVIEW_IAP_AUDIENCE` | API | IAP audience to verify (gcp) |
| `REVIEW_IAP_ENTITLEMENTS_JSON` | API | reviewed Hrz3 subject map to tenant, hosted domain, and principals |
| `NEXT_PUBLIC_REVIEW_API_URL` | UI | the API base URL the browser calls |
| `NEXT_PUBLIC_BASE_PATH` | UI | mount sub-path for same-origin embedding |
| `NEXT_PUBLIC_EMBED` | UI | `1` to drop page chrome (host owns it) |
| `NEXT_PUBLIC_FRAME_ANCESTORS` | UI | CSP frame-ancestors for the framed document |

## Client integration checklist

- Serve the API and UI same-origin (reverse proxy), or accept the CORS + CSP cost of cross-origin
  and set both allowlists explicitly.
- Front both with the host IdP; do not expose the persona picker outside `local`.
- Confirm the host passes the verified identity through (IAP assertion or an equivalent verified
  header the `IdentityPort` adapter reads); the UI sends no identity in request bodies.
- Export and approve the exact Hrz3 subject mappings. Never derive `group:approver` from an email
  domain or browser-supplied value.
