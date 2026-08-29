import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Human-Review Console",
  description: "Maker-checker review queue and sign-off.",
};

// Required by the nonce CSP, not a performance preference. `proxy.ts` mints a per-request script
// nonce and Next can only stamp it onto the script tags of a DYNAMICALLY rendered route. A
// statically prerendered page is built before the nonce exists, so its scripts carry none, and
// `'strict-dynamic'` switches off the `'self'` fallback that would otherwise have loaded them:
// the page would hydrate LESS than it did before the nonce was introduced. `next.config.mjs`
// refuses to build without this line, and `scripts/assert-hydratable.mjs` proves the served bytes.
export const dynamic = "force-dynamic";

// When embedded (NEXT_PUBLIC_EMBED=1) the host owns the page chrome, so render children bare.
const embed = process.env.NEXT_PUBLIC_EMBED === "1";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={embed ? undefined : "min-h-screen"}>{children}</body>
    </html>
  );
}
