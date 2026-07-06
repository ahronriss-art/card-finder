import { useState } from "react";
import { getAlertMatchesAll, getDealsFeed, type MatchListing, type DealListing } from "./api/client";

type Mode = "deals" | "all";

export default function AllMatchesPage() {
  const [mode, setMode] = useState<Mode>("deals");
  const [matches, setMatches] = useState<MatchListing[]>([]);
  const [deals, setDeals] = useState<DealListing[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState<Mode | null>(null);
  const [needLogin, setNeedLogin] = useState(false);
  const [error, setError] = useState("");

  async function load(m: Mode) {
    setLoading(true); setError(""); setNeedLogin(false);
    try {
      if (m === "deals") setDeals(await getDealsFeed());
      else setMatches(await getAlertMatchesAll());
      setLoaded(m);
    } catch (e: any) {
      if (e?.response?.status === 401) setNeedLogin(true);
      else setError("Couldn't load. Try again in a moment.");
    } finally {
      setLoading(false);
    }
  }

  function switchMode(m: Mode) {
    setMode(m); setError(""); setLoaded(null);
  }

  const dealColor = (pct: number) => pct >= 30 ? "#dc2626" : pct >= 20 ? "#ea580c" : "#16a34a";

  return (
    <div style={{ maxWidth: 860, margin: "24px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>{mode === "deals" ? "🔥 Best Deals" : "All Matches"}</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        {mode === "deals"
          ? "Buy-It-Now listings across your alerts priced below their eBay sold-comp value — ranked by biggest discount. Browse only, no alerts sent."
          : "Every current eBay listing (Buy-It-Now + auctions) matching any of your alerts — most valuable first."}
      </p>

      {/* Mode toggle */}
      <div style={{ display: "inline-flex", gap: 4, background: "#f1f5f9", borderRadius: 10, padding: 4, marginBottom: 6 }}>
        {(["deals", "all"] as Mode[]).map(m => (
          <button key={m} onClick={() => switchMode(m)}
            style={{ border: "none", borderRadius: 7, padding: "6px 14px", fontSize: 13, fontWeight: 700, cursor: "pointer",
              background: mode === m ? "#fff" : "transparent", color: mode === m ? "#0f172a" : "#64748b",
              boxShadow: mode === m ? "0 1px 3px rgba(0,0,0,0.1)" : "none" }}>
            {m === "deals" ? "🔥 Best Deals" : "All Matches"}
          </button>
        ))}
      </div>

      {needLogin && <p className="subtitle">Sign in on the <strong>Alerts</strong> tab to see your {mode === "deals" ? "deals" : "matches"}.</p>}

      {!needLogin && (
        <div>
          <button
            onClick={() => load(mode)} disabled={loading}
            style={{ background: loading ? "#94a3b8" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "9px 18px", fontSize: 14, fontWeight: 600, cursor: loading ? "default" : "pointer", margin: "12px 0" }}
          >
            {loading ? "Scanning all your alerts… (~20–40s)"
              : loaded === mode ? "↻ Refresh"
              : mode === "deals" ? "Find the best deals" : "Load all current matches"}
          </button>
        </div>
      )}

      {error && <div style={{ color: "#dc2626" }}>{error}</div>}

      {/* Deals view */}
      {mode === "deals" && loaded === "deals" && !loading && (
        deals.length === 0
          ? <p className="subtitle">No listings are meaningfully under market right now. Check back later.</p>
          : <>
              <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 10px" }}>{deals.length} deal{deals.length === 1 ? "" : "s"} ≥10% under market.</p>
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {deals.map((l, i) => (
                  <a key={i} href={l.listing_url || "#"} target="_blank" rel="noreferrer"
                     style={{ display: "flex", gap: 14, padding: 12, border: "1px solid #e2e8f0", borderRadius: 12, textDecoration: "none", color: "#0f172a", background: "#fff" }}>
                    {l.image_url
                      ? <img src={l.image_url} alt="" style={{ width: 84, height: 84, objectFit: "cover", borderRadius: 8, flexShrink: 0, border: "1px solid #e2e8f0" }} />
                      : <div style={{ width: 84, height: 84, borderRadius: 8, background: "#f1f5f9", flexShrink: 0 }} />}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 15, lineHeight: 1.3 }}>{l.title}</div>
                      <div style={{ fontSize: 12, color: "#64748b", marginTop: 3 }}>alert: <strong>{l.alert}</strong></div>
                      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 18, fontWeight: 700, color: "#16a34a" }}>${l.price.toLocaleString()}</span>
                        <span style={{ fontSize: 13, color: "#64748b" }}>market ~${l.market.toLocaleString()} ({l.comps} comps)</span>
                        <span style={{ marginLeft: "auto", fontSize: 14, fontWeight: 800, color: "#fff", background: dealColor(l.pct_below), padding: "3px 10px", borderRadius: 999 }}>
                          {l.pct_below}% under
                        </span>
                      </div>
                    </div>
                  </a>
                ))}
              </div>
            </>
      )}

      {/* All-matches view */}
      {mode === "all" && loaded === "all" && !loading && (
        matches.length === 0
          ? <p className="subtitle">No current listings match your alerts right now.</p>
          : <>
              <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 10px" }}>{matches.length} matches found.</p>
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
            </>
      )}
    </div>
  );
}
