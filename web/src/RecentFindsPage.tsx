import { useEffect, useMemo, useState } from "react";
import { listMyFinds, type Find } from "./api/client";

function dealBadge(pct: number | null, isAuction: boolean) {
  if (isAuction) return { text: "🔨 Auction", color: "#7c3aed" };
  if (pct == null) return null;
  const p = Math.round(pct);
  if (p <= -5) return { text: `${Math.abs(p)}% below market`, color: "#16a34a" };
  if (p <= 15) return { text: "around market", color: "#0891b2" };
  return { text: `${p}% above market`, color: "#dc2626" };
}

function timeAgo(iso: string | null) {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export default function RecentFindsPage() {
  const [finds, setFinds] = useState<Find[]>([]);
  const [loading, setLoading] = useState(true);
  const [needLogin, setNeedLogin] = useState(false);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"newest" | "priceHigh" | "priceLow">("newest");
  const [sport, setSport] = useState("all");

  const sports = useMemo(
    () => Array.from(new Set(finds.map(f => f.sport || "Other"))).sort(),
    [finds]);

  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    let r = finds.filter(f =>
      (sport === "all" || (f.sport || "Other") === sport) &&
      (!term || [f.title, f.alert, f.price != null ? `$${f.price}` : ""].join(" ").toLowerCase().includes(term)));
    if (sort === "priceHigh") r = [...r].sort((a, b) => (b.price ?? 0) - (a.price ?? 0));
    else if (sort === "priceLow") r = [...r].sort((a, b) => (a.price ?? 0) - (b.price ?? 0));
    // "newest" keeps server order (already sent_at desc)
    return r;
  }, [finds, q, sort, sport]);

  async function load() {
    setLoading(true);
    setError("");
    setNeedLogin(false);
    try {
      setFinds(await listMyFinds());
    } catch (e: any) {
      if (e?.response?.status === 401) setNeedLogin(true);
      else setError("Couldn't load your finds. Try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  return (
    <div style={{ maxWidth: 820, margin: "24px auto", padding: "0 16px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1 style={{ fontSize: 24, margin: 0 }}>Recent Finds</h1>
        <button onClick={load} style={{ background: "#f1f5f9", border: "1px solid #cbd5e1", borderRadius: 8, padding: "6px 14px", cursor: "pointer", fontSize: 14 }}>↻ Refresh</button>
      </div>
      <p style={{ color: "#64748b", marginTop: 4 }}>Cards your alerts have caught — newest first.</p>

      {!loading && !needLogin && finds.length > 0 && (
        <div style={{ position: "relative", marginTop: 10 }}>
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="🔎 Search finds — card, player, alert, price…"
            style={{ width: "100%", padding: "10px 34px 10px 12px", borderRadius: 10, border: "1px solid #cbd5e1", fontSize: 14, boxSizing: "border-box" }}
          />
          {q && <button onClick={() => setQ("")} title="Clear"
            style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 16 }}>✕</button>}
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
            <select value={sort} onChange={e => setSort(e.target.value as any)}
              style={{ fontSize: 13, fontWeight: 600, padding: "6px 10px", borderRadius: 8, border: "1px solid #cbd5e1", cursor: "pointer" }}>
              <option value="newest">Newest first</option>
              <option value="priceHigh">Price: high → low</option>
              <option value="priceLow">Price: low → high</option>
            </select>
            {["all", ...sports].map(s => (
              <button key={s} onClick={() => setSport(s)}
                style={{ fontSize: 13, fontWeight: 600, padding: "5px 12px", borderRadius: 999, cursor: "pointer",
                  border: sport === s ? "1px solid #2563eb" : "1px solid #cbd5e1",
                  background: sport === s ? "#2563eb" : "#fff", color: sport === s ? "#fff" : "#334155" }}>
                {s === "all" ? "All sports" : s}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 13, color: "#94a3b8", marginTop: 6 }}>
            {shown.length === finds.length ? `${finds.length} finds` : `${shown.length} of ${finds.length} shown`}
          </div>
        </div>
      )}

      {loading && <p className="subtitle">Loading…</p>}
      {needLogin && <p className="subtitle">Sign in on the <strong>Alerts</strong> tab to see your finds.</p>}
      {error && <div style={{ color: "#dc2626" }}>{error}</div>}
      {!loading && !needLogin && !error && finds.length === 0 && (
        <p className="subtitle">No finds yet — they'll show up here as your alerts fire.</p>
      )}

      {!loading && q && shown.length === 0 && finds.length > 0 && (
        <p className="subtitle" style={{ marginTop: 16 }}>No finds match "{q}".</p>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 16 }}>
        {shown.map((f, i) => {
          const badge = dealBadge(f.pct_vs_market, f.is_auction);
          return (
            <a
              key={i}
              href={f.listing_url || "#"}
              target="_blank"
              rel="noreferrer"
              style={{ display: "flex", gap: 14, padding: 12, border: "1px solid #e2e8f0", borderRadius: 12, textDecoration: "none", color: "#0f172a", background: "#fff" }}
            >
              {f.image_url
                ? <img src={f.image_url} alt="" style={{ width: 84, height: 84, objectFit: "cover", borderRadius: 8, flexShrink: 0, border: "1px solid #e2e8f0" }} />
                : <div style={{ width: 84, height: 84, borderRadius: 8, background: "#f1f5f9", flexShrink: 0 }} />}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 15, lineHeight: 1.3 }}>{f.title}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 18, fontWeight: 700, color: "#16a34a" }}>
                    ${(f.price ?? 0).toLocaleString()}
                  </span>
                  {badge && (
                    <span style={{ background: badge.color, color: "#fff", padding: "2px 9px", borderRadius: 6, fontSize: 12, fontWeight: 600 }}>
                      {badge.text}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 13, color: "#64748b", marginTop: 6 }}>
                  alert: <strong>{f.alert}</strong> · {timeAgo(f.sent_at)}
                  {f.sport && f.sport !== "Other" && <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 600, color: "#475569", background: "rgba(100,116,139,0.12)", padding: "1px 7px", borderRadius: 6 }}>{f.sport}</span>}
                </div>
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
}
