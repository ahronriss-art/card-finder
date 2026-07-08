import { useEffect, useState } from "react";
import { checkShopPassword, getShopsPassword, clearShopsPassword, getDashboard, type Dashboard } from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";

const money = (n: number) => `$${Math.round(n).toLocaleString()}`;
function ago(iso: string | null) {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 60) return `${Math.max(1, mins)}m ago`;
  if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / 1440)}d ago`;
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ background: "#211d3f", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 14, padding: "16px 18px", color: "#e2e8f0" }}>
      <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.4, textTransform: "uppercase", color: "#94a3b8", marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  );
}
function Stat({ label, value, sub, color }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: 26, fontWeight: 800, color: color || "#f1f5f9", lineHeight: 1.1 }}>{value}</div>
      <div style={{ fontSize: 12.5, color: "#cbd5e1", marginTop: 2 }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 1 }}>{sub}</div>}
    </div>
  );
}

function Board() {
  const [d, setD] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  async function load() {
    setLoading(true); setError("");
    try { setD(await getDashboard()); }
    catch { setError("Couldn't load the dashboard."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  if (loading && !d) return <div className="app" style={{ paddingTop: 40 }}><p className="subtitle">Loading dashboard…</p></div>;
  if (error) return <div className="app" style={{ paddingTop: 40 }}><div className="error-msg">{error}</div></div>;
  if (!d) return null;

  const pnlColor = d.portfolio.pnl >= 0 ? "#4ade80" : "#f87171";
  const grid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14 };

  return (
    <div className="app" style={{ paddingTop: 28, paddingBottom: 48, maxWidth: 900 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
        <h1 style={{ marginBottom: 2 }}>📊 Dashboard</h1>
        <button className="btn btn-sm" type="button" onClick={load} disabled={loading}
          style={{ background: "rgba(255,255,255,0.1)" }}>{loading ? "…" : "↻ Refresh"}</button>
      </div>
      <p className="subtitle" style={{ marginTop: 2 }}>Your operation at a glance · updated {ago(d.as_of)}</p>

      <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 16 }}>
        <Card title="🔔 Alerts & Finds">
          <div style={grid}>
            <Stat label="active searches" value={d.searches.active} sub={`${d.searches.total} total`} />
            <Stat label="cards found (all time)" value={d.alerts.total.toLocaleString()} />
            <Stat label="found this week" value={d.alerts.last_7d} color="#60a5fa" />
          </div>
        </Card>

        <Card title="📣 Broadcasts">
          <div style={grid}>
            <Stat label="blasts sent" value={d.broadcasts.blasts} sub={`last ${ago(d.broadcasts.last_at)}`} />
            <Stat label="texts delivered" value={d.broadcasts.recipients_total.toLocaleString()} />
            <Stat label="scheduled pending" value={d.broadcasts.scheduled_pending} color={d.broadcasts.scheduled_pending ? "#c084fc" : undefined} />
          </div>
        </Card>

        <Card title="💬 Inbox & Replies">
          <div style={grid}>
            <Stat label="conversations" value={d.inbox.conversations} />
            <Stat label="unread" value={d.inbox.unread} color={d.inbox.unread ? "#f87171" : undefined} />
            <Stat label="replies (this week)" value={d.inbox.replies} sub={`${d.inbox.replies_7d} in last 7d`} />
            <Stat label="reply rate" value={d.inbox.reply_rate_pct == null ? "—" : `${d.inbox.reply_rate_pct}%`} color="#4ade80" />
          </div>
        </Card>

        <Card title="👥 Audience">
          <div style={grid}>
            <Stat label="broadcast groups" value={d.audience.groups} />
            <Stat label="saved numbers" value={d.audience.contacts} />
            <Stat label="named" value={d.audience.named} sub={`${d.audience.contacts - d.audience.named} unnamed`} />
          </div>
        </Card>

        <Card title="💰 Deals (Caller Notes)">
          <div style={grid}>
            <Stat label="callers logged" value={d.deals.callers} />
            <Stat label="deals logged" value={d.deals.logged} />
            <Stat label="bought" value={money(d.deals.bought)} color="#4ade80" />
            <Stat label="sold" value={money(d.deals.sold)} color="#60a5fa" />
          </div>
        </Card>

        <Card title="📈 Portfolio">
          <div style={grid}>
            <Stat label="cards held" value={d.portfolio.cards} />
            <Stat label="market value" value={money(d.portfolio.market_value)} />
            <Stat label="cost basis" value={money(d.portfolio.cost)} />
            <Stat label="unrealized P&L" value={`${d.portfolio.pnl >= 0 ? "+" : "−"}${money(Math.abs(d.portfolio.pnl))}`} color={pnlColor} />
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function DashboardPage() {
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
  if (!unlocked) return <ShopPasswordForm title="Dashboard" onUnlocked={() => setUnlocked(true)} />;
  return <Board />;
}
