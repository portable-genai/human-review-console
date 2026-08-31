/** @type {import('next').NextConfig} */
import { readFileSync } from "node:fs";

import { settingOrDefault } from "./lib/envread.mjs";
import { assertHydratableCsp, staticSecurityHeaders } from "./lib/security-headers.mjs";

// Refuse, at config load (which is both `next build` and `next start`), a console whose CSP mints
// a per-request nonce that the rendered HTML can never carry. Next only stamps the nonce onto the
// scripts of a DYNAMICALLY rendered route; on a statically prerendered one the header advertises a
// nonce nothing carries, and `'strict-dynamic'` disables the `'self'` fallback, so the page blocks
// strictly more than it did before the nonce was added. No cheaper check can see this.
assertHydratableCsp(readFileSync(new URL("./app/layout.tsx", import.meta.url), "utf8"));

// NEXT_PUBLIC_BASE_PATH mounts the UI (and its assets) under a reverse-proxy sub-path (for example
// /review) so it can be embedded same-origin; blank keeps the standalone build unchanged.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";
// HSTS belongs on any deployment where TLS terminates in front of the console, never on the
// loopback demo, so it follows the same profile switch the API middleware uses. The read resolves
// THREE states, like every security-relevant read in the service tier: unset takes the reviewed
// `local` default, and a variable an operator deliberately emptied refuses at config load. It used
// to be `process.env.REVIEW_PROFILE || "local"`, which resolved an emptied variable to the demo
// posture and silently dropped Strict-Transport-Security from every response.
const secure = settingOrDefault(process.env.REVIEW_PROFILE, "REVIEW_PROFILE", "local") !== "local";

// The Content-Security-Policy and X-Frame-Options are DELIBERATELY absent from this table. They
// are emitted per request by `proxy.ts`, because the CSP carries a nonce and a static table cannot
// produce one. Emitting a CSP from both layers would give the browser two policies to intersect,
// with the stricter directive winning per directive, which is the defect this split removes.
const nextConfig = {
  reactStrictMode: true,
  // `next dev` writes AGENTS.md and CLAUDE.md into this directory unless this is false; the
  // writer is node_modules/next/dist/server/lib/generate-agent-files.js. This repo's working
  // agreement is the AGENTS.md at its root and there is no tool-specific alias of it, so a
  // second one here is a second agreement to keep in step and CLAUDE.md is precisely the alias
  // the convention forbids. The generated prose also carries an em-dash, which the catalog's
  // house style forbids in shipped markdown. tests/unit/test_ui_agent_documents.py fails the
  // gate if this line goes away or if either file turns up on disk anyway.
  agentRules: false,
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  async headers() {
    return [
      {
        source: "/:path*",
        headers: staticSecurityHeaders({ secure }),
      },
    ];
  },
};

export default nextConfig;
