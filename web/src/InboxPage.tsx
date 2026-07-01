import { useEffect, useRef, useState } from "react";
import {
  checkShopPassword, getShopsPassword, clearShopsPassword,
  listConversations, getConversation, sendConversationReply, assignConversation, deleteConversation,
  listBroadcastGroups, createBroadcastGroup, addToBroadcastGroup,
  type SmsConversation, type SmsMessage, type BroadcastGroup,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";

const MY_NAME_KEY = "tasks_my_name";

function fmt(iso?: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function Inbox() {
  const [convos, setConvos] = useState<SmsConversation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [thread, setThread] = useState<{ conversation: SmsConversation; messages: SmsMessage[] } | null>(null);
  const [reply, setReply] = useState("");
  const [me, setMe] = useState(() => localStorage.getItem(MY_NAME_KEY) || "");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [editAssign, setEditAssign] = useState(false);
  const [aName, setAName] = useState("");
  const [aPhone, setAPhone] = useState("");
  const [showGroupPicker, setShowGroupPicker] = useState(false);
  const [groups, setGroups] = useState<BroadcastGroup[]>([]);
  const [newGroup, setNewGroup] = useState("");
  const [groupMsg, setGroupMsg] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  async function openGroupPicker() {
    setGroupMsg(""); setNewGroup("");
    try { setGroups(await listBroadcastGroups()); } catch {}
    setShowGroupPicker(true);
  }
  async function addToGroup(g: BroadcastGroup) {
    if (!selected) return;
    try {
      const r = await addToBroadcastGroup(g.id, selected);
      setGroupMsg(r.added ? `Added to "${g.name}".` : `Already in "${g.name}".`);
    } catch { setGroupMsg("Couldn't add to that group."); }
  }
  async function addToNewGroup() {
    if (!selected || !newGroup.trim()) return;
    try {
      const g = await createBroadcastGroup(newGroup.trim(), selected);
      setGroupMsg(`Created "${g.name}" and added this number.`);
      setNewGroup("");
      setGroups(await listBroadcastGroups());
    } catch { setGroupMsg("Couldn't create that group."); }
  }

  useEffect(() => { localStorage.setItem(MY_NAME_KEY, me.trim()); }, [me]);

  async function loadConvos() {
    try { setConvos(await listConversations()); }
    catch { setError("Couldn't load the inbox."); }
    finally { setLoading(false); }
  }
  async function openThread(phone: string) {
    setSelected(phone);
    setShowGroupPicker(false); setGroupMsg("");
    try {
      const t = await getConversation(phone);
      setThread(t);
      setConvos(prev => prev.map(c => c.phone === phone ? { ...c, unread: 0 } : c));
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    } catch { setError("Couldn't load that conversation."); }
  }

  useEffect(() => { loadConvos(); }, []);
  // Live refresh: poll the list + the open thread every 20s.
  useEffect(() => {
    const id = setInterval(async () => {
      loadConvos();
      if (selected) {
        try { setThread(await getConversation(selected)); } catch {}
      }
    }, 20000);
    return () => clearInterval(id);
  }, [selected]);

  async function send() {
    const body = reply.trim();
    if (!body || !selected) return;
    setSending(true); setError("");
    try {
      await sendConversationReply(selected, body, me.trim() || undefined);
      setReply("");
      await openThread(selected);
      loadConvos();
    } catch { setError("Couldn't send — check the Twilio balance/number."); }
    finally { setSending(false); }
  }

  async function handleDelete(phone: string) {
    if (!confirm("Delete this conversation and all its messages?")) return;
    try {
      await deleteConversation(phone);
      setConvos(prev => prev.filter(c => c.phone !== phone));
      if (selected === phone) { setSelected(null); setThread(null); }
    } catch { setError("Couldn't delete the conversation."); }
  }

  async function saveAssign() {
    if (!selected) return;
    try {
      await assignConversation(selected, { assignees: aPhone.trim() ? [{ name: aName.trim() || undefined, phone: aPhone.trim() }] : [] });
      setEditAssign(false);
      await openThread(selected);
      loadConvos();
    } catch { setError("Couldn't update assignment."); }
  }

  const totalUnread = convos.reduce((n, c) => n + (c.unread || 0), 0);

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 960 }}>
      <h1>Inbox {totalUnread > 0 && <span style={{ fontSize: 14, color: "#dc2626" }}>· {totalUnread} unread</span>}</h1>
      <p className="subtitle">Replies to the 877 broadcast line. Open a conversation and answer — it goes back out through the 877.</p>

      <div style={{ marginTop: 12, marginBottom: 14, display: "flex", gap: 8, alignItems: "center" }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Your name:</span>
        <input className="add-alert-input" value={me} onChange={e => setMe(e.target.value)} placeholder="(used to sign your replies)"
          style={{ width: 200, fontSize: 13, padding: "5px 9px" }} />
      </div>

      {error && <div className="error-msg" style={{ marginBottom: 10 }}>{error}</div>}

      {loading ? (
        <p className="subtitle">Loading…</p>
      ) : convos.length === 0 ? (
        <div className="empty" style={{ marginTop: 24 }}>
          <p style={{ fontSize: 15 }}>No conversations yet. Send a Broadcast with a follow-up teammate assigned, and replies will land here.</p>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
          {/* Conversation list */}
          <div style={{ flex: "1 1 280px", minWidth: 260, maxWidth: 360 }}>
            {convos.map(c => {
              const sel = selected === c.phone, unread = c.unread > 0;
              return (
              <div key={c.phone} onClick={() => openThread(c.phone)}
                style={{ cursor: "pointer", padding: "11px 13px", borderRadius: 12, marginBottom: 8,
                  color: sel ? "#fff" : "#0f172a", transition: "all .12s",
                  border: "2px solid", borderColor: sel ? "#6d28d9" : unread ? "#3b82f6" : "#e2e8f0",
                  background: sel ? "linear-gradient(135deg,#2563eb,#7c3aed)" : unread ? "#eef2ff" : "#fff",
                  boxShadow: sel ? "0 6px 16px rgba(109,40,217,0.40)" : unread ? "0 2px 10px rgba(59,130,246,0.20)" : "none" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                  <strong style={{ fontSize: 14 }}>{c.name || c.phone}</strong>
                  <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    {c.unread > 0 && <span style={{ fontSize: 11, fontWeight: 700, color: "#fff", background: "#dc2626", borderRadius: 999, padding: "1px 7px" }}>{c.unread}</span>}
                    <button className="alert-remove-btn" title="Delete conversation"
                      onClick={(e) => { e.stopPropagation(); handleDelete(c.phone); }}>✕</button>
                  </span>
                </div>
                <div style={{ fontSize: 12, opacity: 0.7, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {c.last_direction === "in" ? "↩︎ " : "→ "}{c.last_preview}
                </div>
                <div style={{ fontSize: 11, opacity: 0.55, marginTop: 2 }}>
                  {c.assigned_to ? `👤 ${c.assigned_to}` : "unassigned"} · {fmt(c.last_at)}
                </div>
              </div>
            ); })}
          </div>

          {/* Thread */}
          <div style={{ flex: "2 1 380px", minWidth: 300 }}>
            {!thread ? (
              <div className="subtitle" style={{ padding: 20 }}>Select a conversation.</div>
            ) : (
              <div style={{ border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14, padding: 14, background: "#211d3f", color: "#e2e8f0",
                boxShadow: "0 8px 24px rgba(15,23,42,0.35)" }}>
                <div style={{ background: "linear-gradient(135deg,#2563eb,#7c3aed)", color: "#fff",
                  margin: "-14px -14px 12px", padding: "13px 15px", borderRadius: "14px 14px 0 0",
                  display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 16 }}>{thread.conversation.name || thread.conversation.phone}</div>
                    <div style={{ fontSize: 12, opacity: 0.9 }}>{thread.conversation.phone}</div>
                  </div>
                  <div style={{ fontSize: 12, color: "#fff" }}>
                    {editAssign ? (
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <input className="add-alert-input" placeholder="assignee name" value={aName} onChange={e => setAName(e.target.value)} style={{ width: 120, fontSize: 12, padding: "4px 7px" }} />
                        <input className="add-alert-input" placeholder="phone" value={aPhone} onChange={e => setAPhone(e.target.value)} style={{ width: 120, fontSize: 12, padding: "4px 7px" }} />
                        <button className="btn btn-sm" onClick={saveAssign}>Save</button>
                      </div>
                    ) : (
                      <span style={{ background: "rgba(255,255,255,0.18)", padding: "3px 10px", borderRadius: 999 }}>
                        👤 {thread.conversation.assigned_to || "unassigned"}{" "}
                        <button title="Reassign" style={{ background: "none", border: "none", color: "#fff", cursor: "pointer" }}
                          onClick={() => { setAName(thread.conversation.assigned_to || ""); setAPhone(thread.conversation.assignee_phone || ""); setEditAssign(true); }}>✎</button>
                      </span>
                    )}
                  </div>
                </div>

                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", margin: "2px 0 10px" }}>
                  <button className="btn btn-sm" type="button" style={{ background: "rgba(255,255,255,0.1)", color: "#e2e8f0" }}
                    onClick={() => (showGroupPicker ? setShowGroupPicker(false) : openGroupPicker())}>
                    {showGroupPicker ? "Close" : "📂 Add to group"}
                  </button>
                  {groupMsg && <span style={{ fontSize: 12, color: "#15803d" }}>{groupMsg}</span>}
                </div>
                {showGroupPicker && (
                  <div style={{ border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, padding: 10, marginBottom: 10, background: "rgba(255,255,255,0.04)" }}>
                    <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>Save this number to a broadcast group:</div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                      {groups.length === 0 && <span style={{ fontSize: 13, opacity: 0.6 }}>No groups yet — make one below.</span>}
                      {groups.map(g => (
                        <button key={g.id} type="button" className="btn btn-sm" style={{ background: "#fff", color: "#334155", border: "1px solid #cbd5e1" }}
                          onClick={() => addToGroup(g)}>+ {g.name} <span style={{ opacity: 0.5 }}>· {g.count}</span></button>
                      ))}
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <input className="add-alert-input" placeholder="New group name" value={newGroup}
                        onChange={e => setNewGroup(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addToNewGroup(); } }}
                        style={{ flex: 1, fontSize: 13, padding: "6px 9px" }} />
                      <button className="btn btn-sm" type="button" disabled={!newGroup.trim()} onClick={addToNewGroup}>Create + add</button>
                    </div>
                  </div>
                )}

                <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 420, overflowY: "auto", padding: "8px 2px" }}>
                  {thread.messages.map(m => (
                    <div key={m.id} style={{ alignSelf: m.direction === "in" ? "flex-start" : "flex-end", maxWidth: "80%" }}>
                      <div style={{ fontSize: 14, lineHeight: 1.4, whiteSpace: "pre-wrap", padding: "9px 12px", borderRadius: 14,
                        background: m.direction === "in" ? "#eef2ff" : "linear-gradient(135deg,#2563eb,#7c3aed)",
                        color: m.direction === "in" ? "#0f172a" : "#fff",
                        border: m.direction === "in" ? "1px solid #c7d2fe" : "none",
                        boxShadow: m.direction === "in" ? "none" : "0 3px 10px rgba(109,40,217,0.3)" }}>
                        {m.body}
                      </div>
                      <div style={{ fontSize: 10, opacity: 0.5, marginTop: 2, textAlign: m.direction === "in" ? "left" : "right" }}>
                        {m.direction === "out" && m.sender ? `${m.sender} · ` : ""}{fmt(m.created_at)}
                      </div>
                    </div>
                  ))}
                  <div ref={bottomRef} />
                </div>

                <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                  <textarea className="add-alert-input" rows={2} placeholder="Type a reply… (sends from the 877)"
                    value={reply} onChange={e => setReply(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } }}
                    style={{ flex: 1, resize: "vertical", lineHeight: 1.4 }} />
                  <button className="btn btn-sm" disabled={sending || !reply.trim()} onClick={send}>{sending ? "…" : "Send"}</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function InboxPage() {
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
  if (!unlocked) return <ShopPasswordForm title="Inbox" onUnlocked={() => setUnlocked(true)} />;
  return <Inbox />;
}
