import { Fragment, useEffect, useMemo, useState } from "react";
import {
  getPortfolio, addPortfolioCard, deletePortfolioCard, revaluePortfolio, getSoldHistory,
  type PortfolioCard,
} from "./api/client";
import SoldChart from "./SoldChart";

// Track cards you own and value them against eBay sold comps — total inventory
// value and gain/loss vs what you paid.
export default function PortfolioPage() {
  const [cards, setCards] = useState<PortfolioCard[]>([]);
  const [needLogin, setNeedLogin] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [valuing, setValuing] = useState(false);

  const [name, setName] = useState("");
  const [paid, setPaid] = useState("");
  const [qty, setQty] = useState("1");

  // Per-card price-history chart (sold comps over time), fetched on demand.
  const [openChart, setOpenChart] = useState<number | null>(null);
  const [chartData, setChartData] = useState<Record<number, any[]>>({});
  const [chartLoading, setChartLoading] = useState<number | null>(null);
  async function toggleChart(c: PortfolioCard) {
    if (openChart === c.id) { setOpenChart(null); return; }
    setOpenChart(c.id);
    if (!chartData[c.id]) {
      setChartLoading(c.id);
      try {
        const data = await getSoldHistory(c.name);
        setChartData(prev => ({ ...prev, [c.id]: data.sold || [] }));
      } catch { setChartData(prev => ({ ...prev, [c.id]: [] })); }
      finally { setChartLoading(null); }
    }
  }

  async function load() {
    try { setCards(await getPortfolio()); }
    catch (e: any) { if (e?.response?.status === 401) setNeedLogin(true); }
  }
  useEffect(() => { load(); }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true); setError("");
    try {
      await addPortfolioCard({
        name: name.trim(),
        paid: paid ? parseFloat(paid) : undefined,
        qty: qty ? Math.max(1, parseInt(qty, 10)) : 1,
      });
      setName(""); setPaid(""); setQty("1");
      await load();
    } catch { setError("Couldn't add that card."); }
    finally { setBusy(false); }
  }

  async function remove(id: number) {
    await deletePortfolioCard(id).catch(() => {});
    setCards(prev => prev.filter(c => c.id !== id));
  }

  async function revalue() {
    setValuing(true); setError("");
    try { setCards((await revaluePortfolio()).cards); }
    catch { setError("Couldn't refresh values right now — try again."); }
    finally { setValuing(false); }
  }

  const totals = useMemo(() => {
    let value = 0, cost = 0, valued = 0;
    for (const c of cards) {
      const q = c.qty || 1;
      if (c.market_value != null) { value += c.market_value * q; valued++; }
      if (c.paid != null) cost += c.paid * q;
    }
    return { value, cost, gain: value - cost, valued };
  }, [cards]);

  const money = (n: number) => `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const gainColor = (g: number) => g > 0 ? "#16a34a" : g < 0 ? "#dc2626" : "#64748b";

  return (
    <div style={{ maxWidth: 900, margin: "24px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>📦 Portfolio</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Track the cards you own. "Revalue" prices each against recent eBay sold comps so you can see total inventory value and gain/loss.
      </p>

      {needLogin && <p className="subtitle">Sign in on the <strong>Alerts</strong> tab to use your portfolio.</p>}

      {!needLogin && <>
        {/* Totals */}
        {cards.length > 0 && (
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", padding: "14px 18px", borderRadius: 12,
            background: "#0f172a", color: "#fff", margin: "12px 0" }}>
            <div><div style={{ fontSize: 12, opacity: 0.7 }}>Market value</div><div style={{ fontSize: 22, fontWeight: 800 }}>{money(totals.value)}</div></div>
            <div><div style={{ fontSize: 12, opacity: 0.7 }}>Cost basis</div><div style={{ fontSize: 22, fontWeight: 800 }}>{money(totals.cost)}</div></div>
            <div><div style={{ fontSize: 12, opacity: 0.7 }}>Gain / loss</div><div style={{ fontSize: 22, fontWeight: 800, color: gainColor(totals.gain) }}>{totals.gain >= 0 ? "+" : "−"}{money(Math.abs(totals.gain))}</div></div>
            <button onClick={revalue} disabled={valuing}
              style={{ marginLeft: "auto", alignSelf: "center", background: valuing ? "#94a3b8" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "9px 16px", fontSize: 14, fontWeight: 700, cursor: valuing ? "default" : "pointer" }}>
              {valuing ? "Valuing…" : "↻ Revalue all"}
            </button>
          </div>
        )}

        {/* Add form */}
        <form onSubmit={add} style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "10px 0 18px" }}>
          <input placeholder="Card (e.g. 2023 Prizm Wembanyama Silver PSA 10)" value={name} onChange={e => setName(e.target.value)}
            style={{ flex: 3, minWidth: 240, padding: "9px 11px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
          <input placeholder="Paid $" value={paid} onChange={e => setPaid(e.target.value)} type="number" min="0"
            style={{ width: 90, padding: "9px 11px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
          <input placeholder="Qty" value={qty} onChange={e => setQty(e.target.value)} type="number" min="1"
            style={{ width: 64, padding: "9px 11px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
          <button className="btn btn-sm" type="submit" disabled={busy || !name.trim()}>{busy ? "Adding…" : "+ Add"}</button>
        </form>

        {error && <div style={{ color: "#dc2626", marginBottom: 10 }}>{error}</div>}
        {cards.length === 0 && <p className="subtitle">No cards yet — add ones you own above, then hit "Revalue all".</p>}

        {/* Cards table */}
        {cards.length > 0 && (
          <div style={{ overflowX: "auto", border: "1px solid #e2e8f0", borderRadius: 10 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, background: "#fff", color: "#0f172a" }}>
              <thead>
                <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                  <th style={{ padding: "8px 10px" }}>Card</th>
                  <th style={{ padding: "8px 10px" }}>Qty</th>
                  <th style={{ padding: "8px 10px" }}>Paid</th>
                  <th style={{ padding: "8px 10px" }}>Market</th>
                  <th style={{ padding: "8px 10px" }}>Gain/loss</th>
                  <th style={{ padding: "8px 10px" }}></th>
                </tr>
              </thead>
              <tbody>
                {cards.map(c => {
                  const q = c.qty || 1;
                  const mv = c.market_value != null ? c.market_value * q : null;
                  const cost = c.paid != null ? c.paid * q : null;
                  const gain = mv != null && cost != null ? mv - cost : null;
                  return (
                    <Fragment key={c.id}>
                    <tr style={{ borderTop: "1px solid #e2e8f0" }}>
                      <td style={{ padding: "8px 10px", fontWeight: 600 }}>
                        <a href={`https://www.ebay.com/sch/i.html?_nkw=${encodeURIComponent(c.name)}&_sop=13`} target="_blank" rel="noreferrer"
                          style={{ color: "#0f172a", textDecoration: "none" }}>{c.name}</a>
                      </td>
                      <td style={{ padding: "8px 10px" }}>{q}</td>
                      <td style={{ padding: "8px 10px" }}>{c.paid != null ? money(c.paid * q) : "—"}</td>
                      <td style={{ padding: "8px 10px" }}>
                        {mv != null ? <>{money(mv)} <span style={{ color: "#94a3b8", fontSize: 11 }}>({c.comps} comps)</span></>
                          : c.comps === 0 ? <span style={{ color: "#94a3b8" }}>no comps</span> : <span style={{ color: "#94a3b8" }}>not valued</span>}
                      </td>
                      <td style={{ padding: "8px 10px", fontWeight: 700, color: gain != null ? gainColor(gain) : "#94a3b8" }}>
                        {gain != null ? `${gain >= 0 ? "+" : "−"}${money(Math.abs(gain))}` : "—"}
                      </td>
                      <td style={{ padding: "8px 10px", textAlign: "right", whiteSpace: "nowrap" }}>
                        <button onClick={() => toggleChart(c)} title="Price history (sold comps over time)"
                          style={{ background: "none", border: "none", cursor: "pointer", fontSize: 15, marginRight: 6 }}>📈</button>
                        <button onClick={() => remove(c.id)} style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 14 }}>✕</button>
                      </td>
                    </tr>
                    {openChart === c.id && (
                      <tr>
                        <td colSpan={6} style={{ padding: "8px 10px 14px", background: "#0f172a" }}>
                          {chartLoading === c.id
                            ? <span style={{ color: "#94a3b8", fontSize: 13 }}>Loading price history…</span>
                            : (chartData[c.id] && chartData[c.id].length >= 2)
                              ? <div style={{ maxWidth: 340 }}><SoldChart sold={chartData[c.id]} price={c.market_value} /></div>
                              : <span style={{ color: "#94a3b8", fontSize: 13 }}>Not enough sold comps to chart — make the card name more specific.</span>}
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p style={{ color: "#94a3b8", fontSize: 12, marginTop: 8 }}>
          Market value = median of recent eBay sold comps for the card's name. Make the name specific (player, set, parallel, grade) for accurate comps.
        </p>
      </>}
    </div>
  );
}
