import { useEffect, useState } from "react";
import {
  checkShopPassword, getShopsPassword, clearShopsPassword,
  dealCheck, type DealCheck,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";

const money = (n?: number | null) => (n == null ? "—" : n >= 1000 ? `$${(n / 1000).toFixed(2)}k` : `$${Math.round(n).toLocaleString()}`);

const VERDICT: Record<string, { text: string; color: string }> = {
  steal: { text: "🔥 STEAL", color: "#16a34a" },
  good: { text: "✅ Good buy", color: "#22c55e" },
  fair: { text: "≈ Around market", color: "#0891b2" },
  high: { text: "❌ Overpriced", color: "#dc2626" },
  unknown: { text: "🤷 No comps", color: "#64748b" },
};

function Board() {
  const [input, setInput] = useState("");
  const [price, setPrice] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [res, setRes] = useState<DealCheck | null>(null);

  async function run() {
    const val = input.trim();
    if (!val) return;
    setLoading(true); setError(""); setRes(null);
    const isUrl = /^https?:\/\//i.test(val);
    const p = parseFloat(price);
    try {
      const r = await dealCheck(isUrl ? { url: val, price: isNaN(p) ? undefined : p }
                                      : { query: val, price: isNaN(p) ? undefined : p });
      setRes(r);
      if (r.market == null) setError("Couldn't find sold comps for this card — add more detail.");
      else if (r.ask == null) setError("Got the market price, but no asking price — paste the price or an eBay link.");
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't check that right now.");
    } finally { setLoading(false); }
  }

  const v = res ? VERDICT[res.verdict] : null;

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 720 }}>
      <h1>Deal Check</h1>
      <p className="subtitle">Paste an eBay link (or a card name), add the asking price, and see if it's a good buy vs recent sold comps.</p>

      <form onSubmit={e => { e.preventDefault(); run(); }} style={{ marginTop: 16 }}>
        <input className="add-alert-input" placeholder="Paste an eBay link, or type the card (year set player parallel grade)"
          value={input} onChange={e => setInput(e.target.value)} style={{ width: "100%", boxSizing: "border-box" }} />
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <input className="add-alert-input" type="number" step="0.01" placeholder="Asking price $ (optional if pasting a link)"
            value={price} onChange={e => setPrice(e.target.value)} style={{ flex: 1, minWidth: 200 }} />
          <button className="btn btn-sm" type="submit" disabled={loading}>{loading ? "Checking…" : "Check deal"}</button>
        </div>
      </form>

      {error && <div className="error-msg" style={{ marginTop: 14 }}>{error}</div>}

      {res && res.market != null && (
        <div style={{ marginTop: 18, background: "#211d3f", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: 16 }}>
          <div style={{ display: "flex", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
            {res.image_url && <img src={res.image_url} alt="" style={{ width: 90, height: 90, objectFit: "cover", borderRadius: 8, border: "1px solid rgba(255,255,255,0.1)" }} />}
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ color: "#e2e8f0", fontWeight: 700 }}>{res.title}</div>
              {v && (
                <div style={{ marginTop: 6, fontSize: 22, fontWeight: 900, color: v.color }}>
                  {v.text}{res.pct != null && <span style={{ fontSize: 14, fontWeight: 700 }}> · {res.pct > 0 ? "+" : ""}{res.pct}% vs market</span>}
                </div>
              )}
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
            {stat("Asking", money(res.ask))}
            {stat("Market (median)", money(res.market), `${res.comps} comps`)}
            {res.range && stat("Comp range", `${money(res.range[0])} – ${money(res.range[1])}`)}
            {res.pct != null && res.ask != null && stat("vs market", `${res.pct > 0 ? "+" : ""}${res.pct}%`)}
          </div>
          {res.listing_url && (
            <a href={res.listing_url} target="_blank" rel="noreferrer" style={{ display: "inline-block", marginTop: 12, color: "#818cf8", fontSize: 13, textDecoration: "none" }}>
              View listing ↗
            </a>
          )}
        </div>
      )}
    </div>
  );
}

function stat(label: string, val: string, sub?: string) {
  return (
    <div style={{ flex: "1 1 130px", minWidth: 120, background: "#fff", color: "#0f172a", border: "1px solid #e2e8f0", borderRadius: 12, padding: "10px 14px" }}>
      <div style={{ fontSize: 11, color: "#64748b", fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 800 }}>{val}</div>
      {sub && <div style={{ fontSize: 11, color: "#64748b" }}>{sub}</div>}
    </div>
  );
}

export default function DealCheckPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    const stored = getShopsPassword();
    if (!stored) { setChecking(false); return; }
    setUnlocked(true); setChecking(false);
    checkShopPassword(stored).catch((err) => {
      if (err?.response?.status === 401) { clearShopsPassword(); setUnlocked(false); }
    });
  }, []);
  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;
  if (!unlocked) return <ShopPasswordForm title="Deal Check" onUnlocked={() => setUnlocked(true)} />;
  return <Board />;
}
