import { useState } from "react";
import { searchCards } from "./api/client";

// A lightweight "search any card on eBay right now" box for the Alerts tab —
// on-demand, separate from your saved alerts. Collapsed by default.
export default function QuickSearch() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    if (!q.trim() || loading) return;
    setLoading(true);
    setSearched(true);
    try {
      const data = await searchCards(q.trim());
      setResults(data?.listings || []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ margin: "8px 0 18px" }}>
      <button
        className="alert-method-badge"
        onClick={() => setOpen(o => !o)}
        style={{ cursor: "pointer", background: "rgba(37,99,235,0.12)", border: "1px solid rgba(37,99,235,0.35)", color: "#2563eb", fontWeight: 600 }}
      >
        🔍 {open ? "Hide quick search" : "Quick search eBay"}
      </button>

      {open && (
        <div style={{ marginTop: 10, padding: 14, border: "1px solid #e2e8f0", borderRadius: 12, background: "#fff" }}>
          <form onSubmit={run} style={{ display: "flex", gap: 8 }}>
            <input
              value={q}
              onChange={e => setQ(e.target.value)}
              placeholder="Search any card on eBay (e.g. 2025 Topps Chrome Cooper Flagg)"
              autoFocus
              style={{ flex: 1, padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }}
            />
            <button type="submit" disabled={loading}
              style={{ background: loading ? "#94a3b8" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "0 18px", fontWeight: 600, cursor: loading ? "default" : "pointer" }}>
              {loading ? "…" : "Search"}
            </button>
          </form>
          <p style={{ fontSize: 12, color: "#94a3b8", margin: "6px 2px 0" }}>
            On-demand eBay search — this doesn't create an alert.
          </p>

          {searched && !loading && results.length === 0 && (
            <p className="subtitle" style={{ marginTop: 12 }}>No current listings found.</p>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
            {results.map((l, i) => {
              const pct = l?.analysis?.pct_vs_market;
              return (
                <a key={i} href={l.listing_url || "#"} target="_blank" rel="noreferrer"
                   style={{ display: "flex", gap: 12, padding: 10, border: "1px solid #e2e8f0", borderRadius: 10, textDecoration: "none", color: "#0f172a", background: "#fff" }}>
                  {l.image_url
                    ? <img src={l.image_url} alt="" style={{ width: 70, height: 70, objectFit: "cover", borderRadius: 8, flexShrink: 0, border: "1px solid #e2e8f0" }} />
                    : <div style={{ width: 70, height: 70, borderRadius: 8, background: "#f1f5f9", flexShrink: 0 }} />}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.3 }}>{l.title}</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 5, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 16, fontWeight: 700, color: "#16a34a" }}>${(l.price ?? 0).toLocaleString()}</span>
                      {l.is_auction && <span style={{ fontSize: 12, fontWeight: 600, color: "#7c3aed" }}>🔨 Auction</span>}
                      {typeof pct === "number" && (
                        <span style={{ fontSize: 12, color: pct <= -5 ? "#16a34a" : pct <= 15 ? "#64748b" : "#dc2626" }}>
                          {pct <= -5 ? `${Math.abs(Math.round(pct))}% below market` : pct <= 15 ? "around market" : `${Math.round(pct)}% above market`}
                        </span>
                      )}
                    </div>
                  </div>
                </a>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
