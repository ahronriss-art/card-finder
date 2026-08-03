// V File — the day's batch of contact cards, collected while working the shop
// lists and sent out at end of day as ONE .vcf that a phone imports in a single
// tap (rather than texting thirty cards one at a time).
import { useEffect, useState } from "react";
import {
  getVFile, removeFromVFile, clearVFile, textVFile, downloadVFile, restoreVFile, localDay,
  getShopsPassword, type VFileCard,
} from "./api/client";
import { contactDisplayName } from "./ContactCard";
import ShopPasswordForm from "./ShopPasswordForm";

const MY_PHONE_KEY = "myContactPhone";

const SOURCE_LABEL: Record<string, string> = {
  main: "Shops", tcg: "TCG Shops", master: "New Shops",
};

function prettyDay(d: string): string {
  if (d === localDay()) return "Today";
  const y = new Date(); y.setDate(y.getDate() - 1);
  if (d === localDay(y)) return "Yesterday";
  const [Y, M, D] = d.split("-").map(Number);
  return new Date(Y, M - 1, D).toLocaleDateString(undefined,
    { weekday: "short", month: "short", day: "numeric" });
}

export default function VFilePage() {
  const [authed, setAuthed] = useState(!!getShopsPassword());
  const [day, setDay] = useState(localDay());
  const [cards, setCards] = useState<VFileCard[]>([]);
  const [days, setDays] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [phone, setPhone] = useState(localStorage.getItem(MY_PHONE_KEY) || "");
  const [sending, setSending] = useState(false);
  const [msg, setMsg] = useState("");
  const [recoverable, setRecoverable] = useState(0);

  async function load(d = day) {
    setLoading(true); setErr("");
    try {
      const r = await getVFile(d);
      setCards(r.cards);
      setRecoverable(r.recoverable || 0);
      // always offer today, even before anything is filed to it
      setDays([...new Set([localDay(), ...r.days])].sort().reverse());
    } catch (e: any) {
      setErr(e?.response?.status === 401 ? "Wrong password." : "Couldn't load the V File.");
    } finally { setLoading(false); }
  }

  useEffect(() => { if (authed) load(day); /* eslint-disable-next-line */ }, [authed, day]);

  if (!authed) return <ShopPasswordForm title="V File" subtitle="This directory is private. Enter the password to continue." onUnlocked={() => setAuthed(true)} />;

  async function remove(c: VFileCard) {
    setCards(cs => cs.filter(x => x.id !== c.id));   // optimistic
    setRecoverable(n => n + 1);
    try { await removeFromVFile(c.id); } catch { load(); }
  }

  async function undo() {
    try {
      const r = await restoreVFile(day);
      setMsg(`Restored ${r.restored} card${r.restored === 1 ? "" : "s"} ✓`);
      await load(day);
    } catch { setMsg("Couldn't restore."); }
  }

  async function clearDay() {
    if (!confirm(`Remove all ${cards.length} card${cards.length === 1 ? "" : "s"} from ${prettyDay(day)}?`)) return;
    try {
      const r = await clearVFile(day);
      setCards([]); setRecoverable(n => n + r.cleared);
      setMsg(`Cleared ${r.cleared} — you can still undo this.`);
    } catch { setMsg("Couldn't clear the file."); }
  }

  async function sendIt() {
    const to = phone.trim();
    if (!to) { setMsg("Enter a phone number first."); return; }
    setSending(true); setMsg("");
    localStorage.setItem(MY_PHONE_KEY, to);
    try {
      const r = await textVFile(to, day);
      setMsg(`Sent ${r.sent} card${r.sent === 1 ? "" : "s"} ✓ — open the text and tap the file to save them all.`);
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || "Couldn't send the file.");
    } finally { setSending(false); }
  }

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ marginBottom: 4 }}>📁 V File</h1>
          <p className="subtitle" style={{ marginTop: 0 }}>
            Contact cards you've filed today. Send the whole day as one file — the
            phone saves every shop in a single tap.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={day} onChange={e => setDay(e.target.value)}
            style={{ padding: "7px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit" }}>
            {days.map(d => <option key={d} value={d}>{prettyDay(d)} · {d}</option>)}
          </select>
          <button className="btn btn-sm" onClick={() => load()}>⟳</button>
        </div>
      </div>

      {err && <div style={{ color: "#fbbf24", marginBottom: 10 }}>{err}</div>}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", margin: "14px 0" }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>
          {cards.length} card{cards.length === 1 ? "" : "s"}
        </span>
        <button className="btn btn-sm" disabled={!cards.length}
          onClick={() => downloadVFile(day)}>⬇ Download .vcf</button>
        <button className="btn btn-sm btn-danger" disabled={!cards.length}
          onClick={clearDay}>Clear day</button>
        {recoverable > 0 && (
          <button className="btn btn-sm" onClick={undo}
            title="Bring back everything removed from this day">
            ↩ Undo — restore {recoverable} removed
          </button>
        )}
      </div>

      <div style={{ padding: 12, borderRadius: 10, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)", marginBottom: 18 }}>
        <div className="shop-field-label" style={{ marginBottom: 6 }}>📲 Text this file to a number</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input type="tel" placeholder="Phone number" value={phone}
            onChange={e => setPhone(e.target.value)}
            style={{ flex: 1, minWidth: 180, padding: "8px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit" }} />
          <button className="btn btn-sm" onClick={sendIt} disabled={sending || !cards.length || !phone.trim()}>
            {sending ? "Sending…" : `Send ${cards.length || ""} card${cards.length === 1 ? "" : "s"}`}
          </button>
        </div>
        {msg && <div style={{ fontSize: 12, marginTop: 6, color: msg.includes("✓") ? "#34d399" : "#fbbf24" }}>{msg}</div>}
      </div>

      {loading ? <p className="subtitle">Loading…</p>
        : !cards.length ? (
          <p className="subtitle">
            Nothing filed for {prettyDay(day).toLowerCase()} yet. Open a shop on the
            Shops, TCG Shops or New Shops list and hit <b>📁 V File</b> on its contact card.
          </p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {cards.map(c => (
              <div key={c.id} style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", padding: "10px 12px", borderRadius: 9, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)" }}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600 }}>
                    {contactDisplayName({ store: c.store, owner: c.owner, name: c.name, state: c.state })}
                  </div>
                  <div style={{ fontSize: 13, color: "rgba(255,255,255,0.55)", display: "flex", gap: 10, flexWrap: "wrap", marginTop: 2 }}>
                    {c.number && <span>{c.number}</span>}
                    {c.email && <span>{c.email}</span>}
                    {c.ig && <span>{c.ig}</span>}
                    {c.city && <span>{c.city}{c.state ? `, ${c.state}` : ""}</span>}
                    {c.source && <span style={{ opacity: 0.7 }}>· {SOURCE_LABEL[c.source] || c.source}</span>}
                  </div>
                </div>
                <button className="btn btn-sm" title="Remove from this day's file"
                  style={{ background: "rgba(255,255,255,0.1)", boxShadow: "none", flex: "none" }}
                  onClick={() => remove(c)}>✕</button>
              </div>
            ))}
          </div>
        )}
    </div>
  );
}
