import { useEffect, useState } from "react";
import type { WaxSale, WaxStats, TrackedWax } from "./api/client";
import SoldChart from "./SoldChart";

const money = (n?: number | null) => (n == null ? "—" : n >= 1000 ? `$${(n / 1000).toFixed(2)}k` : `$${Math.round(n).toLocaleString()}`);
function fmtDate(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export type LadderConfig = {
  title: string;
  subtitle: string;
  placeholder: string;
  suggest: string[];
  trackLabel: string;      // e.g. "📌 Track this box"
  trackedTitle: string;    // e.g. "📌 Tracked boxes"
  emptyHint: string;       // no-results message
  compsNote: string;       // footer note under the table
  api: {
    history: (q: string) => Promise<{ query: string; sold: WaxSale[]; stats: WaxStats | null }>;
    tracked: () => Promise<TrackedWax[]>;
    track: (q: string) => Promise<any>;
    untrack: (k: string) => Promise<any>;
    target: (k: string, t: number) => Promise<any>;
  };
};

export default function LadderBoard({ config }: { config: LadderConfig }) {
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [res, setRes] = useState<{ query: string; sold: WaxSale[]; stats: WaxStats | null } | null>(null);
  const [tracked, setTracked] = useState<TrackedWax[]>([]);
  const [tracking, setTracking] = useState(false);

  async function loadTracked() {
    try { setTracked(await config.api.tracked()); } catch { /* ignore */ }
  }
  useEffect(() => { loadTracked(); /* eslint-disable-next-line */ }, []);

  async function run(term?: string) {
    const query = (term ?? q).trim();
    if (!query) return;
    setQ(query); setLoading(true); setError(""); setRes(null);
    try {
      const r = await config.api.history(query);
      setRes(r);
      if (!r.stats) setError(config.emptyHint);
    } catch { setError("Couldn't load prices right now."); }
    finally { setLoading(false); }
  }

  async function track() {
    if (!res?.query) return;
    setTracking(true);
    try { await config.api.track(res.query); await loadTracked(); }
    catch { /* ignore */ }
    finally { setTracking(false); }
  }
  async function untrack(box_key: string) {
    try { await config.api.untrack(box_key); await loadTracked(); } catch { /* ignore */ }
  }
  async function saveTarget(box_key: string, raw: string) {
    const n = parseFloat(raw);
    try { await config.api.target(box_key, isNaN(n) ? 0 : n); await loadTracked(); } catch { /* ignore */ }
  }

  const stats = res?.stats;
  const isTracked = !!res?.query && tracked.some(t => t.query.toLowerCase() === res.query.toLowerCase());
  const sales = (res?.sold || []).slice().sort((a, b) => (b.sold_at || "").localeCompare(a.sold_at || ""));

  const stat = (label: string, val: string, sub?: string) => (
    <div style={{ flex: "1 1 130px", minWidth: 120, background: "#fff", color: "#0f172a", border: "1px solid #e2e8f0", borderRadius: 12, padding: "12px 14px" }}>
      <div style={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800 }}>{val}</div>
      {sub && <div style={{ fontSize: 11, color: "#64748b" }}>{sub}</div>}
    </div>
  );

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 820 }}>
      <h1>{config.title}</h1>
      <p className="subtitle">{config.subtitle}</p>

      <form onSubmit={e => { e.preventDefault(); run(); }} style={{ display: "flex", gap: 8, marginTop: 16, flexWrap: "wrap" }}>
        <input className="add-alert-input" placeholder={config.placeholder}
          value={q} onChange={e => setQ(e.target.value)} style={{ flex: 1, minWidth: 240 }} />
        <button className="btn btn-sm" type="submit" disabled={loading}>{loading ? "Searching…" : "Search"}</button>
      </form>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
        {config.suggest.map(s => (
          <button key={s} type="button" onClick={() => run(s)}
            style={{ fontSize: 12, padding: "4px 10px", borderRadius: 999, border: "1px solid #cbd5e1", background: "#fff", color: "#334155", cursor: "pointer" }}>
            {s}
          </button>
        ))}
      </div>

      {error && <div className="error-msg" style={{ marginTop: 14 }}>{error}</div>}

      {stats && (
        <div style={{ marginTop: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
            <div style={{ fontSize: 13, color: "#94a3b8", flex: 1, minWidth: 180 }}>
              Sold prices for <strong style={{ color: "#e2e8f0" }}>{res!.query}</strong> · {stats.count} recent sales
            </div>
            {isTracked ? (
              <span style={{ fontSize: 12, color: "#34d399", fontWeight: 700 }}>📌 Tracking</span>
            ) : (
              <button className="btn btn-sm" type="button" onClick={track} disabled={tracking}>
                {tracking ? "Adding…" : config.trackLabel}
              </button>
            )}
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
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 8 }}>{config.compsNote}</div>
        </div>
      )}

      {tracked.length > 0 && (
        <div style={{ marginTop: 34 }}>
          <h2 style={{ fontSize: 18, margin: "0 0 4px" }}>{config.trackedTitle}</h2>
          <p className="subtitle" style={{ marginTop: 0 }}>A real dated price ladder — each gets a fresh reading once a day.</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 12 }}>
            {tracked.map(t => {
              const pts = t.history.filter(h => h.median != null).map(h => ({ sold_price: h.median as number, sold_at: h.day }));
              const up = (t.change ?? 0) > 0, down = (t.change ?? 0) < 0;
              const col = up ? "#34d399" : down ? "#f87171" : "#94a3b8";
              return (
                <div key={t.id} style={{ background: "#211d3f", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: 14 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <button type="button" onClick={() => run(t.query)}
                      style={{ background: "none", border: "none", color: "#e2e8f0", fontWeight: 700, fontSize: 15, cursor: "pointer", padding: 0, textAlign: "left" }}>
                      {t.query}
                    </button>
                    {t.hit && <span style={{ background: "#16a34a", color: "#fff", fontWeight: 800, fontSize: 12, borderRadius: 6, padding: "2px 8px" }}>🎯 BUY — at target</span>}
                    <div style={{ flex: 1 }} />
                    {t.latest != null && <span style={{ color: "#e2e8f0", fontWeight: 800, fontSize: 16 }}>{money(t.latest)}</span>}
                    {t.change != null && t.change_pct != null && (
                      <span style={{ color: col, fontWeight: 700, fontSize: 13 }}>
                        {up ? "▲" : down ? "▼" : "—"} {money(Math.abs(t.change))} ({t.change_pct > 0 ? "+" : ""}{t.change_pct}%)
                      </span>
                    )}
                    <button type="button" onClick={() => untrack(t.box_key)}
                      style={{ fontSize: 12, color: "#94a3b8", background: "none", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 8, padding: "3px 8px", cursor: "pointer" }}>
                      Untrack
                    </button>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, fontSize: 12, color: "#94a3b8" }}>
                    <span>🎯 Buy target $</span>
                    <input type="number" defaultValue={t.target_price ?? ""} placeholder="none"
                      onBlur={e => { const v = e.target.value; if (String(t.target_price ?? "") !== v) saveTarget(t.box_key, v); }}
                      onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                      style={{ width: 90, padding: "3px 6px", borderRadius: 6, border: "1px solid #cbd5e1", background: "#fff", color: "#0f172a", fontSize: 12 }} />
                    <span style={{ color: "#64748b" }}>— we email a buy signal when the daily median drops to/below it.</span>
                  </div>
                  {pts.length >= 2 ? (
                    <div style={{ marginTop: 10 }}><SoldChart sold={pts as any} price={t.latest ?? undefined} /></div>
                  ) : (
                    <div className="subtitle" style={{ margin: "8px 0 0" }}>Tracking since today — the ladder builds a point each day. Check back tomorrow for a trend.</div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
