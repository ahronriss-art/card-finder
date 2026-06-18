import { useEffect, useMemo, useState } from "react";
import {
  checkShopPassword, listCallerNotes, addCallerNote, deleteCallerNote, updateCallerNote,
  listCallerDeals, addCallerDeal, deleteCallerDeal,
  listCallerWants, addCallerWant, deleteCallerWant,
  type CallerNote, type CallerDeal, type CallerWant,
} from "./api/client";

function fmtDate(iso: string) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function igUrl(h: string) { return `https://instagram.com/${h.replace(/^@/, "").trim()}`; }

function NotesBoard() {
  const [notes, setNotes] = useState<CallerNote[]>([]);
  const [deals, setDeals] = useState<CallerDeal[]>([]);
  const [wants, setWants] = useState<CallerWant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  // add-note form
  const [caller, setCaller] = useState("");
  const [phone, setPhone] = useState("");
  const [instagram, setInstagram] = useState("");
  const [facebook, setFacebook] = useState("");
  const [email, setEmail] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  // inline note edit
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  // per-caller "add deal" inputs
  const [dealInputs, setDealInputs] = useState<Record<string, { desc: string; amt: string; kind: "" | "buy" | "sell" }>>({});
  const di = (name: string) => dealInputs[name] || { desc: "", amt: "", kind: "" as const };
  const setDI = (name: string, patch: Partial<{ desc: string; amt: string; kind: "" | "buy" | "sell" }>) =>
    setDealInputs(p => ({ ...p, [name]: { ...di(name), ...patch } }));

  // per-caller "add want" inputs
  const [wantInputs, setWantInputs] = useState<Record<string, { q: string; max: string }>>({});
  const wi = (name: string) => wantInputs[name] || { q: "", max: "" };
  const setWI = (name: string, patch: Partial<{ q: string; max: string }>) =>
    setWantInputs(p => ({ ...p, [name]: { ...wi(name), ...patch } }));

  async function load() {
    try {
      const [n, d, w] = await Promise.all([listCallerNotes(), listCallerDeals(), listCallerWants()]);
      setNotes(n); setDeals(d); setWants(w);
    } catch { setError("Couldn't load caller data."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function handleAddNote(e: React.FormEvent) {
    e.preventDefault();
    if (!caller.trim() || !text.trim()) { setError("Enter a caller name and a note."); return; }
    setSaving(true); setError("");
    try {
      const created = await addCallerNote(caller.trim(), text.trim(), {
        callerPhone: phone.trim() || undefined,
        instagram: instagram.trim() || undefined,
        facebook: facebook.trim() || undefined,
        email: email.trim() || undefined,
      });
      setNotes(prev => [created, ...prev]);
      setText("");  // keep contact fields so you can log several notes for the same caller
    } catch { setError("Couldn't save the note."); }
    finally { setSaving(false); }
  }

  async function handleDeleteNote(id: number) {
    if (!confirm("Delete this note?")) return;
    try { await deleteCallerNote(id); setNotes(prev => prev.filter(n => n.id !== id)); }
    catch { setError("Couldn't delete the note."); }
  }

  function startEdit(n: CallerNote) { setEditingId(n.id); setEditText(n.note); }
  async function saveEdit(id: number) {
    if (!editText.trim()) { setError("Note can't be empty."); return; }
    try {
      const updated = await updateCallerNote(id, editText.trim());
      setNotes(prev => prev.map(n => n.id === id ? updated : n));
      setEditingId(null);
    } catch { setError("Couldn't update the note."); }
  }

  async function handleAddDeal(name: string) {
    const { desc, amt, kind } = di(name);
    if (!desc.trim()) { setError("Enter what the deal was."); return; }
    try {
      const created = await addCallerDeal(name, desc.trim(), amt ? parseFloat(amt) : undefined, kind || undefined);
      setDeals(prev => [created, ...prev]);
      setDI(name, { desc: "", amt: "", kind: "" });
    } catch { setError("Couldn't save the deal."); }
  }

  async function handleDeleteDeal(id: number) {
    if (!confirm("Delete this deal?")) return;
    try { await deleteCallerDeal(id); setDeals(prev => prev.filter(d => d.id !== id)); }
    catch { setError("Couldn't delete the deal."); }
  }

  async function handleAddWant(name: string) {
    const { q, max } = wi(name);
    if (!q.trim()) { setError("Enter what the caller is looking for."); return; }
    try {
      const created = await addCallerWant(name, q.trim(), max ? parseFloat(max) : undefined);
      setWants(prev => [created, ...prev]);
      setWI(name, { q: "", max: "" });
    } catch { setError("Couldn't save the want."); }
  }

  async function handleDeleteWant(id: number) {
    try { await deleteCallerWant(id); setWants(prev => prev.filter(w => w.id !== id)); }
    catch { setError("Couldn't delete the want."); }
  }

  const callerNames = useMemo(
    () => Array.from(new Set(notes.map(n => n.caller_name))).sort((a, b) => a.localeCompare(b)),
    [notes],
  );

  // Build per-caller view from both notes and deals.
  const groups = useMemo(() => {
    const term = filter.trim().toLowerCase();
    const names = new Set<string>([...notes.map(n => n.caller_name), ...deals.map(d => d.caller_name), ...wants.map(w => w.caller_name)]);
    const result = Array.from(names).map(name => {
      const myNotes = notes.filter(n => n.caller_name === name).sort((a, b) => b.created_at.localeCompare(a.created_at));
      const myDeals = deals.filter(d => d.caller_name === name).sort((a, b) => b.created_at.localeCompare(a.created_at));
      const myWants = wants.filter(w => w.caller_name === name).sort((a, b) => b.created_at.localeCompare(a.created_at));
      const contact = {
        phone: myNotes.map(n => n.caller_phone).find(Boolean) || "",
        instagram: myNotes.map(n => n.instagram).find(Boolean) || "",
        facebook: myNotes.map(n => n.facebook).find(Boolean) || "",
        email: myNotes.map(n => n.email).find(Boolean) || "",
      };
      const lastActivity = [myNotes[0]?.created_at, myDeals[0]?.created_at, myWants[0]?.created_at].filter(Boolean).sort().pop() || "";
      const dealTotal = myDeals.reduce((s, d) => s + (d.amount || 0), 0);
      return { name, notes: myNotes, deals: myDeals, wants: myWants, contact, lastActivity, dealTotal };
    });
    const filtered = term
      ? result.filter(g => {
          const hay = [g.name, g.contact.phone, g.contact.instagram, g.contact.facebook, g.contact.email,
            ...g.notes.map(n => n.note), ...g.deals.map(d => d.description), ...g.wants.map(w => w.query)].join(" ").toLowerCase();
          return hay.includes(term);
        })
      : result;
    return filtered.sort((a, b) => b.lastActivity.localeCompare(a.lastActivity));
  }, [notes, deals, wants, filter]);

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 760 }}>
      <h1>Caller Notes</h1>
      <p className="subtitle">Log what callers say, their contact handles, and deals you've closed — grouped by caller.</p>

      <div className="add-alert-box" style={{ marginTop: 20 }}>
        <div className="add-alert-title">+ Add a note</div>
        <form onSubmit={handleAddNote}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
            <input className="add-alert-input" list="caller-names" placeholder="Caller name"
              value={caller} onChange={e => setCaller(e.target.value)} style={{ flex: 2, minWidth: 160 }} />
            <input className="add-alert-input" placeholder="Phone"
              value={phone} onChange={e => setPhone(e.target.value)} style={{ flex: 1, minWidth: 120 }} />
            <datalist id="caller-names">{callerNames.map(n => <option key={n} value={n} />)}</datalist>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
            <input className="add-alert-input" placeholder="Instagram @handle"
              value={instagram} onChange={e => setInstagram(e.target.value)} style={{ flex: 1, minWidth: 130 }} />
            <input className="add-alert-input" placeholder="Facebook name"
              value={facebook} onChange={e => setFacebook(e.target.value)} style={{ flex: 1, minWidth: 130 }} />
            <input className="add-alert-input" placeholder="Email"
              value={email} onChange={e => setEmail(e.target.value)} style={{ flex: 1, minWidth: 130 }} />
          </div>
          <textarea className="add-alert-input" rows={3}
            placeholder="What did they say? (e.g. looking for 2003 LeBron RC, budget $5k)"
            value={text} onChange={e => setText(e.target.value)}
            style={{ width: "100%", resize: "vertical", lineHeight: 1.5 }} />
          {error && <div className="error-msg" style={{ marginTop: 8 }}>{error}</div>}
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
            <button className="btn btn-sm" type="submit" disabled={saving}>{saving ? "Saving…" : "Add note"}</button>
          </div>
        </form>
      </div>

      <div className="alert-search-wrap" style={{ marginTop: 18 }}>
        <span className="alert-search-icon">🔎</span>
        <input className="alert-search-input" type="text" placeholder="Search callers, handles, notes, deals…"
          value={filter} onChange={e => setFilter(e.target.value)} />
        {filter && <button className="alert-search-clear" onClick={() => setFilter("")} title="Clear">✕</button>}
      </div>

      {loading ? (
        <p className="subtitle" style={{ marginTop: 24 }}>Loading…</p>
      ) : groups.length === 0 ? (
        <div className="empty" style={{ marginTop: 32 }}>
          <p style={{ fontSize: 15 }}>{filter ? `No matches for "${filter}".` : "No caller notes yet. Add your first one above."}</p>
        </div>
      ) : (
        <div style={{ marginTop: 18 }}>
          {groups.map(g => (
            <div key={g.name} className="alert-folder" style={{ marginBottom: 22 }}>
              <div className="alert-folder-header" style={{ fontSize: 16, fontWeight: 700, padding: "8px 2px" }}>
                👤 {g.name}
              </div>
              {/* Contact handles */}
              {(g.contact.phone || g.contact.instagram || g.contact.facebook || g.contact.email) && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12, fontSize: 13, opacity: 0.85, padding: "0 2px 8px" }}>
                  {g.contact.phone && <span>📞 {g.contact.phone}</span>}
                  {g.contact.instagram && <span>📸 <a href={igUrl(g.contact.instagram)} target="_blank" rel="noreferrer">@{g.contact.instagram.replace(/^@/, "")}</a></span>}
                  {g.contact.facebook && <span>📘 {g.contact.facebook}</span>}
                  {g.contact.email && <span>✉️ <a href={`mailto:${g.contact.email}`}>{g.contact.email}</a></span>}
                </div>
              )}

              {/* Wants — auto-matched against eBay */}
              <div style={{ padding: "6px 2px 10px" }}>
                <div style={{ fontSize: 13, fontWeight: 600, opacity: 0.85, marginBottom: 4 }}>
                  🎯 Looking for <span style={{ opacity: 0.55, fontWeight: 400 }}>(we'll email you when one lists on eBay)</span>
                </div>
                {g.wants.map(w => (
                  <div key={w.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, padding: "2px 0" }}>
                    <span>• {w.query}{w.max_price != null ? ` — under $${w.max_price.toLocaleString()}` : ""}</span>
                    <button className="alert-remove-btn" onClick={() => handleDeleteWant(w.id)} title="Remove want" style={{ marginLeft: 8 }}>✕</button>
                  </div>
                ))}
                <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
                  <input className="add-alert-input" placeholder="Card they want (e.g. 2003 LeBron Topps Chrome)"
                    value={wi(g.name).q} onChange={e => setWI(g.name, { q: e.target.value })}
                    style={{ flex: 2, minWidth: 160 }} />
                  <input className="add-alert-input" type="number" placeholder="max $"
                    value={wi(g.name).max} onChange={e => setWI(g.name, { max: e.target.value })}
                    style={{ width: 90 }} />
                  <button className="btn btn-sm" onClick={() => handleAddWant(g.name)}>Track</button>
                </div>
              </div>

              {/* Deals closed */}
              <div style={{ padding: "6px 2px 10px" }}>
                <div style={{ fontSize: 13, fontWeight: 600, opacity: 0.85, marginBottom: 4 }}>
                  💰 Deals closed{g.dealTotal > 0 ? ` · $${g.dealTotal.toLocaleString()} total` : ""}
                </div>
                {g.deals.map(d => (
                  <div key={d.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 13, padding: "2px 0" }}>
                    <span>
                      {d.kind === "buy" ? "🟢 Bought" : d.kind === "sell" ? "🔵 Sold" : "•"} {d.description}
                      {d.amount != null ? ` — $${d.amount.toLocaleString()}` : ""} <span style={{ opacity: 0.5 }}>({fmtDate(d.created_at)})</span>
                    </span>
                    <button className="alert-remove-btn" onClick={() => handleDeleteDeal(d.id)} title="Delete deal" style={{ marginLeft: 8 }}>✕</button>
                  </div>
                ))}
                <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
                  <select className="add-alert-input" value={di(g.name).kind}
                    onChange={e => setDI(g.name, { kind: e.target.value as "" | "buy" | "sell" })}
                    style={{ width: 90 }}>
                    <option value="">type</option>
                    <option value="buy">Bought</option>
                    <option value="sell">Sold</option>
                  </select>
                  <input className="add-alert-input" placeholder="Deal (e.g. Jordan PSA 9)"
                    value={di(g.name).desc} onChange={e => setDI(g.name, { desc: e.target.value })}
                    style={{ flex: 2, minWidth: 140 }} />
                  <input className="add-alert-input" type="number" placeholder="$"
                    value={di(g.name).amt} onChange={e => setDI(g.name, { amt: e.target.value })}
                    style={{ width: 90 }} />
                  <button className="btn btn-sm" onClick={() => handleAddDeal(g.name)}>Add deal</button>
                </div>
              </div>

              {/* Notes log */}
              <div style={{ paddingLeft: 6 }}>
                {g.notes.map(n => (
                  <div key={n.id} className="alert-item" style={{ alignItems: "flex-start" }}>
                    <div className="alert-item-left" style={{ alignItems: "flex-start", flex: 1 }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 2 }}>{fmtDate(n.created_at)}</div>
                        {editingId === n.id ? (
                          <div>
                            <textarea className="add-alert-input" rows={3} value={editText}
                              onChange={e => setEditText(e.target.value)}
                              style={{ width: "100%", resize: "vertical", lineHeight: 1.5 }} />
                            <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                              <button className="btn btn-sm" onClick={() => saveEdit(n.id)}>Save</button>
                              <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.1)" }} onClick={() => setEditingId(null)}>Cancel</button>
                            </div>
                          </div>
                        ) : (
                          <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.5 }}>{n.note}</div>
                        )}
                      </div>
                    </div>
                    {editingId !== n.id && (
                      <div className="alert-item-actions">
                        <button className="alert-edit-btn" onClick={() => startEdit(n)} title="Edit note">✎</button>
                        <button className="alert-remove-btn" onClick={() => handleDeleteNote(n.id)} title="Delete note">✕</button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CallerNotesPage() {
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
    } catch {
      setPwError("Wrong password.");
    }
  }

  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;

  if (!unlocked) {
    return (
      <div className="app" style={{ paddingTop: 60, maxWidth: 440 }}>
        <h1>🔒 Caller Notes</h1>
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

  return <NotesBoard />;
}
