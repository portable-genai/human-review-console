// One home for the backend base URL, because this console used to encode it twice.
//
// `lib/api.ts` resolved `NEXT_PUBLIC_REVIEW_API_URL` with its own loopback fallback for the calls
// the browser makes, and `proxy.ts` resolved the SAME variable with its own copy of that fallback
// for the `connect-src` the browser is allowed to make them to. Two defaults for one setting
// eventually disagree, and when they do the console hydrates perfectly and then blocks its own
// backend, with the only symptom in the browser console.
//
// There is a second edge that makes the duplication worse here than it looks. `NEXT_PUBLIC_*` is
// INLINED AT BUILD TIME in the client module and read AT RUNTIME in the proxy, so setting the
// variable at start-up fixes the header and not the bundle. One exported resolver cannot make
// those two moments the same, but it does guarantee they agree on the value and on what an
// emptied variable means.

import { settingOrDefault } from "./envread.mjs";

/** The documented default: the loopback API a laptop demo serves. */
export const DEFAULT_REVIEW_API_URL = "http://localhost:8087";

/**
 * The backend base URL, with no trailing slash.
 *
 * Three states, not two. Unset takes the loopback default, which is the right answer for a
 * laptop demo and harmless in a deployment that sets the variable. A variable an operator
 * EMPTIED refuses: it names no backend, and inheriting the loopback default there would widen
 * `connect-src` to localhost on a real deployment while the console reported healthy.
 *
 * @param {string | undefined} raw The caller passes `process.env.NEXT_PUBLIC_REVIEW_API_URL`
 *   directly, because Next only inlines literal member reads.
 * @returns {string}
 */
export function resolveApiBaseUrl(raw) {
  const value = settingOrDefault(raw, "NEXT_PUBLIC_REVIEW_API_URL", DEFAULT_REVIEW_API_URL);
  return value.replace(/\/$/, "");
}
