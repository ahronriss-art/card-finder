import { useEffect, useState } from "react";
import { getSellerWatches, addSellerWatch, deleteSellerWatch, type SellerWatch } from "./api/client";

// Watch a specific eBay seller — get alerted when they post new listings.
// Self-contained so it can drop onto any page (rendered on Auction Watch).
export default function SellerWatchPanel() {
  const [watches, setWatches] = useState<SellerWatch[]>([]);
  const [seller, setSeller] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const userId = Number(localStorage.getItem("userId")) || null;

  useEffect(() => {
    if (userId) getSellerWatches().then(setWatches).catch(() => {});
  }, [userId]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const name = seller.trim().replace(/^@/, "");
    if (!name) return;
    setBusy(true); setErr("");
    try {
      const w = await addSellerWatch(name);
      setWatches(prev => [w, ...prev.filter(x => x.id !== w.id)]);
      setSeller("");
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "Couldn't add that seller.");
    } finally { setBusy(false); }
  }

  async function remove(id: number) {
    await deleteSellerWatch(id).catch(() => {});
    setWatches(prev => prev.filter(w => w.id !== id));
  }

  return (
    <div style={{ border: "1px solid #e2e8f0", borderRadius: 12, padding: 16, background: "#fff", margin: "18px 0" }}>
      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 4 }}>🧑‍💼 Seller Watch</div>
      <p style={{ color: "#64748b", fontSize: 13, margin: "0 0 12px" }}>
        Get an email/text when a specific eBay seller posts <strong>new listings</strong>. Great for your go-to sources.
      </p>

      {!userId ? (
        <p style={{ color: "#64748b", fontSize: 13 }}>Sign in on the <strong>Alerts</strong> tab to watch sellers.</p>
      ) : (
        <>
          <form onSubmit={add} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input value={seller} onChange={e => setSeller(e.target.value)}
              placeholder="eBay seller username (e.g. probstein123)"
              style={{ flex: 1, minWidth: 220, padding: "9px 11px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
            <button className="btn btn-sm" type="submit" disabled={busy || !seller.trim()}>{busy ? "Adding…" : "+ Watch seller"}</button>
          </form>
          {err && <div style={{ color: "#dc2626", fontSize: 13, marginTop: 8 }}>{err}</div>}

          {watches.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
              {watches.map(w => (
                <div key={w.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px",
                  border: "1px solid #e2e8f0", borderRadius: 10 }}>
                  <div style={{ flex: 1 }}>
                    <a href={w.url} target="_blank" rel="noreferrer" style={{ fontWeight: 600, color: "#0f172a", textDecoration: "none" }}>{w.seller_name}</a>
                    <div style={{ fontSize: 12, color: "#94a3b8" }}>
                      watching for new listings{w.last_checked_at ? ` · checked ${new Date(w.last_checked_at).toLocaleString()}` : ""}
                    </div>
                  </div>
                  <button onClick={() => remove(w.id)} style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 14 }}>✕</button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
