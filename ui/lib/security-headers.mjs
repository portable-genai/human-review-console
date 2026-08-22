// The document-level security policy for the console UI (C6a), built ONCE and read by every layer.
//
// The API middleware only covers API responses; the document a browser actually loads, frames and
// hydrates is served by Next.js, so the full policy is built here. It is one plain module with no
// framework and no I/O so it can be imported by `proxy.ts` (which sets the response headers),
// by `next.config.mjs` (which refuses to build a policy the page cannot hydrate under) and by
// `scripts/security-headers.test.mjs`. A policy expressed twice is a policy that disagrees with
// itself the first time one copy is edited, and a CSP expressed twice is worse than that: the
// browser intersects the two and the stricter directive wins, silently.
//
// Why this matters and is not cosmetic. Emitting the whole CSP through the
// STATIC `headers()` table in `next.config.mjs`, with `script-src 'self' 'unsafe-inline'` and a
// comment calling the inline allowance an honest limit of Next.js. It was a real hole: any
// injected inline script executed, so the one directive that matters against XSS was switched
// off on every response. The static table cannot express the fix, because the fix is a
// PER-REQUEST value: a nonce. So the CSP moved out of `headers()` into `proxy.ts`, which mints a
// nonce per request, and `script-src` now names that nonce plus `'strict-dynamic'` and nothing
// else. `next.config.mjs` keeps only the headers a static table CAN express.
//
// Two things must BOTH hold or this fails silently, in opposite directions:
//
//   1. `proxy.ts` must put the CSP on the REQUEST headers too, under exactly the name
//      `Content-Security-Policy`. That is where Next reads the nonce it stamps onto every script
//      tag it emits. Response-only blocks the very scripts the nonce was added to allow.
//   2. The document route must be DYNAMICALLY rendered. A statically prerendered page was built
//      before the nonce existed, so nothing carries it, and `'strict-dynamic'` switches off the
//      `'self'` fallback that had at least been loading the chunk scripts. Adding a nonce to a
//      static page therefore blocks strictly MORE than the un-nonced policy did. `app/layout.tsx`
//      sets `export const dynamic = "force-dynamic"` for that reason, `assertHydratableCsp`
//      refuses the half-configured combination at build time, and
//      `scripts/assert-hydratable.mjs` proves the served bytes by executing the built server.
//
// `style-src` still carries `'unsafe-inline'`: the Next runtime injects critical CSS with no
// nonce path, and there is no way to remove it without shipping a broken page. `script-src` no
// longer does, and that is the directive an attacker needs.

/** The origin the browser is allowed to call: the configured API base, plus same-origin. */
export function apiOrigin(apiBaseUrl) {
  if (!apiBaseUrl) return "";
  try {
    return new URL(apiBaseUrl).origin;
  } catch {
    return "";
  }
}

/**
 * Resolve the frame-ancestors allowlist in THREE states, never two.
 *
 * Mirrors `src/review_console/api/app.py::_frame_ancestors` deliberately: the two halves of the
 * embedding posture have to agree or a deployment is framed by one layer and refused by the other.
 *
 * `undefined` means nobody configured it, so the shipped `'self'` stands. A value that names
 * no origin is an expressed intent that names nothing: emitting it would produce
 * `Content-Security-Policy: ...; frame-ancestors ` with an empty directive, which browsers
 * discard as a parse error, and would also skip the `'self'` branch below that adds
 * `X-Frame-Options`, so the clickjacking control would disappear from both channels at once.
 * That refuses instead. A total lockdown stays expressible as `'none'`.
 *
 * @param {string|undefined} raw
 * @returns {string}
 */
/**
 * Values that must never be accepted as a framing ancestor.
 *
 * Four spellings, not one: `'*'` is the quoted form CSP also honours, `*.*` is the subdomain
 * wildcard, and `null` is the origin a SANDBOXED iframe presents, so allowing it hands the frame
 * to any page that can sandbox one. `src/review_console/api/app.py` refuses the same set on the
 * API surface.
 *
 * The set alone was never the whole rule, because it can only match an entry EXACTLY. A
 * host-source form such as `https://*.evil.example` is in no set and was emitted verbatim, and
 * CSP honours it as every subdomain, including one obtained by subdomain takeover or serving
 * user content. `isWildcard` is therefore the union of the two halves, matching the API surface.
 */
const FRAME_ANCESTOR_WILDCARDS = new Set(["*", "'*'", "null", "*.*"]);

/**
 * An entry is a wildcard when it carries an asterisk ANYWHERE, or when it is one of the exact
 * tokens above. A legitimate origin holds no asterisk, so the first half refuses nothing a
 * deployment could correctly hold; the second half exists for the tokens that carry none.
 * Matching for those is exact, so `https://nullify.example` stays a perfectly good origin.
 *
 * @param {string} part
 * @returns {boolean}
 */
function isWildcard(part) {
  return FRAME_ANCESTOR_WILDCARDS.has(part) || part.includes("*");
}

export function resolveFrameAncestors(raw) {
  if (raw === undefined || raw === null) return "'self'";
  const value = String(raw).trim().split(/\s+/).filter(Boolean).join(" ");
  if (!value) {
    throw new Error(
      "frame-ancestors is set to an empty value: it names no parent origin, and an empty CSP " +
        "frame-ancestors directive is a parse error that browsers discard, taking the " +
        "clickjacking restriction with it. Leave it unset to keep the 'self' default, or set " +
        "it to 'none' to refuse all framing.",
    );
  }
  for (const part of value.split(" ")) {
    if (isWildcard(part)) {
      throw new Error(
        `frame-ancestors contains ${JSON.stringify(part)}: the origin policy must never ` +
          "contain a wildcard. That is the clickjacking control switched off, since any page " +
          "on the internet may then frame this console. Name the exact parent origins instead, " +
          "or leave it unset.",
      );
    }
  }
  return value;
}

/**
 * The pre-CSP `X-Frame-Options` spelling of a frame-ancestors value, or "" when it has none.
 *
 * Only `'self'` and `'none'` are expressible. A NAMED parent origin gets no header at all rather
 * than a `SAMEORIGIN` that contradicts the CSP in an agent old enough to ignore frame-ancestors.
 *
 * @param {string} ancestors
 * @returns {string}
 */
export function frameOptions(ancestors) {
  if (ancestors === "'self'") return "SAMEORIGIN";
  if (ancestors === "'none'") return "DENY";
  return "";
}

/** A fresh per-request nonce. Base64 of 16 random bytes from the Web Crypto global. */
export function generateNonce() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

/**
 * Build the full document Content-Security-Policy.
 *
 * With a nonce, `script-src` is `'self' 'nonce-...' 'strict-dynamic'`: the nonced Next bootstrap
 * may load its own chunks and nothing else may run. Without one it falls back to a bare
 * `'self'`, which is right for any response that carries no Next-rendered document and wrong for
 * one that does, which is why the proxy always passes a nonce.
 *
 * The `dev` branch is the ONLY place `'unsafe-eval'` and a websocket appear. Turbopack's HMR
 * client evals its module updates and talks to the dev server over `ws:`; neither exists in a
 * `next build` artefact, and `scripts/assert-hydratable.mjs` runs against that artefact, so a
 * relaxation leaking into a deployment is caught by execution rather than by review.
 *
 * @param {object} options
 * @param {string} [options.frameAncestors] CSP frame-ancestors value (never "*", never empty).
 * @param {string} [options.apiBaseUrl]     Backend base URL; only its origin reaches connect-src.
 * @param {boolean} [options.dev]           Development server (HMR needs eval and a websocket).
 * @param {string} [options.nonce]          Per-request nonce from {@link generateNonce}.
 * @returns {string}
 */
export function contentSecurityPolicy({
  frameAncestors = "'self'",
  apiBaseUrl = "",
  dev = false,
  nonce = "",
} = {}) {
  // A default parameter only covers `undefined`, so an explicitly empty value would otherwise
  // reach the policy below and blank out the directive.
  const ancestors = resolveFrameAncestors(frameAncestors);
  const origin = apiOrigin(apiBaseUrl);
  const connect = ["'self'", origin, dev ? "ws:" : ""].filter(Boolean);
  const script = nonce
    ? ["'self'", `'nonce-${nonce}'`, "'strict-dynamic'", dev ? "'unsafe-eval'" : ""]
    : ["'self'", dev ? "'unsafe-eval'" : ""];

  return [
    "default-src 'self'",
    `script-src ${script.filter(Boolean).join(" ")}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src ${connect.join(" ")}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    `frame-ancestors ${ancestors}`,
  ].join("; ");
}

/**
 * The response headers the proxy sets per request: the nonce CSP and its clickjacking backstop.
 *
 * @param {object} options same shape as {@link contentSecurityPolicy}
 * @returns {Record<string, string>}
 */
export function documentSecurityHeaders(options = {}) {
  const headers = { "Content-Security-Policy": contentSecurityPolicy(options) };
  const legacy = frameOptions(resolveFrameAncestors(options.frameAncestors ?? "'self'"));
  if (legacy) headers["X-Frame-Options"] = legacy;
  return headers;
}

/**
 * The headers a STATIC `headers()` table can honestly express, and only those.
 *
 * No CSP and no `X-Frame-Options` live here. Both are per-request now, and emitting either from
 * both layers would give the browser two policies to intersect, with the stricter directive
 * winning, which is exactly the defect this module was restructured to remove.
 *
 * @param {object} options
 * @param {boolean} [options.secure] Emit HSTS (TLS terminates in front of the console).
 */
export function staticSecurityHeaders({ secure = false } = {}) {
  const headers = [
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "no-referrer" },
  ];
  if (secure) {
    headers.push({
      key: "Strict-Transport-Security",
      value: "max-age=31536000; includeSubDomains",
    });
  }
  return headers;
}

/** Raised when the nonce policy and the rendering mode disagree, which serves un-hydratable HTML. */
export class UnhydratableCspError extends Error {}

/**
 * Refuse a build whose CSP mints a nonce the rendered HTML can never carry.
 *
 * Next can only stamp a per-request nonce onto the scripts of a DYNAMICALLY rendered route. The
 * failure is invisible to every check that does not execute the page: the header is byte-identical
 * in the working case and the broken one. `next.config.mjs` reads `app/layout.tsx` and passes it
 * here, so the refusal happens at `next build` and `next start`. No I/O happens in this module: it
 * takes the source as a string, which keeps it importable from the edge-runtime proxy.
 *
 * @param {string} layoutSource contents of `app/layout.tsx`
 * @throws {UnhydratableCspError}
 */
export function assertHydratableCsp(layoutSource) {
  if (!/export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/.test(layoutSource)) {
    throw new UnhydratableCspError(
      'app/layout.tsx must set `export const dynamic = "force-dynamic"`. The CSP mints a ' +
        "per-request nonce, and Next can only stamp it onto script tags for a dynamically " +
        "rendered route. Statically prerendered HTML was built before the nonce existed, so " +
        "every script is blocked and the page never hydrates.",
    );
  }
}
