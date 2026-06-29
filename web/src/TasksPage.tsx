import { useEffect, useMemo, useState } from "react";
import {
  checkShopPassword, getShopsPassword, clearShopsPassword,
  listTasks, addTask, updateTask, deleteTask,
  type Task, type ChecklistItem,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";

function fmtDate(iso: string) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

const MY_NAME_KEY = "tasks_my_name";

function TasksBoard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [show, setShow] = useState<"open" | "all" | "done">("open");

  // add-task form
  const [text, setText] = useState("");
  const [assignedTo, setAssignedTo] = useState("");
  const [myName, setMyName] = useState(() => localStorage.getItem(MY_NAME_KEY) || "");
  const [saving, setSaving] = useState(false);

  // inline edit
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  // per-task "add a part" inputs (checklist sub-items)
  const [itemInputs, setItemInputs] = useState<Record<number, string>>({});

  async function load() {
    try { setTasks(await listTasks()); }
    catch { setError("Couldn't load tasks."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  // Remember the user's name so they don't retype "from" each time.
  useEffect(() => { localStorage.setItem(MY_NAME_KEY, myName.trim()); }, [myName]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) { setError("Enter what needs to be done."); return; }
    setSaving(true); setError("");
    try {
      const created = await addTask(text.trim(), assignedTo.trim() || undefined, myName.trim() || undefined);
      setTasks(prev => [created, ...prev]);
      setText(""); setAssignedTo("");  // keep "from" so several tasks can be logged
    } catch { setError("Couldn't save the task."); }
    finally { setSaving(false); }
  }

  async function toggleDone(t: Task) {
    setTasks(prev => prev.map(x => x.id === t.id ? { ...x, done: !x.done } : x));
    try {
      const updated = await updateTask(t.id, { done: !t.done });
      setTasks(prev => prev.map(x => x.id === t.id ? updated : x));
    } catch { setError("Couldn't update the task."); load(); }
  }

  async function handleDelete(id: number) {
    if (!confirm("Delete this task?")) return;
    try { await deleteTask(id); setTasks(prev => prev.filter(t => t.id !== id)); }
    catch { setError("Couldn't delete the task."); }
  }

  function startEdit(t: Task) { setEditingId(t.id); setEditText(t.text); }
  async function saveEdit(id: number) {
    if (!editText.trim()) { setError("Task can't be empty."); return; }
    try {
      const updated = await updateTask(id, { text: editText.trim() });
      setTasks(prev => prev.map(t => t.id === id ? updated : t));
      setEditingId(null);
    } catch { setError("Couldn't update the task."); }
  }

  // --- Checklist (sub-parts of a task). Each part has its own checkbox and
  // stays visible when checked — it just gets struck through. ---
  async function saveChecklist(t: Task, items: ChecklistItem[]) {
    setTasks(prev => prev.map(x => x.id === t.id ? { ...x, checklist: items } : x));  // optimistic
    try {
      const updated = await updateTask(t.id, { checklist: items });
      setTasks(prev => prev.map(x => x.id === t.id ? updated : x));
    } catch { setError("Couldn't update the checklist."); load(); }
  }
  function toggleItem(t: Task, id: string) {
    saveChecklist(t, (t.checklist || []).map(i => i.id === id ? { ...i, done: !i.done } : i));
  }
  function deleteItem(t: Task, id: string) {
    saveChecklist(t, (t.checklist || []).filter(i => i.id !== id));
  }
  function addItem(t: Task) {
    const text = (itemInputs[t.id] || "").trim();
    if (!text) return;
    const id = (crypto as any).randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random());
    saveChecklist(t, [...(t.checklist || []), { id, text, done: false }]);
    setItemInputs(p => ({ ...p, [t.id]: "" }));
  }

  const assignees = useMemo(
    () => Array.from(new Set(tasks.map(t => (t.assigned_to || "").trim()).filter(Boolean)))
      .sort((a, b) => a.localeCompare(b)),
    [tasks],
  );

  const visible = useMemo(() => {
    const term = filter.trim().toLowerCase();
    let list = tasks;
    if (show === "open") list = list.filter(t => !t.done);
    else if (show === "done") list = list.filter(t => t.done);
    if (term) list = list.filter(t =>
      [t.text, t.assigned_to, t.created_by].join(" ").toLowerCase().includes(term));
    // Open tasks first (newest first), then completed (most recently done first).
    return [...list].sort((a, b) => {
      if (a.done !== b.done) return a.done ? 1 : -1;
      const ka = a.done ? (a.completed_at || a.created_at) : a.created_at;
      const kb = b.done ? (b.completed_at || b.created_at) : b.created_at;
      return kb.localeCompare(ka);
    });
  }, [tasks, filter, show]);

  const openCount = useMemo(() => tasks.filter(t => !t.done).length, [tasks]);

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 760 }}>
      <h1>Tasks</h1>
      <p className="subtitle">A shared to-do board for the team — add a task and assign it to whoever should handle it.</p>

      <div className="add-alert-box" style={{ marginTop: 20 }}>
        <div className="add-alert-title">+ Add a task</div>
        <form onSubmit={handleAdd}>
          <textarea className="add-alert-input" rows={2}
            placeholder="What needs to be done? (e.g. call back the LeBron seller, ship Jordan PSA 9)"
            value={text} onChange={e => setText(e.target.value)}
            style={{ width: "100%", resize: "vertical", lineHeight: 1.5, marginBottom: 10 }} />
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <input className="add-alert-input" list="task-assignees" placeholder="For (who should do it)"
              value={assignedTo} onChange={e => setAssignedTo(e.target.value)} style={{ flex: 1, minWidth: 150 }} />
            <input className="add-alert-input" placeholder="From (your name)"
              value={myName} onChange={e => setMyName(e.target.value)} style={{ flex: 1, minWidth: 150 }} />
            <datalist id="task-assignees">{assignees.map(a => <option key={a} value={a} />)}</datalist>
          </div>
          {error && <div className="error-msg" style={{ marginTop: 8 }}>{error}</div>}
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
            <button className="btn btn-sm" type="submit" disabled={saving}>{saving ? "Saving…" : "Add task"}</button>
          </div>
        </form>
      </div>

      <div className="alert-search-wrap" style={{ marginTop: 18 }}>
        <span className="alert-search-icon">🔎</span>
        <input className="alert-search-input" type="text" placeholder="Search tasks, people…"
          value={filter} onChange={e => setFilter(e.target.value)} />
        {filter && <button className="alert-search-clear" onClick={() => setFilter("")} title="Clear">✕</button>}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        {([["open", `📋 To do${openCount ? ` (${openCount})` : ""}`], ["all", "All"], ["done", "✅ Done"]] as const).map(([key, label]) => (
          <button key={key} onClick={() => setShow(key)}
            style={{ fontSize: 13, fontWeight: 600, padding: "5px 12px", borderRadius: 999, cursor: "pointer",
              border: show === key ? "1px solid #2563eb" : "1px solid #cbd5e1",
              background: show === key ? "#2563eb" : "#fff", color: show === key ? "#fff" : "#334155" }}>
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="subtitle" style={{ marginTop: 24 }}>Loading…</p>
      ) : visible.length === 0 ? (
        <div className="empty" style={{ marginTop: 32 }}>
          <p style={{ fontSize: 15 }}>
            {filter ? `No matches for "${filter}".`
              : show === "done" ? "Nothing completed yet."
              : "No tasks yet. Add the first one above."}
          </p>
        </div>
      ) : (
        <div style={{ marginTop: 18 }}>
          {visible.map(t => (
            <div key={t.id} className="alert-item" style={{ alignItems: "flex-start" }}>
              <div className="alert-item-left" style={{ alignItems: "flex-start", flex: 1, gap: 10 }}>
                <input type="checkbox" checked={t.done} onChange={() => toggleDone(t)}
                  title={t.done ? "Mark as not done" : "Mark as done"}
                  style={{ width: 18, height: 18, marginTop: 3, cursor: "pointer", flexShrink: 0 }} />
                <div style={{ flex: 1 }}>
                  {editingId === t.id ? (
                    <div>
                      <textarea className="add-alert-input" rows={2} value={editText}
                        onChange={e => setEditText(e.target.value)}
                        style={{ width: "100%", resize: "vertical", lineHeight: 1.5 }} />
                      <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                        <button className="btn btn-sm" onClick={() => saveEdit(t.id)}>Save</button>
                        <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.1)" }} onClick={() => setEditingId(null)}>Cancel</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.5,
                        textDecoration: t.done ? "line-through" : "none", opacity: t.done ? 0.55 : 1 }}>
                        {t.text}
                      </div>
                      <div style={{ fontSize: 12, opacity: 0.6, marginTop: 3, display: "flex", gap: 10, flexWrap: "wrap" }}>
                        {t.assigned_to && <span>👤 for {t.assigned_to}</span>}
                        {t.created_by && <span>✍️ from {t.created_by}</span>}
                        <span>{fmtDate(t.created_at)}</span>
                        {t.done && t.completed_at && <span>✅ done {fmtDate(t.completed_at)}</span>}
                      </div>

                      {/* Checklist of sub-parts — each has its own checkbox and
                          stays visible (struck through) when checked. */}
                      {(t.checklist && t.checklist.length > 0) && (
                        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
                          {t.checklist.map(item => (
                            <div key={item.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 14 }}>
                              <input type="checkbox" checked={item.done} onChange={() => toggleItem(t, item.id)}
                                style={{ width: 15, height: 15, marginTop: 3, cursor: "pointer", flexShrink: 0 }} />
                              <span style={{ flex: 1, lineHeight: 1.4, whiteSpace: "pre-wrap",
                                textDecoration: item.done ? "line-through" : "none", opacity: item.done ? 0.55 : 1 }}>
                                {item.text}
                              </span>
                              <button className="alert-remove-btn" onClick={() => deleteItem(t, item.id)}
                                title="Delete part" style={{ flexShrink: 0 }}>✕</button>
                            </div>
                          ))}
                        </div>
                      )}

                      <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "center" }}>
                        <input className="add-alert-input" placeholder="+ add a part"
                          value={itemInputs[t.id] || ""}
                          onChange={e => setItemInputs(p => ({ ...p, [t.id]: e.target.value }))}
                          onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addItem(t); } }}
                          style={{ flex: 1, minWidth: 120, fontSize: 13, padding: "5px 9px" }} />
                        <button className="btn btn-sm" type="button" onClick={() => addItem(t)}>Add</button>
                      </div>
                    </>
                  )}
                </div>
              </div>
              {editingId !== t.id && (
                <div className="alert-item-actions">
                  <button className="alert-edit-btn" onClick={() => startEdit(t)} title="Edit task">✎</button>
                  <button className="alert-remove-btn" onClick={() => handleDelete(t.id)} title="Delete task">✕</button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function TasksPage() {
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
    return <ShopPasswordForm title="Tasks" onUnlocked={() => setUnlocked(true)} />;
  }

  return <TasksBoard />;
}
