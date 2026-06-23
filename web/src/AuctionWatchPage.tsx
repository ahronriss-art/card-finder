import { useEffect, useState } from "react";
import { authMe, getSavedSearches, getAlertAuctions, type AuctionListing } from "./api/client";

interface Alert { id: number; query: string; folder?: string | null; }

// "ends in 2h 14m" / "ends in 3d" / "ended" — and a color cue when it's close.
function timeLeft(iso: string | null): { text: string; urgent: boolean } | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return { text: "ended", urgent: false };
  const mins = Math.floor(ms / 60000);
  const days = Math.floor(mins / 1440);
  const hrs = Math.floor((mins % 1440) / 60);
  const m = mins % 60;
  const urgent = ms < 60 * 60 * 1000; // under an hour
  if (days > 0) return { text: `ends in ${days}d ${hrs}h`, urgent: false };
  if (hrs > 0) return { text: `ends in ${hrs}h ${m}m`, urgent };
  return { text: `ends in ${m}m`, urgent: true };
}

export default function AuctionWatchPage() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [needLogin, setNeedLogin] = useState(false);
  const [loadingAlerts, setLoadingAlerts] = useState(true);
  const [selected, setSelected] = useState<Alert | null>(null);
  const [auctions, setAuctions] = useState<AuctionListing[]>([]);
  const [loadingAuctions, setLoadingAuctions] = useState(false);
  const [error, setError] = useState("");
  const [, setTick] = useState(0);

  // Re-render every 30s so the countdowns stay current.
  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 30000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const me = await authMe();
        const list = await getSavedSearches(me.id);
        setAlerts(list);
      } catch (e: any) {
        if (e?.response?.status === 401) setNeedLogin(true);
        else setError("Couldn't load your alerts.");
      } finally {
        setLoadingAlerts(false);
      }
    })();
  }, []);

  async function pick(a: Alert) {
    setSelected(a);
    setAuctions([]);
    setError("");
    setLoadingAuctions(true);
    try {
      setAuctions(await getAlertAuctions(a.id));
    } catch {
      setError("Couldn't load auctions. Try again in a moment.");
    } finally {
      setLoadingAuctions(false);
    }
  }

  if (needLogin) {
    return (
      <div style={{ maxWidth: 720, margin: "24px auto", padding: "0 16px" }}>
        <h1 style={{ fontSize: 24 }}>Auction Watch</h1>
        <p className="subtitle">Sign in on the <strong>Alerts</strong> tab to browse auctions for your alerts.</p>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 860, margin: "24px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>Auction Watch</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Pick one of your alerts to see <strong>live eBay auctions</strong> matching it right now. Browse only — no alerts are sent.
      </p>

      {loadingAlerts && <p className="subtitle">Loading your alerts…</p>}

      {!loadingAlerts && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "14px 0 20px" }}>
          {alerts.map(a => (
            <button
              key={a.id}
              onClick={() => pick(a)}
              style={{
                padding: "7px 13px", borderRadius: 999, fontSize: 13, cursor: "pointer",
                border: "1px solid " + (selected?.id === a.id ? "#2563eb" : "#cbd5e1"),
                background: selected?.id === a.id ? "#2563eb" : "#fff",
                color: selected?.id === a.id ? "#fff" : "#0f172a",
              }}
            >
              {a.query}
            </button>
          ))}
          {alerts.length === 0 && <p className="subtitle">No alerts yet — create some on the Alerts tab.</p>}
        </div>
      )}

      {selected && (
        <>
          <h2 style={{ fontSize: 17, margin: "8px 0 2px" }}>
            🔨 Live auctions for “{selected.query}”
          </h2>
          {auctions.length > 0 && <p style={{ color: "#64748b", margin: "0 0 10px", fontSize: 13 }}>Ending soonest first.</p>}
          {loadingAuctions && <p className="subtitle">Searching eBay…</p>}
          {error && <div style={{ color: "#dc2626" }}>{error}</div>}
          {!loadingAuctions && !error && auctions.length === 0 && (
            <p className="subtitle">No live auctions matching this alert right now.</p>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {auctions.map((l, i) => (
              <a
                key={i}
                href={l.listing_url || "#"}
                target="_blank"
                rel="noreferrer"
                style={{ display: "flex", gap: 14, padding: 12, border: "1px solid #e2e8f0", borderRadius: 12, textDecoration: "none", color: "#0f172a", background: "#fff" }}
              >
                {l.image_url
                  ? <img src={l.image_url} alt="" style={{ width: 84, height: 84, objectFit: "cover", borderRadius: 8, flexShrink: 0, border: "1px solid #e2e8f0" }} />
                  : <div style={{ width: 84, height: 84, borderRadius: 8, background: "#f1f5f9", flexShrink: 0 }} />}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 15, lineHeight: 1.3 }}>{l.title}</div>
                  <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 6, flexWrap: "wrap" }}>
                    <div>
                      <div style={{ fontSize: 13, color: "#64748b" }}>Current bid</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: "#7c3aed" }}>
                        ${(l.price ?? 0).toLocaleString()}
                      </div>
                    </div>
                    {(() => {
                      const tl = timeLeft(l.end_date);
                      if (!tl) return null;
                      return (
                        <span style={{
                          fontSize: 13, fontWeight: 600, padding: "3px 10px", borderRadius: 6,
                          background: tl.urgent ? "#fee2e2" : "#f1f5f9",
                          color: tl.urgent ? "#dc2626" : "#475569",
                        }}>
                          ⏱ {tl.text}
                        </span>
                      );
                    })()}
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
