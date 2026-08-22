// Thin client for the FastAPI backend. Identity is never sent in a request body: under the local
// profile the dev persona travels in the X-Dev-Persona header; in secure profiles the host IdP /
// IAP supplies the verified identity and this header is ignored.

import { resolveApiBaseUrl } from "./api-base.mjs";
import type {
  DecisionResponse,
  Disposition,
  Health,
  Persona,
  ReviewItem,
} from "./types";

// The same resolver `proxy.ts` uses for `connect-src`, so the origin this module calls and the
// origin the policy permits cannot drift apart, and an emptied variable refuses in both.
const BASE_URL = resolveApiBaseUrl(process.env.NEXT_PUBLIC_REVIEW_API_URL);

let devPersona = "";

export function setDevPersona(id: string): void {
  devPersona = id;
}

export function getDevPersona(): string {
  return devPersona;
}

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (devPersona) {
    h["X-Dev-Persona"] = devPersona;
  }
  return h;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { ...headers(), ...(init?.headers || {}) },
  });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      detail = body.detail ? String(body.detail) : JSON.stringify(body);
    } catch {
      // non-JSON error body; keep the status
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  health: () => request<Health>("/healthz"),
  listPersonas: () => request<Persona[]>("/v1/personas"),
  queue: () => request<ReviewItem[]>("/v1/reviews"),
  getReview: (id: string) => request<ReviewItem>(`/v1/reviews/${id}`),
  submit: (body: {
    action: string;
    subject: string;
    summary?: string;
    severity?: string;
    required_approvals?: number;
    sod_group?: string;
    citations?: { source_id: string; title: string; snippet?: string }[];
  }) =>
    request<ReviewItem>("/v1/reviews", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  // A 403 (four-eyes / SoD / tenant denial) still returns a DecisionResponse body with findings,
  // so decode it rather than throwing: the UI shows why the disposition was refused.
  decide: async (
    id: string,
    disposition: Disposition,
    reason: string
  ): Promise<DecisionResponse> => {
    const resp = await fetch(`${BASE_URL}/v1/reviews/${id}/decision`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ disposition, reason }),
    });
    if (resp.status === 200 || resp.status === 403) {
      return (await resp.json()) as DecisionResponse;
    }
    throw new Error(`decision failed: ${resp.status}`);
  },
};
