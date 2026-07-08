import { useEffect, useMemo, useState } from "react";
import { sendBroadcast, listBroadcastGroups, getBroadcastGroup, createBroadcastGroup, deleteBroadcastGroup, updateBroadcastGroup, addToBroadcastGroup, updateBroadcastContact, deleteBroadcastContact, type BroadcastResult, type BroadcastGroup } from "./api/client";

// Preset "text back to" contacts — recipients are told to reply to this person.
// Add more here as needed: { name, phone }.
const TEXT_BACK_CONTACTS = [
  { name: "Uriel", phone: "(818) 877-5077" },
];

// Line(s) appended to the broadcast so recipients know who to text/call back.
// `raw` holds one contact per line; supports multiple.
function textBackLine(raw: string): string {
  const contacts = (raw || "").split(/[\n\r]+/).map(s => s.trim()).filter(Boolean);
  if (!contacts.length) return "";
  if (contacts.length === 1) return `\n\nText or call back to: ${contacts[0]}`;
  return `\n\nText or call back to:\n${contacts.map(c => `• ${c}`).join("\n")}`;
}

// Quick client-side parse for a live preview of how many valid phone numbers were pasted.
function parsePreview(raw: string) {
  let phones = 0, skipped = 0;
  for (let tok of (raw || "").split(/[\n\r,;\t]+/)) {
    tok = tok.trim();
    if (!tok) continue;
    const digits = tok.replace(/\D/g, "");
    if (digits.length >= 10) phones++;
    else skipped++;
  }
  return { phones, skipped };
}

export default function BroadcastPage() {
  const [recipients, setRecipients] = useState("");
  const [message, setMessage] = useState("");
  const [textBackTo, setTextBackTo] = useState("");
  const [team, setTeam] = useState<{ name: string; phone: string }[]>([{ name: "", phone: "" }]);
  const [saveAsGroup, setSaveAsGroup] = useState("");
  const [groups, setGroups] = useState<BroadcastGroup[]>([]);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<BroadcastResult | null>(null);
  const [error, setError] = useState("");
  const [image, setImage] = useState<string | null>(null);       // data URL for MMS
  const [addToGroupId, setAddToGroupId] = useState<number | null>(null);  // which group's "add people" box is open
  const [addNums, setAddNums] = useState("");
  // Expanded group → its contacts (numbers + names), editable.
  const [openGroupId, setOpenGroupId] = useState<number | null>(null);
  const [groupContacts, setGroupContacts] = useState<{ id: number; phone: string; name?: string | null }[]>([]);
  // Which folders are expanded (dropdown-style). Collapsed by default.
  const [openFolders, setOpenFolders] = useState<Set<string>>(new Set());
  function toggleFolder(key: string) {
    setOpenFolders(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  async function toggleExpand(g: BroadcastGroup) {
    if (openGroupId === g.id) { setOpenGroupId(null); return; }
    setOpenGroupId(g.id);
    try { const full = await getBroadcastGroup(g.id); setGroupContacts(full.contacts); }
    catch { setGroupContacts([]); }
  }
  async function renameContact(contactId: number, name: string) {
    setGroupContacts(cs => cs.map(c => c.id === contactId ? { ...c, name } : c));
    try { await updateBroadcastContact(contactId, { name }); } catch {}
  }
  async function removeContact(contactId: number) {
    setGroupContacts(cs => cs.filter(c => c.id !== contactId));
    try { await deleteBroadcastContact(contactId); loadGroups(); } catch {}
  }
  async function renameGroup(g: BroadcastGroup) {
    const name = prompt(`Rename group "${g.name}" to:`, g.name);
    if (!name || !name.trim() || name.trim() === g.name) return;
    try { await updateBroadcastGroup(g.id, { name: name.trim() }); loadGroups(); }
    catch { setError("Couldn't rename the group."); }
  }

  function pickImage(file: File | null | undefined) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { setError("Image is over 5MB — pick a smaller one."); return; }
    const r = new FileReader();
    r.onload = () => setImage(r.result as string);
    r.readAsDataURL(file);
  }
  async function addPeopleToGroup(g: BroadcastGroup) {
    if (!addNums.trim()) return;
    try {
      const r = await addToBroadcastGroup(g.id, addNums);
      setAddNums(""); setAddToGroupId(null);
      await loadGroups();
      setError("");
      alert(`Added ${r.added} to "${g.name}" (${r.total} total).`);
    } catch { setError("Couldn't add those numbers to the group."); }
  }

  const preview = useMemo(() => parsePreview(recipients), [recipients]);

  async function loadGroups() {
    try { setGroups(await listBroadcastGroups()); } catch {}
  }
  useEffect(() => { loadGroups(); }, []);

  // Direct group/folder manager (create groups without broadcasting).
  const [showManager, setShowManager] = useState(false);
  const [gName, setGName] = useState("");
  const [gFolder, setGFolder] = useState("");
  const [gNums, setGNums] = useState("");
  const [gMsg, setGMsg] = useState("");
  async function createGroup() {
    if (!gName.trim()) { setGMsg("Enter a group name."); return; }
    try {
      const g = await createBroadcastGroup(gName.trim(), gNums, gFolder.trim() || undefined);
      setGMsg(`Saved "${g.name}"${g.folder ? ` in 🗂 ${g.folder}` : ""} — ${g.count} number${g.count === 1 ? "" : "s"}.`);
      setGName(""); setGFolder(""); setGNums("");
      loadGroups();
    } catch { setGMsg("Couldn't save that group."); }
  }

  async function loadGroupInto(g: BroadcastGroup) {
    try {
      const full = await getBroadcastGroup(g.id);
      // Include the saved name next to each number so the Inbox shows the person's
      // name (the broadcast parses "Name <number>" lines into conversation names).
      const nums = full.contacts.map(c => (c.name ? `${c.name} ${c.phone}` : c.phone)).join("\n");
      setRecipients(prev => {
        const base = prev.trim();
        return base ? base + "\n" + nums : nums;  // append so you can combine groups
      });
    } catch { setError("Couldn't load that group."); }
  }

  const [history, setHistory] = useState<{ name: string; entries: { message: string; sent_count: number; created_at?: string | null }[] } | null>(null);
  async function showHistory(g: BroadcastGroup) {
    try {
      const full = await getBroadcastGroup(g.id);
      setHistory({ name: g.name, entries: full.history || [] });
    } catch { setError("Couldn't load that group's history."); }
  }

  async function removeGroup(g: BroadcastGroup) {
    if (!confirm(`Delete the group "${g.name}"? (Numbers stay on any sent texts; this only removes the saved list.)`)) return;
    try { await deleteBroadcastGroup(g.id); loadGroups(); } catch { setError("Couldn't delete the group."); }
  }

  async function setGroupFolder(g: BroadcastGroup) {
    const folder = prompt(`Folder for "${g.name}" (blank = no folder):`, g.folder || "");
    if (folder === null) return;
    try { await updateBroadcastGroup(g.id, { folder: folder.trim() }); loadGroups(); }
    catch { setError("Couldn't update the folder."); }
  }

  // Group the saved groups by folder (folders alphabetical, "No folder" last).
  const groupsByFolder = useMemo(() => {
    const m = new Map<string, BroadcastGroup[]>();
    for (const g of groups) {
      const k = (g.folder || "").trim();
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(g);
    }
    const keys = Array.from(m.keys()).filter(Boolean).sort((a, b) => a.localeCompare(b));
    if (m.has("")) keys.push("");
    return keys.map(k => [k, m.get(k)!] as const);
  }, [groups]);

  async function send() {
    setError("");
    setResult(null);
    if (!message.trim() && !image) { setError("Write a message or add a picture first."); return; }
    if (preview.phones === 0) { setError("Add at least one phone number."); return; }
    if (!confirm(`Send this ${image ? "picture text" : "text"} to ${preview.phones} number(s)?`)) return;
    setSending(true);
    try {
      const fullMessage = message.trim() + textBackLine(textBackTo);
      const assignees = team.map(t => ({ name: t.name.trim() || undefined, phone: t.phone.trim() })).filter(t => t.phone);
      const r = await sendBroadcast(recipients, fullMessage, assignees.length ? assignees : undefined, saveAsGroup.trim() || undefined, image || undefined);
      setResult(r);
      setImage(null);
      if (saveAsGroup.trim()) { setSaveAsGroup(""); loadGroups(); }
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to send.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "24px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>Broadcast (Text)</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Paste a list of phone numbers, write one text, and send it to everyone at once.
      </p>

      <div style={{ background: "#fef9c3", border: "1px solid #fde047", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#854d0e", margin: "12px 0" }}>
        ⚠️ Only text people who agreed to hear from you. The message sends exactly as written — Twilio still automatically honors “STOP” replies for opt-out.
      </div>

      {/* Groups & folders manager — create/organize without broadcasting */}
      <div style={{ margin: "10px 0 14px" }}>
        <button type="button" onClick={() => { setShowManager(m => !m); setGMsg(""); }}
          style={{ background: "none", border: "none", cursor: "pointer", color: "#2563eb", fontSize: 14, fontWeight: 700, padding: 0 }}>
          {showManager ? "▾ " : "▸ "}📁 Manage groups & folders
        </button>
        {showManager && (
          <div style={{ marginTop: 8, border: "1px solid #cbd5e1", borderRadius: 10, padding: 12, background: "#f8fafc" }}>
            <div style={{ fontSize: 13, color: "#475569", marginBottom: 8 }}>
              Create a group and (optionally) file it in a folder — no broadcast needed. Using an existing group name adds the numbers to it.
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              <input value={gName} onChange={e => setGName(e.target.value)} placeholder="Group name (e.g. Whatnot buyers)"
                style={{ flex: 1, minWidth: 180, padding: 9, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
              <input value={gFolder} onChange={e => setGFolder(e.target.value)} placeholder="Folder (optional, e.g. Buyers)"
                style={{ flex: 1, minWidth: 150, padding: 9, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
            </div>
            <textarea value={gNums} onChange={e => setGNums(e.target.value)} rows={3}
              placeholder={"Numbers to add (optional) — one per line or comma-separated.\n818-740-9787\n(212) 555-1234"}
              style={{ width: "100%", padding: 9, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14, fontFamily: "inherit", boxSizing: "border-box" }} />
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 8 }}>
              <button type="button" onClick={createGroup}
                style={{ background: "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "8px 16px", fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
                Save group
              </button>
              {gMsg && <span style={{ fontSize: 13, color: "#15803d" }}>{gMsg}</span>}
            </div>
          </div>
        )}
      </div>

      {groups.length > 0 && (
        <div style={{ margin: "8px 0 14px" }}>
          <label style={{ fontWeight: 600, fontSize: 14 }}>Saved groups</label>
          <div style={{ fontSize: 13, color: "#475569", margin: "2px 0 8px" }}>Tap a group to open its dropdown and see every number — add a name to each one. Use <strong>⬇︎ Load</strong> to drop a group's numbers into the message below (combine several), ＋ to add numbers, 🗂 to file it in a folder.</div>
          {groupsByFolder.map(([folder, gs]) => {
            const isOpen = openFolders.has(folder);
            const people = gs.reduce((n, g) => n + (g.count || 0), 0);
            return (
            <div key={folder || "_none"} style={{ marginBottom: 8, border: "1px solid #e2e8f0", borderRadius: 10, overflow: "hidden" }}>
              <button type="button" onClick={() => toggleFolder(folder)}
                style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "9px 12px", cursor: "pointer",
                  background: isOpen ? "#eef2ff" : "#f8fafc", border: "none", textAlign: "left",
                  fontSize: 13, fontWeight: 700, color: folder ? "#1d4ed8" : "#64748b" }}>
                <span style={{ fontSize: 12, color: "#64748b" }}>{isOpen ? "▾" : "▸"}</span>
                {folder ? `🗂 ${folder}` : "📁 No folder"}
                <span style={{ marginLeft: "auto", fontWeight: 400, color: "#94a3b8", fontSize: 12 }}>
                  {gs.length} group{gs.length === 1 ? "" : "s"} · {people} number{people === 1 ? "" : "s"}
                </span>
              </button>
              {isOpen && (
              <div style={{ padding: "10px 12px" }}>
              {/* Each group is its own collapsible dropdown row */}
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {gs.map(g => {
                  const gOpen = openGroupId === g.id;
                  const addOpen = addToGroupId === g.id;
                  return (
                  <div key={g.id} style={{ border: "1px solid #cbd5e1", borderRadius: 10, overflow: "hidden", background: "#fff" }}>
                    {/* Header row */}
                    <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "8px 10px", background: gOpen ? "#eef2ff" : "#fff", flexWrap: "wrap" }}>
                      <button type="button" title="Show/hide the numbers" onClick={() => toggleExpand(g)}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: 13 }}>{gOpen ? "▾" : "▸"}</button>
                      <button type="button" onClick={() => toggleExpand(g)}
                        style={{ flex: 1, minWidth: 120, background: "none", border: "none", cursor: "pointer", fontSize: 14, fontWeight: 700, color: "#334155", textAlign: "left" }}>
                        {g.name} <span style={{ opacity: 0.55, fontWeight: 400 }}>· {g.count} number{g.count === 1 ? "" : "s"}</span>
                      </button>
                      <button type="button" title="Load these numbers into the message below" onClick={() => loadGroupInto(g)}
                        style={{ background: "#eef2ff", border: "1px solid #c7d2fe", borderRadius: 7, cursor: "pointer", color: "#1d4ed8", fontSize: 12, fontWeight: 600, padding: "3px 9px" }}>⬇︎ Load</button>
                      <button type="button" title="Rename this group" onClick={() => renameGroup(g)}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: 13 }}>✎</button>
                      <button type="button" title="Add numbers to this group" onClick={() => { setAddToGroupId(addOpen ? null : g.id); setAddNums(""); }}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "#16a34a", fontSize: 15, fontWeight: 700 }}>＋</button>
                      <button type="button" title="What we messaged them" onClick={() => showHistory(g)}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: 13 }}>📋</button>
                      <button type="button" title="Set folder" onClick={() => setGroupFolder(g)}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: 13 }}>🗂</button>
                      <button type="button" title="Delete group" onClick={() => removeGroup(g)}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 13 }}>✕</button>
                    </div>

                    {/* Dropdown: each number, with a name you can add/edit */}
                    {gOpen && (
                      <div style={{ padding: 10, borderTop: "1px solid #e2e8f0", background: "#f8fafc" }}>
                        {groupContacts.length === 0 ? <div style={{ fontSize: 13, color: "#64748b" }}>No numbers saved in this group yet — use ＋ to add some.</div>
                          : <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                              {groupContacts.map(c => (
                                <div key={c.id} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                                  <input defaultValue={c.name || ""} placeholder="add a name…" onBlur={e => renameContact(c.id, e.target.value)}
                                    style={{ width: 160, padding: "6px 9px", borderRadius: 7, border: "1px solid #cbd5e1", fontSize: 13 }} />
                                  <span style={{ fontSize: 13, color: "#334155" }}>{c.phone}</span>
                                  <button type="button" onClick={() => removeContact(c.id)} title="Remove from group"
                                    style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 13 }}>✕</button>
                                </div>
                              ))}
                            </div>}
                      </div>
                    )}

                    {/* Add-numbers box */}
                    {addOpen && (
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", padding: 10, borderTop: "1px solid #e2e8f0", background: "#f8fafc" }}>
                        <span style={{ fontSize: 13, fontWeight: 600 }}>Add to <strong>{g.name}</strong>:</span>
                        <input value={addNums} onChange={e => setAddNums(e.target.value)}
                          placeholder="Name 2125551234, or paste numbers (one per line)"
                          style={{ flex: 1, minWidth: 220, padding: "7px 10px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 13 }} />
                        <button className="btn btn-sm" type="button" onClick={() => addPeopleToGroup(g)} disabled={!addNums.trim()}>Add</button>
                        <button type="button" onClick={() => setAddToGroupId(null)} style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 13 }}>cancel</button>
                      </div>
                    )}
                  </div>
                  );
                })}
              </div>
              </div>
              )}
            </div>
            );
          })}

          {history && (
            <div style={{ marginTop: 10, border: "1px solid #cbd5e1", borderRadius: 10, padding: 12, background: "#f8fafc" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <strong style={{ fontSize: 14 }}>📋 {history.name} — what we messaged</strong>
                <button type="button" onClick={() => setHistory(null)} style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8" }}>✕</button>
              </div>
              {history.entries.length === 0 ? (
                <div style={{ fontSize: 13, color: "#64748b" }}>No messages logged for this group yet.</div>
              ) : history.entries.map((e, i) => (
                <div key={i} style={{ borderTop: i ? "1px solid #e2e8f0" : "none", padding: "8px 0" }}>
                  <div style={{ fontSize: 12, color: "#64748b" }}>
                    {e.created_at ? new Date(e.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : ""} · sent to {e.sent_count}
                  </div>
                  <div style={{ fontSize: 14, whiteSpace: "pre-wrap", marginTop: 2 }}>{e.message}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <label style={{ fontWeight: 600, fontSize: 14 }}>Phone numbers</label>
      <textarea
        value={recipients}
        onChange={e => setRecipients(e.target.value)}
        placeholder={"Paste phone numbers — one per line or comma-separated.\n818-740-9787\n(212) 555-1234"}
        rows={6}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4 }}
      />
      <div style={{ fontSize: 13, color: "#475569", marginBottom: 12 }}>
        Detected: <strong>{preview.phones}</strong> number{preview.phones === 1 ? "" : "s"}
        {preview.skipped > 0 && <span style={{ color: "#b45309" }}> · {preview.skipped} skipped (unrecognized)</span>}
      </div>

      <label style={{ fontWeight: 600, fontSize: 14 }}>Message</label>
      <textarea
        value={message}
        onChange={e => setMessage(e.target.value)}
        placeholder="Your text message — sent exactly as written. (A picture alone is fine too.)"
        rows={5}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4, marginBottom: 12 }}
      />

      {/* Picture (MMS) */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
        <label className="btn btn-sm" style={{ cursor: "pointer" }}>
          📷 {image ? "Change picture" : "Add a picture (MMS)"}
          <input type="file" accept="image/*" hidden onChange={e => pickImage(e.target.files?.[0])} />
        </label>
        {image && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <img src={image} alt="" style={{ height: 44, borderRadius: 6, border: "1px solid #cbd5e1" }} />
            <button type="button" onClick={() => setImage(null)} style={{ background: "none", border: "none", cursor: "pointer", color: "#dc2626", fontSize: 13 }}>✕ remove</button>
          </span>
        )}
        {image && <span style={{ fontSize: 12, color: "#64748b" }}>Sends as a picture text (MMS costs a bit more per message).</span>}
      </div>

      <label style={{ fontWeight: 600, fontSize: 14 }}>Text or Call back to</label>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "6px 0" }}>
        {TEXT_BACK_CONTACTS.map(c => {
          const entry = `${c.name} ${c.phone}`;
          const already = textBackTo.split(/[\n\r]+/).map(s => s.trim()).includes(entry);
          return (
            <button key={c.name} type="button" disabled={already}
              onClick={() => setTextBackTo(t => (t.trim() ? t.trim() + "\n" : "") + entry)}
              style={{ fontSize: 13, fontWeight: 600, padding: "5px 11px", borderRadius: 999, cursor: already ? "default" : "pointer",
                border: "1px solid #cbd5e1", background: already ? "#e2e8f0" : "#fff", color: "#334155" }}>
              {already ? "✓ " : "+ "}{c.name} {c.phone}
            </button>
          );
        })}
      </div>
      <textarea
        value={textBackTo}
        onChange={e => setTextBackTo(e.target.value)}
        placeholder={"One contact per line — name and/or number.\nUriel (818) 877-5077\nAvi 212-555-1234"}
        rows={3}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4 }}
      />
      <div style={{ fontSize: 13, color: "#475569", margin: "4px 0 12px" }}>
        {textBackTo.trim()
          ? <>Appended to the text: <em style={{ whiteSpace: "pre-wrap" }}>"{textBackLine(textBackTo).trim()}"</em></>
          : "Optional — add one or more people (one per line) so recipients know who to text or call back."}
      </div>

      <label style={{ fontWeight: 600, fontSize: 14 }}>Assign follow-up teammates (optional)</label>
      <div style={{ fontSize: 13, color: "#475569", margin: "2px 0 6px" }}>
        When recipients reply, <strong>every</strong> teammate here gets the reply forwarded and can answer right from their phone
        (or the Inbox) — replies go back out through the 877, so the customer sees one conversation.
      </div>
      {team.map((t, i) => (
        <div key={i} style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8, alignItems: "center" }}>
          <input value={t.name} onChange={e => setTeam(prev => prev.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
            placeholder="Teammate name (e.g. Uriel)"
            style={{ flex: 1, minWidth: 150, padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
          <input value={t.phone} onChange={e => setTeam(prev => prev.map((x, j) => j === i ? { ...x, phone: e.target.value } : x))}
            placeholder="Their phone"
            style={{ flex: 1, minWidth: 150, padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
          {team.length > 1 && (
            <button type="button" onClick={() => setTeam(prev => prev.filter((_, j) => j !== i))}
              title="Remove" style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 18 }}>✕</button>
          )}
        </div>
      ))}
      <button type="button" onClick={() => setTeam(prev => [...prev, { name: "", phone: "" }])}
        style={{ background: "none", border: "none", cursor: "pointer", color: "#2563eb", fontSize: 13, fontWeight: 600, padding: "0 0 12px" }}>
        + Add another teammate
      </button>

      <label style={{ fontWeight: 600, fontSize: 14 }}>Save these recipients as a group (optional)</label>
      <div style={{ fontSize: 13, color: "#475569", margin: "2px 0 6px" }}>
        Give this batch a name (e.g. "Whatnot buyers", "NorCal shops") and it's saved as a reusable group you can message again later.
      </div>
      <input value={saveAsGroup} onChange={e => setSaveAsGroup(e.target.value)} placeholder="Group name (leave blank to not save)"
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14, marginBottom: 12 }} />

      <button
        onClick={send}
        disabled={sending}
        style={{ background: sending ? "#94a3b8" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "10px 22px", fontSize: 15, fontWeight: 600, cursor: sending ? "default" : "pointer" }}
      >
        {sending ? "Sending…" : `Send to ${preview.phones} number${preview.phones === 1 ? "" : "s"}`}
      </button>

      {error && <div style={{ color: "#dc2626", marginTop: 12, fontSize: 14 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16, background: "#f1f5f9", borderRadius: 8, padding: 14, fontSize: 14 }}>
          <strong>Done.</strong>
          <div style={{ marginTop: 6 }}>📱 Texts: {result.sms.sent} sent{result.sms.failed ? `, ${result.sms.failed} failed` : ""} (of {result.sms.total})</div>
          {result.saved_group && (
            <div style={{ marginTop: 6 }}>📂 Saved to group <strong>{result.saved_group.name}</strong> ({result.saved_group.added} new · {result.saved_group.total} total)</div>
          )}
          {result.skipped.length > 0 && (
            <div style={{ marginTop: 6, color: "#b45309" }}>Skipped {result.skipped.length}: {result.skipped.slice(0, 8).join(", ")}{result.skipped.length > 8 ? "…" : ""}</div>
          )}
        </div>
      )}
    </div>
  );
}
