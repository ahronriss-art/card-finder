import { useEffect, useMemo, useRef, useState } from "react";
import {
  uploadChecklist, listChecklists, getChecklist, deleteChecklist,
  checklistChat, checklistToAlerts,
  saveChecklistSearch, listChecklistSearches, runChecklistSearch, deleteChecklistSearch,
  getSavedSearches, deleteSearch,
  getShopsPassword, checkShopPassword, clearShopsPassword,
  type ChecklistUpload, type ChecklistCard, type ChecklistSavedSearch,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";

// Read the file the user picked as a base64 string (strip the data: prefix server-side).
function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

const cardCell: React.CSSProperties = { padding: "7px 10px", fontSize: 13, borderBottom: "1px solid rgba(255,255,255,0.06)" };

function Board() {
  const [uploads, setUploads] = useState<ChecklistUpload[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [upload, setUpload] = useState<ChecklistUpload | null>(null);
  const [allCards, setAllCards] = useState<ChecklistCard[]>([]);
  const [matched, setMatched] = useState<ChecklistCard[] | null>(null); // null = showing all
  const [query, setQuery] = useState("");
  const [chatInfo, setChatInfo] = useState<{ used_ai: boolean; filter: any } | null>(null);
  const [saved, setSaved] = useState<ChecklistSavedSearch[]>([]);
  const [savingSearch, setSavingSearch] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [sentAlerts, setSentAlerts] = useState<{ id: number; query: string }[]>([]);

  const [busy, setBusy] = useState(false);
  const [searching, setSearching] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [name, setName] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const userId = Number(localStorage.getItem("userId")) || null;

  async function loadUploads() {
    try { setUploads(await listChecklists()); } catch { setError("Couldn't load checklists."); }
  }
  useEffect(() => { loadUploads(); }, []);

  async function loadSaved(id: number) {
    try { setSaved(await listChecklistSearches(id)); } catch { /* non-fatal */ }
  }

  // The alerts pushed from this checklist are the user's active saved searches
  // whose folder matches the checklist name.
  async function loadSentAlerts(name: string) {
    if (!userId) { setSentAlerts([]); return; }
    try {
      const all = await getSavedSearches(userId);
      const folder = (name || "").trim().toLowerCase();
      setSentAlerts((all as any[])
        .filter(s => (s.folder || "").trim().toLowerCase() === folder)
        .map(s => ({ id: s.id, query: s.query })));
    } catch { /* not logged into alerts — leave empty */ }
  }

  async function open(id: number) {
    setOpenId(id); setMatched(null); setQuery(""); setChatInfo(null); setError(""); setSaved([]); setSelected(new Set()); setSentAlerts([]);
    try {
      const { upload, cards } = await getChecklist(id);
      setUpload(upload); setAllCards(cards);
      loadSaved(id);
      loadSentAlerts(upload.name);
    } catch { setError("Couldn't open that checklist."); }
  }

  async function removeAlert(id: number) {
    try {
      await deleteSearch(id);
      setSentAlerts(prev => prev.filter(a => a.id !== id));
    } catch { setError("Couldn't remove that alert."); }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true); setError(""); setToast("");
    try {
      const b64 = await fileToBase64(file);
      const nm = (name.trim() || file.name.replace(/\.[^.]+$/, ""));
      const { upload } = await uploadChecklist(nm, file.name, b64);
      setName("");
      if (fileRef.current) fileRef.current.value = "";
      await loadUploads();
      await open(upload.id);
      setToast(`Loaded ${upload.card_count} cards from ${upload.name}.`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't parse that file. Use a Beckett .xlsx checklist export.");
    } finally { setBusy(false); }
  }

  async function runSearch() {
    if (!openId || !query.trim()) { setMatched(null); setChatInfo(null); return; }
    setSearching(true); setError("");
    try {
      const res = await checklistChat(openId, query.trim());
      setMatched(res.cards);
      setChatInfo({ used_ai: res.used_ai, filter: res.filter });
      setSelected(new Set());
    } catch { setError("Search failed — try rephrasing."); }
    finally { setSearching(false); }
  }

  function clearSearch() { setMatched(null); setQuery(""); setChatInfo(null); setSelected(new Set()); }

  async function saveCurrentSearch() {
    if (!openId || !chatInfo || matched === null) return;
    const nm = prompt("Name this saved search:", query.trim() || "Saved search");
    if (nm === null) return;
    setSavingSearch(true); setError("");
    try {
      await saveChecklistSearch(openId, nm.trim() || query.trim(), query.trim(), chatInfo.filter || {});
      await loadSaved(openId);
      setToast(`Saved "${nm.trim() || query.trim()}".`);
    } catch { setError("Couldn't save that search."); }
    finally { setSavingSearch(false); }
  }

  async function runSaved(s: ChecklistSavedSearch) {
    setSearching(true); setError("");
    try {
      const res = await runChecklistSearch(s.id);
      setMatched(res.cards);
      setQuery(res.query || s.name);
      setChatInfo({ used_ai: true, filter: res.filter });
      setSelected(new Set());
    } catch { setError("Couldn't run that saved search."); }
    finally { setSearching(false); }
  }

  async function removeSaved(s: ChecklistSavedSearch) {
    try { await deleteChecklistSearch(s.id); if (openId) await loadSaved(openId); }
    catch { setError("Couldn't delete that saved search."); }
  }

  function toggleOne(id: number) {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }
  function toggleAll(rows: ChecklistCard[]) {
    setSelected(prev => {
      const allOn = rows.length > 0 && rows.every(c => prev.has(c.id));
      if (allOn) { const n = new Set(prev); rows.forEach(c => n.delete(c.id)); return n; }
      const n = new Set(prev); rows.forEach(c => n.add(c.id)); return n;
    });
  }

  async function pushToAlerts() {
    if (!openId) return;
    const visible = matched ?? allCards;
    // Send checked rows if any are selected; otherwise send everything shown.
    const rows = selected.size ? visible.filter(c => selected.has(c.id)) : visible;
    if (!rows.length) return;
    if (!userId) { setError("Sign in on the Alerts tab first, then come back to push these to alerts."); return; }
    if (rows.length > 300 && !confirm(`This will create up to 300 alerts (of ${rows.length} selected). Continue?`)) return;
    setPushing(true); setError(""); setToast("");
    try {
      const res = await checklistToAlerts(openId, userId, rows.map(c => c.id));
      setToast(`Added ${res.created} alert${res.created === 1 ? "" : "s"} to the "${res.folder}" folder`
        + (res.skipped ? `, skipped ${res.skipped} you already had` : "")
        + (res.capped ? " (capped at 300)" : "") + ". Note: your $1000 listed-card floor still applies.");
      if (upload) loadSentAlerts(upload.name);
      setSelected(new Set());
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't create alerts.");
    } finally { setPushing(false); }
  }

  async function remove(id: number) {
    if (!confirm("Delete this checklist?")) return;
    try {
      await deleteChecklist(id);
      if (openId === id) { setOpenId(null); setUpload(null); setAllCards([]); setMatched(null); }
      await loadUploads();
    } catch { setError("Couldn't delete."); }
  }

  const shown = matched ?? allCards;
  const filterChips = useMemo(() => {
    const f = chatInfo?.filter || {};
    const chips: string[] = [];
    (f.players || []).forEach((p: string) => chips.push(`player: ${p}`));
    (f.subsets || []).forEach((s: string) => chips.push(s));
    (f.teams || []).forEach((t: string) => chips.push(`team: ${t}`));
    if (f.rookies_only) chips.push("rookies only");
    if (f.numbered_max) chips.push(`≤ /${f.numbered_max}`);
    (f.keywords || []).forEach((k: string) => chips.push(`"${k}"`));
    return chips;
  }, [chatInfo]);

  return (
    <div className="app" style={{ maxWidth: 1000 }}>
      <h1>Checklists</h1>
      <p className="subtitle">Upload a Beckett checklist (.xlsx), search it in plain English, then push the matches straight to your Alerts.</p>

      {error && <div style={{ background: "rgba(239,68,68,0.15)", border: "1px solid rgba(239,68,68,0.4)", color: "#fca5a5", padding: "8px 12px", borderRadius: 8, marginBottom: 12, fontSize: 13 }}>{error}</div>}
      {toast && <div style={{ background: "rgba(34,197,94,0.15)", border: "1px solid rgba(34,197,94,0.4)", color: "#bbf7d0", padding: "8px 12px", borderRadius: 8, marginBottom: 12, fontSize: 13 }}>{toast}</div>}

      {/* Upload */}
      <div className="add-alert-box">
        <div className="add-alert-title">⬆️ Upload a checklist (.xlsx)</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <input className="add-alert-input" style={{ flex: "1 1 260px" }} placeholder="Name (optional — defaults to filename)"
            value={name} onChange={e => setName(e.target.value)} />
          <input ref={fileRef} type="file" accept=".xlsx,.xls" onChange={onFile} disabled={busy}
            style={{ fontSize: 13, color: "#94a3b8" }} />
          {busy && <span style={{ fontSize: 13, color: "#94a3b8" }}>Parsing…</span>}
        </div>
      </div>

      {/* Saved checklists */}
      {uploads.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "14px 0" }}>
          {uploads.map(u => (
            <div key={u.id} style={{
              display: "flex", alignItems: "center", gap: 8, padding: "6px 10px", borderRadius: 8,
              border: `1px solid ${openId === u.id ? "rgba(34,197,94,0.5)" : "rgba(255,255,255,0.12)"}`,
              background: openId === u.id ? "rgba(34,197,94,0.12)" : "rgba(255,255,255,0.04)", cursor: "pointer", fontSize: 13,
            }} onClick={() => open(u.id)}>
              <span style={{ color: "#e2e8f0" }}>{u.name}</span>
              <span style={{ color: "#64748b" }}>{u.card_count}</span>
              <button title="Delete" onClick={(e) => { e.stopPropagation(); remove(u.id); }}
                style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: 14 }}>✕</button>
            </div>
          ))}
        </div>
      )}

      {/* Open checklist: search + results */}
      {upload && (
        <div>
          <div className="add-alert-box" style={{ marginTop: 4 }}>
            <div className="add-alert-title">🔎 Search {upload.name}</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <input className="add-alert-input" style={{ flex: "1 1 320px" }}
                placeholder='e.g. "Cooper Flagg autos" or "rookie inserts numbered to /99"'
                value={query} onChange={e => setQuery(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") runSearch(); }} />
              <button className="btn" onClick={runSearch} disabled={searching}>{searching ? "Searching…" : "Search"}</button>
              {matched !== null && chatInfo && <button className="btn btn-sm" onClick={saveCurrentSearch} disabled={savingSearch}>{savingSearch ? "Saving…" : "💾 Save search"}</button>}
              {matched !== null && <button className="btn btn-sm" onClick={clearSearch}>Show all</button>}
            </div>
            {chatInfo && (
              <div style={{ marginTop: 8, fontSize: 12, color: "#94a3b8", display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                {!chatInfo.used_ai && <span style={{ color: "#eab308" }}>text match</span>}
                {filterChips.map((c, i) => (
                  <span key={i} style={{ background: "rgba(59,130,246,0.15)", border: "1px solid rgba(59,130,246,0.35)", borderRadius: 999, padding: "2px 8px" }}>{c}</span>
                ))}
              </div>
            )}
          </div>

          {saved.length > 0 && (
            <div style={{ margin: "12px 2px 0" }}>
              <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", marginBottom: 6 }}>Saved searches</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {saved.map(s => (
                  <div key={s.id} style={{
                    display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 999,
                    border: "1px solid rgba(168,85,247,0.4)", background: "rgba(168,85,247,0.12)", cursor: "pointer", fontSize: 13,
                  }} onClick={() => runSaved(s)} title={s.query || s.name}>
                    <span style={{ color: "#e9d5ff" }}>{s.name}</span>
                    {typeof s.count === "number" && <span style={{ color: "#a78bda" }}>{s.count}</span>}
                    <button title="Delete" onClick={(e) => { e.stopPropagation(); removeSaved(s); }}
                      style={{ background: "none", border: "none", color: "#a78bda", cursor: "pointer", fontSize: 14 }}>✕</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {sentAlerts.length > 0 && (
            <div style={{ margin: "12px 2px 0" }}>
              <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", marginBottom: 6 }}>
                In alerts ({sentAlerts.length}) — sent from this checklist
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {sentAlerts.map(a => (
                  <div key={a.id} style={{
                    display: "flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 999,
                    border: "1px solid rgba(251,146,60,0.4)", background: "rgba(251,146,60,0.12)", fontSize: 13,
                  }}>
                    <span style={{ color: "#fed7aa" }}>{a.query}</span>
                    <button title="Remove from alerts" onClick={() => removeAlert(a.id)}
                      style={{ background: "none", border: "none", color: "#fdba74", cursor: "pointer", fontSize: 14 }}>✕</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "14px 2px 8px", gap: 10, flexWrap: "wrap" }}>
            <span style={{ fontSize: 13, color: "#94a3b8" }}>
              {matched !== null ? `${shown.length} match${shown.length === 1 ? "" : "es"} of ${allCards.length}` : `${allCards.length} cards`}
              {selected.size > 0 && <span style={{ color: "#4ade80" }}> · {selected.size} selected</span>}
            </span>
            <div style={{ display: "flex", gap: 8 }}>
              {selected.size > 0 && <button className="btn btn-sm" onClick={() => setSelected(new Set())}>Clear selection</button>}
              <button className="btn" onClick={pushToAlerts} disabled={pushing || !shown.length}>
                {pushing ? "Adding…"
                  : selected.size > 0 ? `➕ Send ${selected.size} selected to Alerts`
                  : `➕ Send all ${shown.length} to Alerts`}
              </button>
            </div>
          </div>

          <div style={{ background: "rgba(255,255,255,0.03)", borderRadius: 10, overflow: "hidden", border: "1px solid rgba(255,255,255,0.08)" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left", color: "#64748b", fontSize: 11, textTransform: "uppercase" }}>
                  <th style={{ ...cardCell, borderBottom: "1px solid rgba(255,255,255,0.12)", width: 34 }}>
                    <input type="checkbox" title="Select all shown"
                      checked={shown.length > 0 && shown.slice(0, 500).every(c => selected.has(c.id))}
                      onChange={() => toggleAll(shown.slice(0, 500))} />
                  </th>
                  <th style={{ ...cardCell, borderBottom: "1px solid rgba(255,255,255,0.12)" }}>Subset</th>
                  <th style={{ ...cardCell, borderBottom: "1px solid rgba(255,255,255,0.12)" }}>#</th>
                  <th style={{ ...cardCell, borderBottom: "1px solid rgba(255,255,255,0.12)" }}>Player</th>
                  <th style={{ ...cardCell, borderBottom: "1px solid rgba(255,255,255,0.12)" }}>Team</th>
                  <th style={{ ...cardCell, borderBottom: "1px solid rgba(255,255,255,0.12)" }}>#'d</th>
                </tr>
              </thead>
              <tbody>
                {shown.slice(0, 500).map(c => (
                  <tr key={c.id} style={selected.has(c.id) ? { background: "rgba(34,197,94,0.08)" } : undefined}>
                    <td style={{ ...cardCell }}>
                      <input type="checkbox" checked={selected.has(c.id)} onChange={() => toggleOne(c.id)} />
                    </td>
                    <td style={{ ...cardCell, color: "#cbd5e1" }}>{c.subset}{c.rookie && <span style={{ marginLeft: 6, color: "#4ade80", fontSize: 11 }}>RC</span>}</td>
                    <td style={{ ...cardCell, color: "#94a3b8" }}>{c.card_number}</td>
                    <td style={{ ...cardCell, color: "#e2e8f0", fontWeight: 500 }}>{c.player}</td>
                    <td style={{ ...cardCell, color: "#94a3b8" }}>{c.team}</td>
                    <td style={{ ...cardCell, color: "#94a3b8" }}>{c.numbered_to ? `/${c.numbered_to}` : ""}</td>
                  </tr>
                ))}
                {!shown.length && <tr><td colSpan={6} style={{ padding: 16, textAlign: "center", color: "#64748b" }}>No cards match.</td></tr>}
              </tbody>
            </table>
            {shown.length > 500 && <div style={{ padding: "8px 12px", fontSize: 12, color: "#64748b" }}>Showing first 500 of {shown.length}. Narrow your search to see the rest.</div>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ChecklistsPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    const stored = getShopsPassword();
    if (!stored) { setChecking(false); return; }
    setUnlocked(true); setChecking(false);
    checkShopPassword(stored).catch((err: any) => {
      if (err?.response?.status === 401) { clearShopsPassword(); setUnlocked(false); }
    });
  }, []);
  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;
  if (!unlocked) return <ShopPasswordForm title="Checklists" onUnlocked={() => setUnlocked(true)} />;
  return <Board />;
}
