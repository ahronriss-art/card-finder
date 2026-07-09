import { useEffect, useState } from "react";
import {
  checkShopPassword, getShopsPassword, clearShopsPassword,
  getWaxHistory, type WaxSale, type WaxStats,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";
import SoldChart from "./SoldChart";

const money = (n?: number | null) => (n == null ? "—" : n >= 1000 ? `$${(n / 1000).toFixed(2)}k` : `$${Math.round(n).toLocaleString()}`);
function fmtDate(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const SUGGEST = [
  "2024 Topps Chrome Baseball Hobby Box",
  "2023-24 Panini Prizm Basketball Hobby Box",
  "2024 Bowman Chrome Baseball Hobby Box",
  "2023 Topps Chrome UCL Hobby Box",
];

function Board() {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [res, setRes] = useState<{ query: string; sold: WaxSale[]; stats: WaxStats | null } | null>(null);

  async function run(term?: string) {
    const query = (term ?? q).trim();
    if (!query) return;
    setQ(query); setLoading(true); setError(""); setRes(null);
    try {
      const r = await getWaxHistory(query);
      setRes(r);
      if (!r.stats) setError("No sealed-box sales found — try the full box name (e.g. add 'Hobby Box').");
    } catch { setError("Couldn't load box prices right now."); }
    finally { setLoading(false); }
  }

  const stats = res?.stats;
  const sales = (res?.sold || []).slice()
    .sort((a, b) => (b.sold_at || "").localeCompare(a.sold_at || ""));

  const stat = (label: string, val: string, sub?: string) => (
    <div style={{ flex: "1 1 130px", minWidth: 120, background: "#fff", color: "#0f172a", border: "1px solid #e2e8f0",
      borderRadius: 12, padding: "12px 14px" }}>
      <div style={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800 }}>{val}</div>
      {sub && <div style={{ fontSize: 11, color: "#64748b" }}>{sub}</div>}
    </div>
  );

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 820 }}>
      <h1>Wax Ladder</h1>
      <p className="subtitle">Search any sealed wax box → see what it's actually selling for on eBay, with a price chart.</p>

      <form onSubmit={e => { e.preventDefault(); run(); }} style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap" }}>
        <input className="add-alert-input" placeholder="e.g. 2024 Topps Chrome Baseball Hobby Box"
          value={q} onChange={e => setQ(e.target.value)} style={{ flex: 1, minWidth: 240 }} />
        <button className="btn btn-sm" type="submit" disabled={loading}>{loading ? "Searching…" : "Search"}</button>
      </form>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
        {SUGGEST.map(s => (
          <button key={s} type="button" onClick={() => run(s)}
            style={{ fontSize: 12, padding: "4px 10px", borderRadius: 999, border: "1px solid #cbd5e1", background: "#fff", color: "#334155", cursor: "pointer" }}>
            {s}
          </button>
        ))}
      </div>

      {error && <div className="error-msg" style={{ marginTop: 14 }}>{error}</div>}

      {stats && (
        <div style={{ marginTop: 18 }}>
          <div style={{ fontSize: 13, color: "#94a3b8", marginBottom: 8 }}>
            Sold prices for <strong style={{ color: "#e2e8f0" }}>{res!.query}</strong> · {stats.count} recent sales
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {stat("Market (median)", money(stats.median))}
            {stat("Last sale", money(stats.last_price), fmtDate(stats.last_date))}
            {stat("Range", `${money(stats.min)} – ${money(stats.max)}`)}
            {stat("Average", money(stats.avg), `${stats.count} sales`)}
          </div>

          <div style={{ marginTop: 16, background: "#211d3f", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: 14 }}>
            <SoldChart sold={sales as any} price={stats.median} />
            {sales.length < 2 && <div className="subtitle" style={{ margin: 0 }}>Not enough dated sales to chart.</div>}
          </div>

          {/* Recent sales table */}
          <div style={{ marginTop: 16, overflowX: "auto", border: "1px solid #e2e8f0", borderRadius: 10 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, background: "#fff", color: "#0f172a" }}>
              <thead>
                <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                  <th style={{ padding: "8px 10px" }}>Sold</th>
                  <th style={{ padding: "8px 10px" }}>Price</th>
                  <th style={{ padding: "8px 10px" }}>Listing</th>
                </tr>
              </thead>
              <tbody>
                {sales.map((s, i) => (
                  <tr key={i} style={{ borderTop: "1px solid #e2e8f0" }}>
                    <td style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>{fmtDate(s.sold_at) || "—"}</td>
                    <td style={{ padding: "6px 10px", fontWeight: 700 }}>{money(s.sold_price)}</td>
                    <td style={{ padding: "6px 10px" }}>
                      <a href={s.listing_url || "#"} target="_blank" rel="noreferrer" style={{ color: "#2563eb", textDecoration: "none" }}>
                        {(s.title || "view").slice(0, 70)} ↗
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 8 }}>
            Sold comps from eBay (last ~50), filtered to sealed boxes — breaks, cases, singles, and graded lots are excluded.
          </div>
        </div>
      )}
    </div>
  );
}

export default function WaxLadderPage() {
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
  if (!unlocked) return <ShopPasswordForm title="Wax Ladder" onUnlocked={() => setUnlocked(true)} />;
  return <Board />;
}
