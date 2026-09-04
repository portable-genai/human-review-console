"use client";

import { useCallback, useEffect, useState } from "react";
import { api, setDevPersona } from "../lib/api";
import type { DecisionResponse, Disposition, Persona, ReviewItem } from "../lib/types";

const IS_EMBEDDED = process.env.NEXT_PUBLIC_EMBED === "1";

const SEVERITY_COLOR: Record<string, string> = {
  low: "#3b7d3b",
  medium: "#9a7d18",
  high: "#b4531a",
  critical: "#a01f1f",
};

export default function Page() {
  const [profile, setProfile] = useState<string>("");
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [persona, setPersona] = useState<string>("");
  const [queue, setQueue] = useState<ReviewItem[]>([]);
  const [selected, setSelected] = useState<ReviewItem | null>(null);
  const [reason, setReason] = useState<string>("");
  const [note, setNote] = useState<string>("");

  const refreshQueue = useCallback(async () => {
    try {
      setQueue(await api.queue());
    } catch (err) {
      setNote(`queue error: ${(err as Error).message}`);
    }
  }, []);

  useEffect(() => {
    (async () => {
      const health = await api.health();
      setProfile(health.profile);
      if (health.profile === "local") {
        const list = await api.listPersonas();
        setPersonas(list);
        if (list.length > 0) {
          setPersona(list[0].id);
          setDevPersona(list[0].id);
        }
      }
      await refreshQueue();
    })().catch((err) => setNote(`load error: ${(err as Error).message}`));
  }, [refreshQueue]);

  function onPersonaChange(id: string) {
    setPersona(id);
    setDevPersona(id);
    setSelected(null);
    setNote(`acting as ${id}`);
    refreshQueue();
  }

  async function seedDemoItem() {
    try {
      await api.submit({
        action: "disburse_facility",
        subject: "Acme Holdings Pte Ltd (FICTIONAL)",
        summary: "Disburse SGD 2.5m revolving facility.",
        severity: "high",
        sod_group: "group:origination",
        citations: [
          {
            source_id: "facility-demo-001",
            title: "Approved facility record (FICTIONAL)",
            snippet: "Independent approval is required.",
          },
        ],
      });
      setNote("submitted a demo item for review");
      await refreshQueue();
    } catch (err) {
      setNote(`submit error: ${(err as Error).message}`);
    }
  }

  async function decide(disposition: Disposition) {
    if (!selected) return;
    try {
      const res: DecisionResponse = await api.decide(selected.review_id, disposition, reason);
      if (res.decision === "allowed") {
        const sourceEvidence = selected.source_key ? ` · source ${selected.source_key}` : "";
        setNote(`${disposition} recorded -> ${res.item.state}${sourceEvidence}`);
      } else {
        setNote(`refused: ${res.findings.join(", ")}`);
      }
      setReason("");
      setSelected(null);
      await refreshQueue();
    } catch (err) {
      setNote(`decision error: ${(err as Error).message}`);
    }
  }

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "1.5rem" }}>
      <header style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", justifyContent: "space-between", alignItems: "baseline" }}>
        <h1 style={{ fontSize: "1.4rem", fontWeight: 700 }}>Human-Review Console</h1>
        <span style={{ fontSize: "0.8rem", color: "#666" }}>profile: {profile || "..."}</span>
      </header>
      <p style={{ color: "#555", fontSize: "0.9rem", marginTop: "0.25rem" }}>
        Maker-checker review queue. A maker can never approve their own item, and consequential
        actions need two distinct approvals.
      </p>

      {!IS_EMBEDDED && personas.length > 0 && (
        <section
          style={{
            marginTop: "1rem",
            padding: "0.75rem",
            background: "#fff",
            border: "1px solid #e3e6ea",
            borderRadius: 8,
          }}
        >
          <label style={{ fontSize: "0.85rem", fontWeight: 600 }}>
            Acting reviewer:{" "}
            <select
              value={persona}
              onChange={(e) => onPersonaChange(e.target.value)}
              style={{ marginLeft: "0.5rem", padding: "0.2rem" }}
            >
              {personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.subject} ({p.tenant || "no-tenant"})
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={seedDemoItem}
            style={{
              marginLeft: "1rem",
              padding: "0.25rem 0.6rem",
              fontSize: "0.8rem",
              border: "1px solid #c3c8ce",
              borderRadius: 6,
              background: "#f0f2f5",
            }}
          >
            + submit demo item
          </button>
        </section>
      )}

      {note && (
        <p
          data-testid="operation-result"
          style={{ marginTop: "0.75rem", fontSize: "0.85rem", color: "#334" }}
        >
          {note}
        </p>
      )}

      <section data-testid="review-queue" style={{ marginTop: "1rem" }}>
        <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "0.5rem" }}>
          Pending queue ({queue.length})
        </h2>
        <div style={{ display: "grid", gap: "0.5rem" }}>
          {queue.map((item) => (
            <button
              key={item.review_id}
              data-testid="review-item"
              onClick={() => {
                setSelected(item);
                setNote("");
              }}
              style={{
                textAlign: "left",
                padding: "0.6rem 0.75rem",
                background: selected?.review_id === item.review_id ? "#eef3fb" : "#fff",
                border: "1px solid #e3e6ea",
                borderRadius: 8,
                cursor: "pointer",
              }}
            >
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem 0.5rem", justifyContent: "space-between" }}>
                <strong>{item.action}</strong>
                <span
                  style={{
                    color: SEVERITY_COLOR[item.severity] || "#555",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                  }}
                >
                  {item.severity} · {item.approvals_count}/{item.required_approvals}
                </span>
              </div>
              <div style={{ fontSize: "0.85rem", color: "#555" }}>{item.subject}</div>
              <div style={{ fontSize: "0.75rem", color: "#888" }}>maker: {item.maker}</div>
            </button>
          ))}
          {queue.length === 0 && (
            <p style={{ fontSize: "0.85rem", color: "#888" }}>
              Nothing pending for this tenant.
            </p>
          )}
        </div>
      </section>

      {selected && (
        <section
          data-testid="review-evidence"
          style={{
            marginTop: "1rem",
            padding: "1rem",
            background: "#fff",
            border: "1px solid #d7dbe0",
            borderRadius: 8,
          }}
        >
          <h2 style={{ fontSize: "1rem", fontWeight: 600 }}>Review {selected.action}</h2>
          <p style={{ fontSize: "0.85rem", color: "#555" }}>{selected.summary || selected.subject}</p>
          <p style={{ fontSize: "0.75rem", color: "#888" }}>
            maker {selected.maker} · needs {selected.required_approvals} distinct approval(s)
          </p>
          {selected.source_key && (
            <p
              data-testid="review-source-key"
              style={{ fontSize: "0.75rem", color: "#555", overflowWrap: "anywhere" }}
            >
              source: {selected.source_key.startsWith("cdd-sow-research:") ? "cdd-sow-research" : "upstream service"} ·
              key: {selected.source_key}
            </p>
          )}
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "max-content 1fr",
              gap: "0.25rem 0.75rem",
              marginTop: "0.75rem",
              fontSize: "0.78rem",
            }}
          >
            <dt style={{ color: "#666" }}>Decision state</dt>
            <dd data-testid="decision-state">{selected.state}</dd>
            <dt style={{ color: "#666" }}>Evidence</dt>
            <dd>
              {selected.citations.length > 0
                ? selected.citations.map((citation) => citation.source_id).join(", ")
                : "No producer citations supplied"}
            </dd>
            <dt style={{ color: "#666" }}>Completed checks</dt>
            <dd>
              {selected.approvals.length > 0
                ? selected.approvals.map((approval) => approval.checker).join(", ")
                : "None yet"}
            </dd>
            <dt style={{ color: "#666" }}>Next action</dt>
            <dd>
              Collect {Math.max(0, selected.required_approvals - selected.approvals_count)} more
              independent approval(s), or record a reasoned rejection or amendment.
            </dd>
          </dl>
          <textarea
            aria-label="Reason for your decision"
            placeholder="Reason for your decision"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{
              width: "100%",
              marginTop: "0.5rem",
              padding: "0.5rem",
              border: "1px solid #ccd1d7",
              borderRadius: 6,
              minHeight: 60,
            }}
          />
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginTop: "0.5rem" }}>
            <button
              onClick={() => decide("approve")}
              style={{ padding: "0.35rem 0.9rem", background: "#1f7a34", color: "#fff", border: 0, borderRadius: 6 }}
            >
              Approve
            </button>
            <button
              onClick={() => decide("reject")}
              style={{ padding: "0.35rem 0.9rem", background: "#a01f1f", color: "#fff", border: 0, borderRadius: 6 }}
            >
              Reject
            </button>
            <button
              onClick={() => decide("amend")}
              style={{ padding: "0.35rem 0.9rem", background: "#9a7d18", color: "#fff", border: 0, borderRadius: 6 }}
            >
              Amend
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
