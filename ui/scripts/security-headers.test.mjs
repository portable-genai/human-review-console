// Unit contract for the UI security-header policy (C6a). Run: node --test this file.
//
// These are NOT sufficient, and the reason is the whole point of the C6a standard. Every
// assertion here is about a STRING, and the string is byte-identical in the case where the
// console hydrates and the case where it serves dead markup: a nonce in the header proves
// nothing unless the rendered script tags carry the same nonce, which only the served bytes
// know. `scripts/assert-hydratable.mjs` starts the BUILT server and checks those bytes, and it
// is the check that can actually fail on the defect. What follows covers only what a string can
// decide: that the directives exist, that none of them is empty, and that the three-state
// frame-ancestors read never collapses into two.
import assert from "node:assert/strict";
import test from "node:test";

import {
  apiOrigin,
  assertHydratableCsp,
  contentSecurityPolicy,
  documentSecurityHeaders,
  frameOptions,
  generateNonce,
  resolveFrameAncestors,
  staticSecurityHeaders,
  UnhydratableCspError,
} from "../lib/security-headers.mjs";

/** Split a policy string into a name -> value map, the way a browser parses it. */
function directives(policy) {
  return new Map(
    policy
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [name, ...value] = part.split(/\s+/);
        return [name.toLowerCase(), value.join(" ")];
      }),
  );
}

test("apiOrigin keeps only the origin and rejects garbage", () => {
  assert.equal(apiOrigin("http://127.0.0.1:18087/v1/reviews"), "http://127.0.0.1:18087");
  assert.equal(apiOrigin("not a url"), "");
  assert.equal(apiOrigin(""), "");
});

test("every directive the console's posture depends on is present", () => {
  const parsed = directives(
    contentSecurityPolicy({ apiBaseUrl: "https://api.example.invalid", nonce: "abc" }),
  );
  for (const name of [
    "default-src",
    "script-src",
    "style-src",
    "img-src",
    "font-src",
    "connect-src",
    "object-src",
    "base-uri",
    "form-action",
    "frame-ancestors",
  ]) {
    assert.ok(parsed.has(name), `the policy has no ${name} directive`);
  }
  assert.equal(parsed.get("object-src"), "'none'");
  assert.equal(parsed.get("base-uri"), "'self'");
  assert.equal(parsed.get("default-src"), "'self'");
});

test("no directive is ever emitted empty, whatever the inputs", () => {
  // An empty directive is a parse error browsers DISCARD, which removes the control it named
  // without removing the header that appears to carry it.
  for (const options of [
    {},
    { nonce: "abc" },
    { apiBaseUrl: "" },
    { apiBaseUrl: "not a url" },
    { dev: true },
    { frameAncestors: "'none'" },
  ]) {
    for (const [name, value] of directives(contentSecurityPolicy(options))) {
      assert.ok(value, `${name} is empty for ${JSON.stringify(options)}`);
    }
  }
});

test("script-src takes the nonce and strict-dynamic only when a nonce is supplied", () => {
  const nonced = directives(contentSecurityPolicy({ nonce: "n0nc3" })).get("script-src");
  assert.equal(nonced, "'self' 'nonce-n0nc3' 'strict-dynamic'");
  assert.equal(directives(contentSecurityPolicy({})).get("script-src"), "'self'");
});

test("script-src never carries unsafe-inline, in any mode", () => {
  // The pre-C6a policy shipped `script-src 'self' 'unsafe-inline'` under a comment calling it an
  // honest limit of Next.js. It was not: it switched off the one directive XSS has to defeat.
  for (const options of [{}, { nonce: "abc" }, { dev: true }, { dev: true, nonce: "abc" }]) {
    const script = directives(contentSecurityPolicy(options)).get("script-src");
    assert.doesNotMatch(script, /unsafe-inline/, `unsafe-inline leaked for ${JSON.stringify(options)}`);
  }
});

test("unsafe-eval and the HMR websocket exist only on the dev server", () => {
  // Proven by execution, not assumed: with `'unsafe-eval'` removed, `next dev` logs "eval() is not
  // supported in this environment ... React requires eval() in development mode" and the page
  // never attaches. A `next build` artefact needs neither, and assert-hydratable runs against
  // that artefact, so a leak into a deployment fails a gate rather than a review.
  const production = contentSecurityPolicy({ nonce: "abc", apiBaseUrl: "https://api.example.invalid" });
  assert.doesNotMatch(production, /unsafe-eval/);
  assert.doesNotMatch(production, /ws:/);
  const development = contentSecurityPolicy({ nonce: "abc", dev: true });
  assert.match(directives(development).get("script-src"), /'unsafe-eval'/);
  assert.match(directives(development).get("connect-src"), /ws:/);
});

test("connect-src widens to the API ORIGIN and never to a wildcard", () => {
  const parsed = directives(contentSecurityPolicy({ apiBaseUrl: "https://api.example.invalid/v1/x" }));
  assert.equal(parsed.get("connect-src"), "'self' https://api.example.invalid");
  assert.equal(directives(contentSecurityPolicy({ apiBaseUrl: "" })).get("connect-src"), "'self'");
  assert.doesNotMatch(contentSecurityPolicy({ apiBaseUrl: "*" }), /\*/);
});

test("frame-ancestors resolves in three states, mirroring the API middleware", () => {
  assert.equal(resolveFrameAncestors(undefined), "'self'");
  assert.equal(resolveFrameAncestors("'self' https://host.example.invalid"), "'self' https://host.example.invalid");
  assert.equal(resolveFrameAncestors("'none'"), "'none'");
  // RED before: an explicitly empty value slipped past the default parameter (which only covers
  // `undefined`) into `frame-ancestors ` with nothing after it. Browsers discard an empty
  // directive as a parse error, and the 'self' branch that adds X-Frame-Options is skipped too,
  // so the clickjacking control vanished from both channels at once.
  assert.throws(() => resolveFrameAncestors(""), /empty value/);
  assert.throws(() => resolveFrameAncestors("   "), /empty value/);
  assert.throws(() => contentSecurityPolicy({ frameAncestors: "" }), /empty value/);
});

test("a wildcard frame-ancestors is refused rather than passed through", () => {
  // The document a browser frames is served by Next.js and never passes through the API
  // middleware, so this surface needs the refusal the API now makes. A wildcard here is the
  // clickjacking control switched off: any page on the internet may frame the review queue.
  //
  // SEVEN spellings, not four. The exact-token set is only half the rule, because a Set can
  // match an entry EXACTLY and nothing else. `https://*.evil.example` is in no set, so it was
  // emitted verbatim, and CSP honours that host-source form as EVERY subdomain, including one
  // an attacker obtained by takeover or one that serves user content. The other three carry
  // their asterisk somewhere the same reasoning covers. The token half remains for `'*'` (the
  // quoted form CSP also honours) and `null` (the origin a SANDBOXED iframe presents, so
  // allowing it hands the frame to any page that can sandbox one), which carry no asterisk at
  // all. `src/review_console/api/app.py` refuses the same union.
  const spellings = ["*", "'*'", "null", "*.*", "https://*.evil.example", "*.example", "https://*"];
  for (const spelling of spellings) {
    assert.throws(() => resolveFrameAncestors(spelling), /wildcard/, `${spelling} must be refused`);
    assert.throws(
      () => resolveFrameAncestors(`'self' https://host.example.invalid ${spelling}`),
      /wildcard/,
      `${spelling} must be refused among named origins`,
    );
    assert.throws(() => contentSecurityPolicy({ frameAncestors: spelling }), /wildcard/);
  }
  // The states this resolver already had must be untouched by the new one.
  assert.equal(resolveFrameAncestors(undefined), "'self'");
  assert.equal(resolveFrameAncestors("'none'"), "'none'");
});

test("the wildcard refusal leaves a legitimate named allowlist alone", () => {
  // A refusal that also turns away valid configuration is an outage, not a control. The two
  // shapes most likely to trip a careless rule are an explicit PORT and a HYPHENATED host
  // label, and `nullify` proves the token match did not quietly become a substring match.
  const named = "'self' https://portal.demo-bank.example:8443 https://a-b-c.demo.example";
  assert.equal(resolveFrameAncestors(named), named);
  assert.equal(resolveFrameAncestors("https://nullify.example"), "https://nullify.example");
  assert.match(contentSecurityPolicy({ frameAncestors: named }), /frame-ancestors 'self' https:/);
});

test("X-Frame-Options is sent only for the two policies it can express", () => {
  assert.equal(frameOptions("'self'"), "SAMEORIGIN");
  assert.equal(frameOptions("'none'"), "DENY");
  assert.equal(frameOptions("'self' https://host.example.invalid"), "");
  const framed = documentSecurityHeaders({ frameAncestors: "'self' https://host.example.invalid" });
  assert.equal(framed["X-Frame-Options"], undefined);
  assert.equal(documentSecurityHeaders({})["X-Frame-Options"], "SAMEORIGIN");
});

test("the static headers table carries no CSP and no X-Frame-Options", () => {
  // Two layers emitting a CSP is the fleet defect: the browser intersects them and the stricter
  // directive wins, per directive, silently.
  const keys = staticSecurityHeaders({ secure: true }).map((h) => h.key);
  assert.ok(!keys.includes("Content-Security-Policy"));
  assert.ok(!keys.includes("X-Frame-Options"));
  assert.deepEqual(keys, ["X-Content-Type-Options", "Referrer-Policy", "Strict-Transport-Security"]);
  assert.deepEqual(staticSecurityHeaders({}).map((h) => h.key), [
    "X-Content-Type-Options",
    "Referrer-Policy",
  ]);
});

test("nonces are unguessable, base64 and never repeated", () => {
  const seen = new Set();
  for (let i = 0; i < 50; i += 1) {
    const nonce = generateNonce();
    assert.match(nonce, /^[A-Za-z0-9+/]{22}==$/);
    seen.add(nonce);
  }
  assert.equal(seen.size, 50);
});

test("a layout without force-dynamic is refused at build time", () => {
  assert.throws(
    () => assertHydratableCsp("export const metadata = {};"),
    UnhydratableCspError,
  );
  assert.doesNotThrow(() => assertHydratableCsp('export const dynamic = "force-dynamic";'));
});
