# Review console UI (Hrz7)

An embeddable Next.js micro-frontend for the Human-Review & Maker-Checker Console: a pending-review
queue and a per-item approve / reject / amend panel with a reason box, plus a local persona picker.

```bash
npm ci
cp .env.local.example .env.local     # point NEXT_PUBLIC_REVIEW_API_URL at the API (default :8087)
npm run dev                          # http://localhost:3000
```

The API must be running (`make run-api` in the repo root). Under the `local` profile the persona
picker switches the acting reviewer via the `X-Dev-Persona` header, so four-eyes and the tenant
partition are visible in the browser: the `other-tenant` persona sees an empty queue, and the maker
of an item is refused when they try to approve it.

Identity is never sent in a request body. In secure profiles the host IdP / Cloud IAP supplies the
verified identity and the picker is hidden. See
[`../docs/embedding-and-identity.md`](../docs/embedding-and-identity.md) for the embed modes and the
CSP `frame-ancestors` configuration (emitted at both the API and this document layer).

## Source map

| Path | Role |
| --- | --- |
| `lib/security-headers.mjs` | The ONE place the document security policy is built. Nothing else composes a CSP. |
| `proxy.ts` | Mints a per-request nonce and sets the CSP on both the request and the response. |
| `next.config.mjs` | Static headers only, plus the build refusal for an un-hydratable nonce policy. |
| `app/layout.tsx` | `export const dynamic = "force-dynamic"`, required by the nonce, not a perf choice. |
| `scripts/security-headers.test.mjs` | What a string can decide about the policy. |
| `scripts/assert-hydratable.mjs` | What only the served bytes can decide: every script tag carries the nonce. |
| `lib/api.ts` | Thin backend client; the dev persona travels in a header, never a body. |

## Gate

```bash
make ui-install    # npm ci --prefix ui
make ui-check      # tsc, unit tests, next build, then the hydration proof against that build
```

`assert-hydratable` runs LAST and against the artefact the build just produced. It starts that
server, fetches the served document and fails unless every `<script>` tag carries the nonce from
the response CSP. A header assertion cannot replace it: the header is byte-identical whether the
console hydrates or ships as dead markup.

The repository-level presenter demo uses the pinned Playwright dependency in this package:

```bash
npx playwright install chromium
cd ..
make demo
make demo-selftest
```
