import { useState } from "react";
import { getAlertMatchesAll, type MatchListing } from "./api/client";

export default function AllMatchesPage() {
  const [matches, setMatches] = useState<MatchListing[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [needLogin, setNeedLogin] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    setNeedLogin(false);
    try {
      setMatches(await getAlertMatchesAll());
      setLoaded(true);
    } catch (e: any) {
      if (e?.response?.status === 401) setNeedLogin(true);
      else setError("Couldn't load matches. Try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 860, margin: "24px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>All Matches</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Every current eBay listing (Buy-It-Now + auctions) matching any of your alerts — most valuable first. Browse only, no alerts sent.
      </p>

      {needLogin && <p className="subtitle">Sign in on the <strong>Alerts</strong> tab to see your matches.</p>}

      {!needLogin && (
        <button
          onClick={load}
          disabled={loading}
          style={{ background: loading ? "#94a3b8" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "9px 18px", fontSize: 14, fontWeight: 600, cursor: loading ? "default" : "pointer", margin: "12px 0" }}
        >
          {loading ? "Searching all your alerts… (~20s)" : loaded ? "↻ Refresh matches" : "Load all current matches"}
        </button>
      )}

      {error && <div style={{ color: "#dc2626" }}>{error}</div>}
      {loaded && !loading && matches.length === 0 && (
        <p className="subtitle">No current listings match your alerts right now.</p>
      )}
      {loaded && matches.length > 0 && (
        <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 10px" }}>{matches.length} matches found.</p>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {matches.map((l, i) => (
          <a key={i} href={l.listing_url || "#"} target="_blank" rel="noreferrer"
             style={{ display: "flex", gap: 14, padding: 12, border: "1px solid #e2e8f0", borderRadius: 12, textDecoration: "none", color: "#0f172a", background: "#fff" }}>
            {l.image_url
              ? <img src={l.image_url} alt="" style={{ width: 84, height: 84, objectFit: "cover", borderRadius: 8, flexShrink: 0, border: "1px solid #e2e8f0" }} />
              : <div style={{ width: 84, height: 84, borderRadius: 8, background: "#f1f5f9", flexShrink: 0 }} />}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 15, lineHeight: 1.3 }}>{l.title}</div>
              <div style={{ fontSize: 12, color: "#64748b", marginTop: 3 }}>alert: <strong>{l.alert}</strong></div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
                <span style={{ fontSize: 18, fontWeight: 700, color: "#16a34a" }}>${(l.price ?? 0).toLocaleString()}</span>
                {l.is_auction && <span style={{ fontSize: 12, fontWeight: 600, color: "#7c3aed" }}>🔨 Auction</span>}
              </div>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
