import { useEffect, useMemo, useState } from "react";
import { sendBroadcast, listBroadcastGroups, getBroadcastGroup, createBroadcastGroup, deleteBroadcastGroup, updateBroadcastGroup, type BroadcastResult, type BroadcastGroup } from "./api/client";

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
    if (!message.trim()) { setError("Write a message first."); return; }
    if (preview.phones === 0) { setError("Add at least one phone number."); return; }
    if (!confirm(`Send this text to ${preview.phones} number(s)?`)) return;
    setSending(true);
    try {
      const fullMessage = message.trim() + textBackLine(textBackTo);
      const assignees = team.map(t => ({ name: t.name.trim() || undefined, phone: t.phone.trim() })).filter(t => t.phone);
      const r = await sendBroadcast(recipients, fullMessage, assignees.length ? assignees : undefined, saveAsGroup.trim() || undefined);
      setResult(r);
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
          <div style={{ fontSize: 13, color: "#475569", margin: "2px 0 8px" }}>Tap a group to load its numbers below (combine several). Use 🗂 to file a group into a folder.</div>
          {groupsByFolder.map(([folder, gs]) => (
            <div key={folder || "_none"} style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: folder ? "#1d4ed8" : "#94a3b8", marginBottom: 4 }}>
                {folder ? `🗂 ${folder}` : "No folder"}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {gs.map(g => (
                  <span key={g.id} style={{ display: "inline-flex", alignItems: "center", gap: 4, border: "1px solid #cbd5e1", borderRadius: 999, padding: "4px 6px 4px 11px", background: "#fff" }}>
                    <button type="button" onClick={() => loadGroupInto(g)}
                      style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, fontWeight: 600, color: "#334155" }}>
                      {g.name} <span style={{ opacity: 0.6, fontWeight: 400 }}>· {g.count}</span>
                    </button>
                    <button type="button" title="What we messaged them" onClick={() => showHistory(g)}
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: 13 }}>📋</button>
                    <button type="button" title="Set folder" onClick={() => setGroupFolder(g)}
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#64748b", fontSize: 13 }}>🗂</button>
                    <button type="button" title="Delete group" onClick={() => removeGroup(g)}
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 13 }}>✕</button>
                  </span>
                ))}
              </div>
            </div>
          ))}

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
        placeholder="Your text message — sent exactly as written."
        rows={5}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4, marginBottom: 12 }}
      />

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
