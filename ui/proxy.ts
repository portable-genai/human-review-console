// The per-request document security headers (Next 16 names this file `proxy.ts`).
//
// The Content-Security-Policy is set HERE rather than in `next.config.mjs` because it carries a
// per-request script nonce, and the static `headers()` table has no way to produce one. Nothing
// here authenticates: identity belongs to the identity-aware proxy in front of this console and to
// the FastAPI service behind it, which discards any client-asserted actor.
//
// The nonce has to reach two places or hydration fails in one of two ways. On the REQUEST headers,
// under exactly the name `Content-Security-Policy`, is where Next looks for the nonce it stamps
// onto every script tag it emits; any other header name is silently ignored. On the RESPONSE is
// what the browser enforces. A nonce on only the response blocks the very scripts it was added to
// allow; a nonce on only the request proves nothing.

import { type NextRequest, NextResponse } from "next/server";

import { resolveApiBaseUrl } from "./lib/api-base.mjs";
import { documentSecurityHeaders, generateNonce } from "./lib/security-headers.mjs";

export function proxy(request: NextRequest) {
  const headers = documentSecurityHeaders({
    frameAncestors: process.env.NEXT_PUBLIC_FRAME_ANCESTORS,
    // The same resolver `lib/api.ts` calls, so `connect-src` names the origin the client
    // actually calls. Two copies of one default is how a console blocks its own backend.
    apiBaseUrl: resolveApiBaseUrl(process.env.NEXT_PUBLIC_REVIEW_API_URL),
    dev: process.env.NODE_ENV !== "production",
    nonce: generateNonce(),
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", headers["Content-Security-Policy"]);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  for (const [name, value] of Object.entries(headers)) {
    response.headers.set(name, value);
  }
  return response;
}

// Every path, the same matcher the rest of the fleet's consoles use. A narrower one was tried and
// reverted: the dev server's 403 on `/_next/static/chunks/*.js` and its failed HMR websocket
// handshake reproduce with `proxy.ts` deleted entirely, so they are a property of this machine's
// `next dev`, not of the proxy, and narrowing the matcher to work around them would have diverged
// this console from the standard for no gain.
export const config = {
  matcher: "/:path*",
};
