import { useEffect, useState } from "react";
import { authMe, getSavedSearches, getAlertAuctions, getAlertAuctionsAll, listWatchedAuctions, watchAuction, unwatchAuction, type AuctionListing, type WatchedAuctionItem } from "./api/client";
import SellerWatchPanel from "./SellerWatchPanel";

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
  const [allMode, setAllMode] = useState(false);
  const [auctions, setAuctions] = useState<AuctionListing[]>([]);
  const [loadingAuctions, setLoadingAuctions] = useState(false);
  const [error, setError] = useState("");
  const [watchedList, setWatchedList] = useState<WatchedAuctionItem[]>([]);
  const watched = new Set(watchedList.map(w => w.external_id));
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
        try {
          setWatchedList(await listWatchedAuctions());
        } catch { /* ignore */ }
      } catch (e: any) {
        if (e?.response?.status === 401) setNeedLogin(true);
        else setError("Couldn't load your alerts.");
      } finally {
        setLoadingAlerts(false);
      }
    })();
  }, []);

  async function toggleWatch(e: React.MouseEvent, l: AuctionListing) {
    e.preventDefault();  // don't follow the card link
    if (!l.external_id) return;
    const id = l.external_id;
    const prev = watchedList;
    try {
      if (watched.has(id)) {
        setWatchedList(prev.filter(w => w.external_id !== id));
        await unwatchAuction(id);
      } else {
        setWatchedList([...prev, { id: Date.now(), external_id: id, title: l.title, image_url: l.image_url,
          listing_url: l.listing_url, price: l.price, end_date: l.end_date, notified: false }]);
        await watchAuction(l);
      }
    } catch {
      setWatchedList(prev);  // revert on failure
    }
  }

  async function unwatchById(id: string) {
    const prev = watchedList;
    setWatchedList(prev.filter(w => w.external_id !== id));
    try { await unwatchAuction(id); } catch { setWatchedList(prev); }
  }

  async function clearAllWatched() {
    if (!watchedList.length || !confirm(`Stop watching all ${watchedList.length} auction(s)?`)) return;
    const prev = watchedList;
    setWatchedList([]);
    try { await Promise.all(prev.map(w => unwatchAuction(w.external_id))); }
    catch { setWatchedList(prev); }
  }

  async function pick(a: Alert) {
    setSelected(a);
    setAllMode(false);
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

  async function pickAll() {
    setSelected(null);
    setAllMode(true);
    setAuctions([]);
    setError("");
    setLoadingAuctions(true);
    try {
      setAuctions(await getAlertAuctionsAll());
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
        Pick one of your alerts to see <strong>live eBay auctions</strong> matching it right now. Browsing sends no alerts — but you can <strong>★ Watch</strong> an auction to get a text ~30 min before it ends.
      </p>

      <SellerWatchPanel />

      {loadingAlerts && <p className="subtitle">Loading your alerts…</p>}

      {!loadingAlerts && alerts.length > 0 && (
        <button
          onClick={pickAll}
          style={{
            padding: "8px 16px", borderRadius: 999, fontSize: 13, fontWeight: 600, cursor: "pointer",
            margin: "14px 0 6px",
            border: "1px solid " + (allMode ? "#7c3aed" : "#cbd5e1"),
            background: allMode ? "#7c3aed" : "#faf5ff",
            color: allMode ? "#fff" : "#7c3aed",
          }}
        >
          🔨 All live auctions (across every alert)
        </button>
      )}

      {!loadingAlerts && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "8px 0 20px" }}>
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

      {watchedList.length > 0 && (
        <div style={{ border: "1px solid #fde68a", background: "#fffbeb", borderRadius: 12, padding: 14, marginBottom: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <div style={{ fontWeight: 700, fontSize: 15, color: "#92400e" }}>
              ★ Watching ({watchedList.length}) — you'll get a text ~30 min before each ends
            </div>
            <button onClick={clearAllWatched}
              style={{ flexShrink: 0, border: "1px solid #fca5a5", background: "#fff", color: "#dc2626", borderRadius: 6, padding: "3px 10px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
              Clear all
            </button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[...watchedList].sort((a, b) => (a.end_date || "9").localeCompare(b.end_date || "9")).map(w => {
              const tl = timeLeft(w.end_date);
              return (
                <div key={w.external_id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14 }}>
                  <a href={w.listing_url || "#"} target="_blank" rel="noreferrer" style={{ flex: 1, minWidth: 0, color: "#0f172a", textDecoration: "none", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {w.title}
                  </a>
                  <span style={{ color: "#7c3aed", fontWeight: 700, flexShrink: 0 }}>${(w.price ?? 0).toLocaleString()}</span>
                  {tl && <span style={{ flexShrink: 0, color: tl.urgent ? "#dc2626" : "#64748b", fontWeight: 600 }}>⏱ {tl.text}</span>}
                  <button onClick={() => unwatchById(w.external_id)} title="Stop watching this auction" style={{ flexShrink: 0, border: "1px solid #fca5a5", background: "#fff", borderRadius: 6, padding: "2px 9px", cursor: "pointer", color: "#dc2626", fontWeight: 600, fontSize: 12 }}>✕ Remove</button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {(selected || allMode) && (
        <>
          <h2 style={{ fontSize: 17, margin: "8px 0 2px" }}>
            {allMode ? "🔨 Live auctions across all your alerts" : `🔨 Live auctions for “${selected!.query}”`}
          </h2>
          {auctions.length > 0 && <p style={{ color: "#64748b", margin: "0 0 10px", fontSize: 13 }}>Ending soonest first.</p>}
          {loadingAuctions && <p className="subtitle">{allMode ? "Searching all your alerts on eBay (this can take ~20s)…" : "Searching eBay…"}</p>}
          {error && <div style={{ color: "#dc2626" }}>{error}</div>}
          {!loadingAuctions && !error && auctions.length === 0 && (
            <p className="subtitle">{allMode ? "No live auctions matching any of your alerts right now." : "No live auctions matching this alert right now."}</p>
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
                  {allMode && l.alert && (
                    <div style={{ fontSize: 12, color: "#64748b", marginTop: 3 }}>alert: <strong>{l.alert}</strong></div>
                  )}
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
                    {l.external_id && (
                      <button
                        onClick={(e) => toggleWatch(e, l)}
                        title="Get a text ~30 min before this auction ends"
                        style={{
                          fontSize: 13, fontWeight: 600, padding: "4px 11px", borderRadius: 6, cursor: "pointer",
                          border: "1px solid " + (watched.has(l.external_id) ? "#f59e0b" : "#cbd5e1"),
                          background: watched.has(l.external_id) ? "#fef3c7" : "#fff",
                          color: watched.has(l.external_id) ? "#b45309" : "#475569",
                        }}
                      >
                        {watched.has(l.external_id) ? "★ Watching" : "☆ Watch"}
                      </button>
                    )}
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
