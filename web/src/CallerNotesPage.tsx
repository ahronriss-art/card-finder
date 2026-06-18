import { useEffect, useMemo, useState } from "react";
import { checkShopPassword, listCallerNotes, addCallerNote, deleteCallerNote, type CallerNote } from "./api/client";

function fmtDate(iso: string) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function NotesBoard() {
  const [notes, setNotes] = useState<CallerNote[]>([]);
  const [loading, setLoading] = useState(true);
  const [caller, setCaller] = useState("");
  const [phone, setPhone] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try { setNotes(await listCallerNotes()); } catch { setError("Couldn't load notes."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!caller.trim() || !text.trim()) { setError("Enter a caller name and a note."); return; }
    setSaving(true);
    setError("");
    try {
      const created = await addCallerNote(caller.trim(), text.trim(), phone.trim() || undefined);
      setNotes(prev => [created, ...prev]);
      setText("");  // keep caller/phone so you can log several notes for the same call
    } catch {
      setError("Couldn't save the note.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this note?")) return;
    try {
      await deleteCallerNote(id);
      setNotes(prev => prev.filter(n => n.id !== id));
    } catch { setError("Couldn't delete the note."); }
  }

  // Existing caller names for the autocomplete datalist.
  const callerNames = useMemo(
    () => Array.from(new Set(notes.map(n => n.caller_name))).sort((a, b) => a.localeCompare(b)),
    [notes],
  );

  // Group by caller; order callers by their most recent note (newest first).
  const groups = useMemo(() => {
    const term = filter.trim().toLowerCase();
    const visible = term
      ? notes.filter(n => `${n.caller_name} ${n.caller_phone || ""} ${n.note}`.toLowerCase().includes(term))
      : notes;
    const byCaller = new Map<string, CallerNote[]>();
    for (const n of visible) {
      if (!byCaller.has(n.caller_name)) byCaller.set(n.caller_name, []);
      byCaller.get(n.caller_name)!.push(n);
    }
    return Array.from(byCaller.entries())
      .map(([name, items]) => ({
        name,
        phone: items.find(i => i.caller_phone)?.caller_phone || "",
        items: items.slice().sort((a, b) => b.created_at.localeCompare(a.created_at)),
      }))
      .sort((a, b) => b.items[0].created_at.localeCompare(a.items[0].created_at));
  }, [notes, filter]);

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 720 }}>
      <h1>Caller Notes</h1>
      <p className="subtitle">Log what callers say — notes are grouped under each caller's name.</p>

      <div className="add-alert-box" style={{ marginTop: 20 }}>
        <div className="add-alert-title">+ Add a note</div>
        <form onSubmit={handleAdd}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
            <input
              className="add-alert-input" list="caller-names" placeholder="Caller name"
              value={caller} onChange={e => setCaller(e.target.value)}
              style={{ flex: 2, minWidth: 160 }}
            />
            <input
              className="add-alert-input" placeholder="Phone (optional)"
              value={phone} onChange={e => setPhone(e.target.value)}
              style={{ flex: 1, minWidth: 120 }}
            />
            <datalist id="caller-names">{callerNames.map(n => <option key={n} value={n} />)}</datalist>
          </div>
          <textarea
            className="add-alert-input" rows={3} placeholder="What did they say? (e.g. looking for 2003 LeBron RC, budget $5k)"
            value={text} onChange={e => setText(e.target.value)}
            style={{ width: "100%", resize: "vertical", lineHeight: 1.5 }}
          />
          {error && <div className="error-msg" style={{ marginTop: 8 }}>{error}</div>}
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
            <button className="btn btn-sm" type="submit" disabled={saving}>{saving ? "Saving…" : "Add note"}</button>
          </div>
        </form>
      </div>

      <div className="alert-search-wrap" style={{ marginTop: 18 }}>
        <span className="alert-search-icon">🔎</span>
        <input
          className="alert-search-input" type="text" placeholder="Search callers or notes…"
          value={filter} onChange={e => setFilter(e.target.value)}
        />
        {filter && <button className="alert-search-clear" onClick={() => setFilter("")} title="Clear">✕</button>}
      </div>

      {loading ? (
        <p className="subtitle" style={{ marginTop: 24 }}>Loading…</p>
      ) : groups.length === 0 ? (
        <div className="empty" style={{ marginTop: 32 }}>
          <p style={{ fontSize: 15 }}>{filter ? `No notes match "${filter}".` : "No caller notes yet. Add your first one above."}</p>
        </div>
      ) : (
        <div style={{ marginTop: 18 }}>
          {groups.map(g => (
            <div key={g.name} className="alert-folder" style={{ marginBottom: 18 }}>
              <div className="alert-folder-header" style={{ display: "flex", alignItems: "baseline", gap: 10, fontSize: 16, fontWeight: 700, padding: "8px 2px" }}>
                <span>👤 {g.name}</span>
                {g.phone && <span style={{ fontSize: 13, opacity: 0.7, fontWeight: 400 }}>{g.phone}</span>}
                <span style={{ fontSize: 12, opacity: 0.5, fontWeight: 400 }}>{g.items.length} note{g.items.length === 1 ? "" : "s"}</span>
              </div>
              <div style={{ paddingLeft: 6 }}>
                {g.items.map(n => (
                  <div key={n.id} className="alert-item" style={{ alignItems: "flex-start" }}>
                    <div className="alert-item-left" style={{ alignItems: "flex-start" }}>
                      <div>
                        <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 2 }}>{fmtDate(n.created_at)}</div>
                        <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.5 }}>{n.note}</div>
                      </div>
                    </div>
                    <div className="alert-item-actions">
                      <button className="alert-remove-btn" onClick={() => handleDelete(n.id)} title="Delete note">✕</button>
                    </div>
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
