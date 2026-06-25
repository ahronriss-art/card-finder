import { useEffect, useState } from "react";
import { getTrendingCards, type TrendingCard } from "./api/client";

// Most-watched trading cards on eBay right now — a proxy for what's hottest today.
export default function TrendingPage() {
  const [cards, setCards] = useState<TrendingCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true); setError("");
    try {
      const r = await getTrendingCards();
      setCards(r.cards || []);
    } catch {
      setError("Couldn't load trending cards right now. Try again in a moment.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  return (
    <div style={{ maxWidth: 820, margin: "24px auto", padding: "0 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ fontSize: 24, marginBottom: 4 }}>Trending</h1>
          <p style={{ color: "#94a3b8", marginTop: 0, fontSize: 14 }}>
            The most-watched cards on eBay right now — the closest read on what's hottest today.
          </p>
        </div>
        <button onClick={load} disabled={loading}
          style={{ background: loading ? "#475569" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "8px 16px", fontWeight: 600, fontSize: 13, cursor: loading ? "default" : "pointer" }}>
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      {error && <div style={{ color: "#f87171", marginTop: 12 }}>{error}</div>}
      {loading && cards.length === 0 && <div style={{ color: "#94a3b8", marginTop: 16 }}>Loading the hottest cards…</div>}

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 16 }}>
        {cards.map((c, i) => (
          <a key={i} href={c.url || "#"} target="_blank" rel="noreferrer"
            style={{ display: "flex", gap: 14, alignItems: "center", padding: 12, borderRadius: 12, textDecoration: "none",
              background: "#fff", border: "1px solid #e2e8f0", color: "#0f172a" }}>
            <div style={{ fontSize: 20, fontWeight: 900, color: "#94a3b8", width: 30, textAlign: "center", flexShrink: 0 }}>{i + 1}</div>
            {c.image_url
              ? <img src={c.image_url} alt="" style={{ width: 64, height: 64, objectFit: "cover", borderRadius: 8, border: "1px solid #e2e8f0", flexShrink: 0 }} />
              : <div style={{ width: 64, height: 64, borderRadius: 8, background: "#f1f5f9", flexShrink: 0 }} />}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.35 }}>{c.title}</div>
              <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 5, flexWrap: "wrap" }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: "#dc2626", background: "rgba(220,38,38,0.1)", padding: "2px 8px", borderRadius: 6 }}>
                  👀 {c.watch_count.toLocaleString()} watching
                </span>
                {c.price != null && <span style={{ fontSize: 15, fontWeight: 800, color: "#16a34a" }}>${c.price.toLocaleString()}</span>}
              </div>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
