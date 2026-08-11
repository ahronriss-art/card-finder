import { useCallback, useEffect, useMemo, useState } from "react";
import { checkShopPassword, getShopsPassword, clearShopsPassword, listCallerDeals,
         addCallerDeal, editCallerDeal, deleteCallerDeal, type CallerDeal } from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";

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

  const reload = useCallback(() => {
    listCallerDeals().then(setDeals).catch(() => {}).finally(() => setLoading(false));
  }, []);
  useEffect(() => { reload(); }, [reload]);

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
      {/* The full ledger sits under the dashboard: stats first, then every
          individual deal for searching, correcting and exporting. */}
      <Ledger deals={deals} reload={reload} />
    </div>
  );
}


const todayISO = () => new Date().toISOString().slice(0, 10);

/** Every deal, searchable and editable. The dashboard above answers "how are we
 *  doing"; this answers "what exactly did we do, and fix it if it's wrong". */
function Ledger({ deals, reload }: { deals: CallerDeal[]; reload: () => void }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<"all" | "buy" | "sell" | "untagged">("all");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [form, setForm] = useState({ caller: "", desc: "", amount: "", kind: "" as "" | "buy" | "sell", date: todayISO() });

  const shown = useMemo(() => {
    const term = q.trim().toLowerCase();
    return deals.filter(d => {
      if (kind === "untagged" ? d.kind : kind !== "all" && d.kind !== kind) return false;
      if (!term) return true;
      return `${d.caller_name} ${d.description}`.toLowerCase().includes(term);
    });
  }, [deals, q, kind]);

  const shownTotal = shown.reduce((n, d) => n + (d.amount || 0), 0);

  async function save() {
    if (!form.caller.trim() || !form.desc.trim()) { setErr("Who, and what for?"); return; }
    setBusy(true); setErr("");
    try {
      const amt = form.amount ? parseFloat(form.amount) : undefined;
      if (editing) {
        await editCallerDeal(editing, { callerName: form.caller, description: form.desc,
          amount: amt ?? null, kind: form.kind, occurredAt: form.date });
      } else {
        await addCallerDeal(form.caller.trim(), form.desc.trim(), amt,
                            form.kind || undefined, form.date);
      }
      setForm({ caller: "", desc: "", amount: "", kind: "", date: todayISO() });
      setEditing(null);
      reload();
    } catch { setErr("Couldn't save that deal."); }
    finally { setBusy(false); }
  }

  async function remove(d: CallerDeal) {
    if (!window.confirm(`Delete "${d.description}" with ${d.caller_name}?`)) return;
    try { await deleteCallerDeal(d.id); reload(); } catch { setErr("Couldn't delete."); }
  }

  function startEdit(d: CallerDeal) {
    setEditing(d.id);
    setForm({ caller: d.caller_name, desc: d.description,
              amount: d.amount != null ? String(d.amount) : "",
              kind: (d.kind as any) || "", date: (d.created_at || "").slice(0, 10) || todayISO() });
  }

  function exportCsv() {
    const rows = [["date", "caller", "description", "kind", "amount"],
      ...shown.map(d => [(d.created_at || "").slice(0, 10), d.caller_name, d.description,
                         d.kind || "", d.amount != null ? String(d.amount) : ""])];
    const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `deals-${todayISO()}.csv`;
    a.click();
  }

  const inputStyle = { padding: 9, borderRadius: 8, background: "rgba(255,255,255,0.05)",
                       color: "inherit", border: "1px solid rgba(255,255,255,0.15)" } as const;

  return (
    <div className="add-alert-box" style={{ marginTop: 18, padding: 18 }}>
      <div className="add-alert-title" style={{ marginBottom: 10 }}>
        {editing ? "Edit deal" : "Log a deal"}
      </div>
      {err && <div className="error-box" style={{ marginBottom: 10 }}>{err}</div>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <input placeholder="Who" value={form.caller} style={{ ...inputStyle, flex: "1 1 140px" }}
          onChange={e => setForm(f => ({ ...f, caller: e.target.value }))} />
        <input placeholder="What (e.g. Curry MIT /5)" value={form.desc}
          style={{ ...inputStyle, flex: "2 1 220px" }}
          onChange={e => setForm(f => ({ ...f, desc: e.target.value }))} />
        <input placeholder="$" type="number" value={form.amount} style={{ ...inputStyle, flex: "0 1 110px" }}
          onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} />
        <select value={form.kind} style={{ ...inputStyle, flex: "0 1 120px" }}
          onChange={e => setForm(f => ({ ...f, kind: e.target.value as any }))}>
          <option value="">untagged</option>
          <option value="buy">Bought</option>
          <option value="sell">Sold</option>
        </select>
        {/* Deals get written up after they close, so the date is editable. */}
        <input type="date" value={form.date} style={{ ...inputStyle, flex: "0 1 150px" }}
          onChange={e => setForm(f => ({ ...f, date: e.target.value }))} />
        <button className="btn btn-sm" disabled={busy} onClick={save}>
          {busy ? "Saving…" : editing ? "Save" : "Add deal"}
        </button>
        {editing && (
          <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.1)" }}
            onClick={() => { setEditing(null); setForm({ caller: "", desc: "", amount: "", kind: "", date: todayISO() }); }}>
            Cancel
          </button>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
        <input placeholder="Search deals…" value={q} style={{ ...inputStyle, flex: "1 1 200px" }}
          onChange={e => setQ(e.target.value)} />
        <select value={kind} style={{ ...inputStyle }} onChange={e => setKind(e.target.value as any)}>
          <option value="all">All</option>
          <option value="buy">Bought</option>
          <option value="sell">Sold</option>
          <option value="untagged">Untagged</option>
        </select>
        <span style={{ fontSize: 13, opacity: 0.7 }}>
          {shown.length} deal{shown.length === 1 ? "" : "s"} · {money(shownTotal)}
        </span>
        <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.1)" }}
          onClick={exportCsv}>Export CSV</button>
      </div>

      <div style={{ maxHeight: 420, overflowY: "auto" }}>
        {shown.length === 0 ? (
          <div style={{ opacity: 0.6, fontSize: 13, padding: "8px 0" }}>No deals match.</div>
        ) : shown.map((d, i) => (
          <div key={d.id} style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 13,
                padding: "7px 0", borderTop: i ? "1px solid rgba(255,255,255,0.07)" : "none" }}>
            <span style={{ opacity: 0.5, width: 62, flexShrink: 0 }}>
              {(d.created_at || "").slice(5, 10)}
            </span>
            <span style={{ width: 118, flexShrink: 0, opacity: 0.8 }}>{d.caller_name}</span>
            <span style={{ flex: 1 }}>
              {d.kind === "buy" ? "🟢 " : d.kind === "sell" ? "🔵 " : ""}{d.description}
            </span>
            <span style={{ fontWeight: 700, width: 90, textAlign: "right" }}>
              {d.amount != null ? money(d.amount) : "—"}
            </span>
            <button className="alert-edit-btn" title="Edit" onClick={() => startEdit(d)}>✎</button>
            <button className="alert-remove-btn" title="Delete" onClick={() => remove(d)}>✕</button>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function DealsPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const stored = getShopsPassword();
    if (!stored) { setChecking(false); return; }
    setUnlocked(true);
    setChecking(false);
    checkShopPassword(stored).catch((err) => {
      if (err?.response?.status === 401) { clearShopsPassword(); setUnlocked(false); }
    });
  }, []);

  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;

  if (!unlocked) {
    return <ShopPasswordForm title="Deals Dashboard" onUnlocked={() => setUnlocked(true)} />;
  }

  return <Dashboard />;
}
