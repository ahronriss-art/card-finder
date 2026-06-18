import { useEffect, useMemo, useState } from "react";
import { checkShopPassword, listCallerDeals, type CallerDeal } from "./api/client";

const money = (n: number) => `$${Math.round(n).toLocaleString()}`;

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="add-alert-box" style={{ flex: 1, minWidth: 150, padding: 16 }}>
      <div style={{ fontSize: 12, opacity: 0.65, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, opacity: 0.6, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function Dashboard() {
  const [deals, setDeals] = useState<CallerDeal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listCallerDeals().then(setDeals).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const s = useMemo(() => {
    const now = new Date();
    const ym = (d: string) => d.slice(0, 7); // YYYY-MM
    const thisMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    const amt = (d: CallerDeal) => d.amount || 0;

    const buys = deals.filter(d => d.kind === "buy");
    const sells = deals.filter(d => d.kind === "sell");
    const sum = (ds: CallerDeal[]) => ds.reduce((a, d) => a + amt(d), 0);

    // by caller (volume)
    const byCaller = new Map<string, { count: number; total: number }>();
    for (const d of deals) {
      const e = byCaller.get(d.caller_name) || { count: 0, total: 0 };
      e.count++; e.total += amt(d);
      byCaller.set(d.caller_name, e);
    }
    const topCallers = Array.from(byCaller.entries())
      .map(([name, v]) => ({ name, ...v }))
      .sort((a, b) => b.total - a.total || b.count - a.count)
      .slice(0, 8);

    // last 6 months
    const months: { key: string; label: string; count: number; total: number }[] = [];
    for (let i = 5; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      const ds = deals.filter(x => ym(x.created_at) === key);
      months.push({ key, label: d.toLocaleString(undefined, { month: "short" }), count: ds.length, total: sum(ds) });
    }
    const maxMonth = Math.max(1, ...months.map(m => m.total));

    const thisMonthDeals = deals.filter(d => ym(d.created_at) === thisMonth);
    const recent = deals.slice().sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 12);

    return {
      total: deals.length, volume: sum(deals),
      buyCount: buys.length, buyTotal: sum(buys),
      sellCount: sells.length, sellTotal: sum(sells),
      monthCount: thisMonthDeals.length, monthTotal: sum(thisMonthDeals),
      topCallers, months, maxMonth, recent,
    };
  }, [deals]);

  if (loading) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 860 }}>
      <h1>Deals Dashboard</h1>
      <p className="subtitle">Everything you've bought and sold with callers, at a glance.</p>

      {deals.length === 0 ? (
        <div className="empty" style={{ marginTop: 32 }}>
          <p style={{ fontSize: 15 }}>No deals logged yet. Add deals from a caller's section in the Caller Notes tab.</p>
        </div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 20 }}>
            <Stat label="Total deals" value={String(s.total)} sub={`${money(s.volume)} volume`} />
            <Stat label="This month" value={String(s.monthCount)} sub={money(s.monthTotal)} />
            <Stat label="Bought" value={money(s.buyTotal)} sub={`${s.buyCount} deal${s.buyCount === 1 ? "" : "s"}`} />
            <Stat label="Sold" value={money(s.sellTotal)} sub={`${s.sellCount} deal${s.sellCount === 1 ? "" : "s"}`} />
          </div>
          {(s.buyTotal > 0 || s.sellTotal > 0) && (
            <div className="add-alert-box" style={{ marginTop: 12, padding: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                Net (sold − bought): <span style={{ color: s.sellTotal - s.buyTotal >= 0 ? "#34d399" : "#f87171" }}>
                  {money(s.sellTotal - s.buyTotal)}
                </span>
                <span style={{ opacity: 0.55, fontWeight: 400 }}> — only counts deals tagged Bought/Sold</span>
              </div>
            </div>
          )}

          {/* Last 6 months */}
          <div className="add-alert-box" style={{ marginTop: 18, padding: 18 }}>
            <div className="add-alert-title" style={{ marginBottom: 12 }}>Last 6 months</div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 12, height: 140 }}>
              {s.months.map(m => (
                <div key={m.key} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end", height: "100%" }}>
                  <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 4 }}>{m.total ? money(m.total) : ""}</div>
                  <div title={`${m.count} deals · ${money(m.total)}`}
                    style={{ width: "70%", background: "linear-gradient(180deg,#f97316,#7c3aed)", borderRadius: 6,
                             height: `${Math.max(4, (m.total / s.maxMonth) * 100)}%`, minHeight: 4 }} />
                  <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>{m.label}</div>
                  <div style={{ fontSize: 11, opacity: 0.5 }}>{m.count}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 18 }}>
            {/* Top callers */}
            <div className="add-alert-box" style={{ flex: 1, minWidth: 280, padding: 18 }}>
              <div className="add-alert-title" style={{ marginBottom: 10 }}>Top callers by volume</div>
              {s.topCallers.map((c, i) => (
                <div key={c.name} style={{ display: "flex", justifyContent: "space-between", fontSize: 14, padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                  <span>{i + 1}. {c.name} <span style={{ opacity: 0.5, fontSize: 12 }}>({c.count})</span></span>
                  <span style={{ fontWeight: 600 }}>{money(c.total)}</span>
                </div>
              ))}
            </div>

            {/* Recent deals */}
            <div className="add-alert-box" style={{ flex: 1, minWidth: 280, padding: 18 }}>
              <div className="add-alert-title" style={{ marginBottom: 10 }}>Recent deals</div>
              {s.recent.map(d => (
                <div key={d.id} style={{ fontSize: 13, padding: "4px 0", borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                  <span style={{ opacity: 0.75 }}>{d.caller_name}</span>{" — "}
                  {d.kind === "buy" ? "🟢 " : d.kind === "sell" ? "🔵 " : ""}{d.description}
                  {d.amount != null ? <b> {money(d.amount)}</b> : ""}
                  <span style={{ opacity: 0.45 }}> · {new Date(d.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function DealsPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);
  const [pw, setPw] = useState("");
  const [pwError, setPwError] = useState("");

  useEffect(() => {
    const stored = localStorage.getItem("shopsPassword");
    if (!stored) { setChecking(false); return; }
    setUnlocked(true);
    setChecking(false);
    checkShopPassword(stored).catch((err) => {
      if (err?.response?.status === 401) { localStorage.removeItem("shopsPassword"); setUnlocked(false); }
    });
  }, []);

  async function submitPw(e: React.FormEvent) {
    e.preventDefault();
    setPwError("");
    try {
      await checkShopPassword(pw.trim());
      localStorage.setItem("shopsPassword", pw.trim());
      setUnlocked(true);
    } catch { setPwError("Wrong password."); }
  }

  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;

  if (!unlocked) {
    return (
      <div className="app" style={{ paddingTop: 60, maxWidth: 440 }}>
        <h1>🔒 Deals Dashboard</h1>
        <p className="subtitle">This is private. Enter the password to continue.</p>
        <form onSubmit={submitPw} style={{ marginTop: 24 }}>
          <div className="form-group">
            <input type="password" placeholder="Password" value={pw} onChange={e => setPw(e.target.value)} autoFocus />
          </div>
          {pwError && <div className="error-msg">{pwError}</div>}
          <button className="btn" type="submit" style={{ width: "100%", marginTop: 8 }}>Enter →</button>
        </form>
      </div>
    );
  }

  return <Dashboard />;
}
