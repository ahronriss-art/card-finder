import { useEffect, useMemo, useState } from "react";
import {
  getPnl, createPnlCard, updatePnlCard, deletePnlCard, getPnlContacts,
  type PnlCard, type PnlStats, type PnlContact,
} from "./api/client";

const money = (n?: number | null) =>
  n == null ? "—" : `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

const SPORTS = ["Basketball", "Baseball", "Football", "Hockey", "Soccer", "Pokemon", "Other"];
const GRADERS = ["PSA", "BGS", "SGC", "CGC", "TAG"];
const STATUSES: { key: PnlCard["status"]; label: string }[] = [
  { key: "in_hand", label: "In hand" },
  { key: "grading", label: "Grading" },
  { key: "sold", label: "Sold" },
];

// Empty draft for the add/edit form. Numbers stay as strings while typing so a
// half-typed "12." doesn't get coerced to something else under the user.
type Draft = Record<string, string>;
const EMPTY: Draft = {
  name: "", sport: "", brand: "", status: "in_hand", grader: "", grade: "", grade_fee: "",
  base_cost: "", platform: "", tax: "", shipping: "", date_purchased: "", date_sold: "",
  sold_price: "", notes: "",
  bought_from_name: "", bought_from_phone: "", bought_from_email: "", bought_from_website: "",
  sold_to_name: "", sold_to_phone: "", sold_to_email: "", sold_to_website: "",
};

function toDraft(c: PnlCard): Draft {
  const s = (v: any) => (v == null ? "" : String(v));
  return {
    name: s(c.name), sport: s(c.sport), brand: s(c.brand), status: c.status,
    grader: s(c.grader), grade: s(c.grade), grade_fee: s(c.grade_fee),
    base_cost: s(c.base_cost), platform: s(c.platform), tax: s(c.tax), shipping: s(c.shipping),
    date_purchased: s(c.date_purchased), date_sold: s(c.date_sold), sold_price: s(c.sold_price),
    notes: s(c.notes),
    bought_from_name: s(c.bought_from_name), bought_from_phone: s(c.bought_from_phone),
    bought_from_email: s(c.bought_from_email), bought_from_website: s(c.bought_from_website),
    sold_to_name: s(c.sold_to_name), sold_to_phone: s(c.sold_to_phone),
    sold_to_email: s(c.sold_to_email), sold_to_website: s(c.sold_to_website),
  };
}

function toPayload(d: Draft): Partial<PnlCard> {
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const str = (v: string) => (v.trim() === "" ? null : v.trim());
  return {
    name: d.name.trim(), sport: str(d.sport), brand: str(d.brand),
    status: d.status as PnlCard["status"], grader: str(d.grader), grade: str(d.grade),
    grade_fee: num(d.grade_fee), base_cost: num(d.base_cost), platform: str(d.platform),
    tax: num(d.tax), shipping: num(d.shipping), date_purchased: str(d.date_purchased),
    date_sold: str(d.date_sold), sold_price: num(d.sold_price), notes: str(d.notes),
    bought_from_name: str(d.bought_from_name), bought_from_phone: str(d.bought_from_phone),
    bought_from_email: str(d.bought_from_email), bought_from_website: str(d.bought_from_website),
    sold_to_name: str(d.sold_to_name), sold_to_phone: str(d.sold_to_phone),
    sold_to_email: str(d.sold_to_email), sold_to_website: str(d.sold_to_website),
  };
}

function StatTile({ label, value, sub, tone }: {
  label: string; value: string; sub?: string; tone?: "profit" | "loss" | "gem" | "plain";
}) {
  const color = tone === "profit" ? "#2563eb" : tone === "loss" ? "#b91c1c"
    : tone === "gem" ? "#15803d" : undefined;
  return (
    <div style={{
      flex: "1 1 180px", minWidth: 170, borderRadius: 12, padding: "14px 16px",
      background: tone === "gem" ? "rgba(21,128,61,0.10)" : "rgba(148,163,184,0.10)",
      borderTop: `3px solid ${color || "#94a3b8"}`,
    }}>
      <div style={{ fontSize: 11, letterSpacing: 1, color: "#64748b", fontFamily: "monospace" }}>
        // {label}
      </div>
      <div style={{ fontSize: 30, fontWeight: 800, color, lineHeight: 1.25 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: "#64748b", fontFamily: "monospace" }}>{sub}</div>}
    </div>
  );
}

// Add / edit form. Mirrors the sections of the tracker: what the card is, what
// grading cost, what it cost to get, when it moved, what it sold for, and who
// was on each side.
function CardForm({ initial, busy, submitLabel, onSubmit, onCancel }: {
  initial: Draft; busy: boolean; submitLabel: string;
  onSubmit: (d: Draft) => void; onCancel: () => void;
}) {
  const [d, setD] = useState<Draft>(initial);
  const set = (k: string) => (e: any) => setD(p => ({ ...p, [k]: e.target.value }));

  // Same rule the server enforces: a sale price plus a sale date means sold.
  const autoSold = !!d.sold_price.trim() && !!d.date_sold.trim();
  const totalCost = ["base_cost", "tax", "shipping", "grade_fee"]
    .reduce((sum, k) => sum + (Number(d[k]) || 0), 0);
  const net = autoSold || d.status === "sold" ? (Number(d.sold_price) || 0) - totalCost : null;

  const L = ({ children }: { children: any }) =>
    <span style={{ fontSize: 12, color: "#64748b", display: "block", marginBottom: 3 }}>{children}</span>;
  const Section = ({ children }: { children: any }) => (
    <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1, color: "#475569",
      borderLeft: "3px solid #2563eb", paddingLeft: 8, margin: "16px 0 10px" }}>{children}</div>
  );
  const row = { display: "flex", gap: 12, flexWrap: "wrap" as const, marginBottom: 4 };
  const cell = { flex: "1 1 160px", minWidth: 150, marginBottom: 8 };

  return (
    <form onSubmit={e => { e.preventDefault(); if (d.name.trim()) onSubmit(d); }}>
      <Section>CARD BASICS</Section>
      <div style={cell}>
        <L>Card name *</L>
        <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.name} onChange={set("name")}
          placeholder="e.g. 2023 Bowman Chrome Sapphire Ronald Acuna Jr" />
      </div>
      <div style={row}>
        <label style={cell}>
          <L>Sport</L>
          <select className="add-alert-input" style={{ marginBottom: 0 }} value={d.sport} onChange={set("sport")}>
            <option value="">Select</option>
            {SPORTS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label style={cell}>
          <L>Type / Brand</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.brand} onChange={set("brand")}
            placeholder="e.g. Bowman Chrome, Panini Prizm" />
        </label>
      </div>

      <Section>GRADING</Section>
      <div style={row}>
        <label style={cell}>
          <L>Card status</L>
          <select className="add-alert-input" style={{ marginBottom: 0 }}
            value={autoSold ? "sold" : d.status} onChange={set("status")} disabled={autoSold}>
            {STATUSES.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          <span style={{ fontSize: 11, color: "#64748b" }}>
            Marked Sold automatically once a sale price and date are set.
          </span>
        </label>
        <label style={cell}>
          <L>Grader</L>
          <select className="add-alert-input" style={{ marginBottom: 0 }} value={d.grader} onChange={set("grader")}>
            <option value="">Select</option>
            {GRADERS.map(g => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        <label style={cell}>
          <L>Grade</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.grade} onChange={set("grade")}
            placeholder="10, 9.5" />
        </label>
        <label style={cell}>
          <L>Grade fee ($)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} inputMode="decimal"
            value={d.grade_fee} onChange={set("grade_fee")} placeholder="0.00" />
        </label>
      </div>

      <Section>COSTS</Section>
      <div style={row}>
        <label style={cell}>
          <L>Base cost ($)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} inputMode="decimal"
            value={d.base_cost} onChange={set("base_cost")} placeholder="0.00" />
        </label>
        <label style={cell}>
          <L>Platform</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.platform} onChange={set("platform")}
            placeholder="eBay, Person, Store" />
        </label>
        <label style={cell}>
          <L>Tax ($)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} inputMode="decimal"
            value={d.tax} onChange={set("tax")} placeholder="0.00" />
        </label>
        <label style={cell}>
          <L>Shipping ($)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} inputMode="decimal"
            value={d.shipping} onChange={set("shipping")} placeholder="0.00" />
        </label>
      </div>

      <Section>DATES</Section>
      <div style={row}>
        <label style={cell}>
          <L>Date purchased</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} type="date"
            value={d.date_purchased} onChange={set("date_purchased")} />
        </label>
        <label style={cell}>
          <L>Date sold</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} type="date"
            value={d.date_sold} onChange={set("date_sold")} />
        </label>
      </div>

      <Section>SALE</Section>
      <div style={row}>
        <label style={cell}>
          <L>Sold price ($)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} inputMode="decimal"
            value={d.sold_price} onChange={set("sold_price")} placeholder="0.00" />
        </label>
        <div style={{ ...cell, alignSelf: "flex-end", fontSize: 13 }}>
          Total cost <strong>{money(totalCost)}</strong>
          {net != null && <> · Net return <strong style={{ color: net >= 0 ? "#15803d" : "#b91c1c" }}>{money(net)}</strong></>}
        </div>
      </div>

      <Section>NOTES</Section>
      <textarea className="add-alert-input" rows={2} value={d.notes} onChange={set("notes")}
        placeholder="Anything worth remembering about this card (who you bought it from, condition details, plans for it…)" />

      <Section>WHO'D YOU BUY FROM?</Section>
      <div style={row}>
        <label style={cell}><L>Name</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.bought_from_name}
            onChange={set("bought_from_name")} placeholder="Seller name" /></label>
        <label style={cell}><L>Phone (optional)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.bought_from_phone}
            onChange={set("bought_from_phone")} placeholder="+1 555 …" /></label>
        <label style={cell}><L>Email (optional)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.bought_from_email}
            onChange={set("bought_from_email")} placeholder="seller@example.com" /></label>
        <label style={cell}><L>Website (optional)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.bought_from_website}
            onChange={set("bought_from_website")} placeholder="https://" /></label>
      </div>

      <Section>WHO'D YOU SELL TO?</Section>
      <div style={row}>
        <label style={cell}><L>Name</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.sold_to_name}
            onChange={set("sold_to_name")} placeholder="Buyer name" /></label>
        <label style={cell}><L>Phone (optional)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.sold_to_phone}
            onChange={set("sold_to_phone")} placeholder="+1 555 …" /></label>
        <label style={cell}><L>Email (optional)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.sold_to_email}
            onChange={set("sold_to_email")} placeholder="buyer@example.com" /></label>
        <label style={cell}><L>Website (optional)</L>
          <input className="add-alert-input" style={{ marginBottom: 0 }} value={d.sold_to_website}
            onChange={set("sold_to_website")} placeholder="https://" /></label>
      </div>

      <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
        <button className="btn btn-sm" type="submit" disabled={busy || !d.name.trim()}>
          {busy ? "Saving…" : submitLabel}
        </button>
        <button className="btn btn-sm" type="button" style={{ background: "rgba(255,255,255,0.1)" }}
          onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

export default function PnlPage() {
  const [tab, setTab] = useState<"ledger" | "contacts">("ledger");
  const [cards, setCards] = useState<PnlCard[]>([]);
  const [stats, setStats] = useState<PnlStats | null>(null);
  const [contacts, setContacts] = useState<PnlContact[]>([]);
  const [contactSide, setContactSide] = useState<"all" | "bought_from" | "sold_to">("all");
  const [statusFilter, setStatusFilter] = useState<"" | PnlCard["status"]>("");
  const [sportFilter, setSportFilter] = useState("");
  const [minCost, setMinCost] = useState("");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<PnlCard | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    try {
      const [d, c] = await Promise.all([getPnl(), getPnlContacts()]);
      setCards(d.cards); setStats(d.stats); setContacts(c.contacts);
    } catch (e: any) {
      setErr(e?.response?.status === 401 ? "Sign in on the Alerts tab to use the P&L Tracker."
        : "Couldn't load your P&L.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { load(); }, []);

  async function save(d: Draft) {
    setBusy(true); setErr("");
    try {
      if (editing) await updatePnlCard(editing.id, toPayload(d));
      else await createPnlCard(toPayload(d));
      setAdding(false); setEditing(null);
      await load();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "Couldn't save that card.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(c: PnlCard) {
    if (!confirm(`Remove “${c.name}” from your P&L?`)) return;
    try { await deletePnlCard(c.id); await load(); }
    catch { setErr("Couldn't remove that card."); }
  }

  const visible = useMemo(() => cards.filter(c =>
    (!statusFilter || c.status === statusFilter) &&
    (!sportFilter || (c.sport || "") === sportFilter) &&
    (!minCost || c.total_cost >= Number(minCost))
  ), [cards, statusFilter, sportFilter, minCost]);

  const visibleContacts = contacts.filter(p =>
    contactSide === "all" || (contactSide === "bought_from" ? p.bought_from > 0 : p.sold_to > 0));

  const chip = (active: boolean) => ({
    padding: "5px 14px", borderRadius: 999, fontSize: 13, cursor: "pointer",
    border: `1px solid ${active ? "#2563eb" : "rgba(148,163,184,0.5)"}`,
    background: active ? "rgba(37,99,235,0.12)" : "transparent",
    fontWeight: active ? 700 : 400,
  });

  return (
    <div style={{ maxWidth: 1100, margin: "24px auto", padding: "0 16px" }}>
      <div style={{ fontSize: 11, letterSpacing: 2, color: "#94a3b8", fontFamily: "monospace" }}>
        OPERATOR LEDGER
      </div>
      <h1 style={{ fontSize: 30, margin: "2px 0 4px" }}>P&amp;L Tracker</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Every flip and your buyer/seller contacts in one place.
      </p>

      <div style={{ display: "flex", gap: 18, borderBottom: "1px solid rgba(148,163,184,0.35)", marginBottom: 16 }}>
        {([["ledger", "P&L Tracker"], ["contacts", "My Contacts"]] as const).map(([k, label]) => (
          <button key={k} type="button" onClick={() => setTab(k)}
            style={{
              background: "none", border: "none", cursor: "pointer", fontSize: 15, padding: "8px 2px",
              fontWeight: tab === k ? 700 : 400, color: tab === k ? "#2563eb" : "#64748b",
              borderBottom: `2px solid ${tab === k ? "#2563eb" : "transparent"}`,
            }}>
            {label}
          </button>
        ))}
      </div>

      {err && <div style={{ color: "#b91c1c", fontSize: 13, marginBottom: 10 }}>{err}</div>}
      {loading && <div style={{ color: "#64748b" }}>Loading…</div>}

      {tab === "ledger" && !loading && (
        <>
          {stats && (
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
              <StatTile label="TOTAL SPEND" value={money(stats.total_spend)}
                sub={`${stats.cards_sold + stats.cards_in_hand} CARDS LOGGED`} />
              <StatTile label="NET PROFIT" value={money(stats.net_profit)}
                sub={stats.roi_pct != null ? `${stats.roi_pct}% ROI` : "NO SPEND YET"}
                tone={stats.net_profit >= 0 ? "profit" : "loss"} />
              <StatTile label="INVENTORY VALUE" value={money(stats.inventory_value)}
                sub={`${stats.cards_in_hand} CARD${stats.cards_in_hand === 1 ? "" : "S"} IN HAND`} />
              <StatTile label="GEM RATE"
                value={stats.gem_rate_pct != null ? `${stats.gem_rate_pct}%` : "—"}
                sub={stats.graded ? `${stats.gems} OF ${stats.graded} GRADED EARNED A 10` : "NOTHING GRADED YET"}
                tone="gem" />
            </div>
          )}

          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
            <div style={{ display: "flex", gap: 8 }}>
              <span style={chip(statusFilter === "")} onClick={() => setStatusFilter("")}>All</span>
              {STATUSES.map(s => (
                <span key={s.key} style={chip(statusFilter === s.key)}
                  onClick={() => setStatusFilter(s.key)}>{s.label}</span>
              ))}
            </div>
            <select className="add-alert-input" style={{ marginBottom: 0, width: 140 }}
              value={sportFilter} onChange={e => setSportFilter(e.target.value)}>
              <option value="">All sports</option>
              {SPORTS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <select className="add-alert-input" style={{ marginBottom: 0, width: 150 }}
              value={minCost} onChange={e => setMinCost(e.target.value)}>
              <option value="">Any cost</option>
              <option value="100">$100+</option>
              <option value="500">$500+</option>
              <option value="1000">$1,000+</option>
              <option value="5000">$5,000+</option>
            </select>
            <div style={{ flex: 1 }} />
            <button className="btn btn-sm" type="button"
              onClick={() => { setEditing(null); setAdding(a => !a); }}>
              + Add card
            </button>
          </div>

          {adding && (
            <div className="add-alert-box" style={{ marginBottom: 16 }}>
              <div className="add-alert-title">🏆 Add card to P&amp;L</div>
              <CardForm initial={EMPTY} busy={busy} submitLabel="Add card"
                onSubmit={save} onCancel={() => setAdding(false)} />
            </div>
          )}

          {visible.length === 0 ? (
            <div style={{ color: "#64748b", padding: "18px 0" }}>
              {cards.length ? "No cards match those filters." : "No cards logged yet — add your first flip."}
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ textAlign: "left", color: "#64748b", fontSize: 12 }}>
                    <th style={{ padding: "8px 6px" }}>Card</th>
                    <th style={{ padding: "8px 6px" }}>Sport</th>
                    <th style={{ padding: "8px 6px" }}>Brand</th>
                    <th style={{ padding: "8px 6px" }}>Grade</th>
                    <th style={{ padding: "8px 6px", textAlign: "right" }}>Total cost</th>
                    <th style={{ padding: "8px 6px", textAlign: "right" }}>Sold price</th>
                    <th style={{ padding: "8px 6px", textAlign: "right" }}>Net return</th>
                    <th style={{ padding: "8px 6px" }}>Status</th>
                    <th style={{ padding: "8px 6px" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map(c => (
                    <tr key={c.id} style={{ borderTop: "1px solid rgba(148,163,184,0.3)" }}>
                      <td style={{ padding: "8px 6px", fontWeight: 600 }}>{c.name}</td>
                      <td style={{ padding: "8px 6px" }}>{c.sport || "—"}</td>
                      <td style={{ padding: "8px 6px" }}>{c.brand || "—"}</td>
                      <td style={{ padding: "8px 6px" }}>
                        {c.grade ? `${c.grader || ""} ${c.grade}`.trim() : "—"}
                      </td>
                      <td style={{ padding: "8px 6px", textAlign: "right" }}>{money(c.total_cost)}</td>
                      <td style={{ padding: "8px 6px", textAlign: "right" }}>{money(c.sold_price)}</td>
                      <td style={{
                        padding: "8px 6px", textAlign: "right", fontWeight: 700,
                        color: c.net_return == null ? undefined : c.net_return >= 0 ? "#15803d" : "#b91c1c",
                      }}>{c.net_return == null ? "—" : money(c.net_return)}</td>
                      <td style={{ padding: "8px 6px", fontFamily: "monospace", fontSize: 11, color: "#64748b" }}>
                        {(STATUSES.find(s => s.key === c.status)?.label || c.status).toUpperCase()}
                      </td>
                      <td style={{ padding: "8px 6px", whiteSpace: "nowrap" }}>
                        <button className="btn btn-sm" type="button" title="Edit"
                          style={{ background: "rgba(255,255,255,0.1)", marginRight: 6 }}
                          onClick={() => { setAdding(false); setEditing(c); }}>✏️</button>
                        <button className="btn btn-sm" type="button" title="Remove"
                          style={{ background: "rgba(185,28,28,0.15)" }}
                          onClick={() => remove(c)}>🗑</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {editing && (
            <div className="add-alert-box" style={{ marginTop: 16 }}>
              <div className="add-alert-title">Edit “{editing.name}”</div>
              <CardForm key={editing.id} initial={toDraft(editing)} busy={busy} submitLabel="Save changes"
                onSubmit={save} onCancel={() => setEditing(null)} />
            </div>
          )}
        </>
      )}

      {tab === "contacts" && !loading && (
        <>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
            <StatTile label="TOTAL CONTACTS" value={String(contacts.length)} sub="IN YOUR NETWORK" />
            <StatTile label="TOTAL DEALS" value={String(contacts.reduce((n, p) => n + p.deals, 0))}
              sub="LOGGED ACROSS CONTACTS" />
          </div>

          <div style={{ display: "flex", gap: 8, marginBottom: 14, flexWrap: "wrap" }}>
            <span style={chip(contactSide === "all")} onClick={() => setContactSide("all")}>
              ALL ({contacts.length})
            </span>
            <span style={chip(contactSide === "bought_from")} onClick={() => setContactSide("bought_from")}>
              ↙ I BOUGHT FROM ({contacts.filter(p => p.bought_from > 0).length})
            </span>
            <span style={chip(contactSide === "sold_to")} onClick={() => setContactSide("sold_to")}>
              ↗ I SOLD TO ({contacts.filter(p => p.sold_to > 0).length})
            </span>
          </div>

          {visibleContacts.length === 0 ? (
            <div style={{ color: "#64748b" }}>
              No contacts yet — they appear here as you fill in who you bought from and sold to.
            </div>
          ) : visibleContacts.map((p, i) => (
            <div key={i} style={{
              borderLeft: "3px solid #15803d", background: "rgba(148,163,184,0.08)",
              borderRadius: 8, padding: "10px 14px", marginBottom: 8,
            }}>
              <div style={{ fontWeight: 700 }}>{p.name}</div>
              <div style={{ fontSize: 13, color: "#64748b" }}>
                {[p.phone && `📞 ${p.phone}`, p.email && `✉️ ${p.email}`, p.website].filter(Boolean).join("  ·  ") || "—"}
              </div>
              <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
                {p.deals} deal{p.deals === 1 ? "" : "s"}
                {p.bought_from ? ` · bought ${p.bought_from} from them` : ""}
                {p.sold_to ? ` · sold ${p.sold_to} to them` : ""}
              </div>
              <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 2 }}>
                {p.cards.slice(0, 4).map(c => c.name).join(", ")}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
