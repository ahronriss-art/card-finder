import { useState, useEffect } from "react";
import { createUser, saveSearch, getSavedSearches, deleteSearch } from "./api/client";

export default function AlertsPage() {
  const [userId, setUserId] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [alertMethod, setAlertMethod] = useState<"email" | "sms" | "both">("email");
  const [searches, setSearches] = useState<any[]>([]);
  const [newQuery, setNewQuery] = useState("");
  const [onboarded, setOnboarded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const id = localStorage.getItem("userId");
    if (id) {
      setUserId(Number(id));
      setOnboarded(true);
      loadSearches(Number(id));
    }
  }, []);

  async function loadSearches(id: number) {
    try {
      const data = await getSavedSearches(id);
      setSearches(data);
    } catch {}
  }

  async function handleOnboard(e: React.FormEvent) {
    e.preventDefault();
    if (!email && !phone) { setError("Enter an email or phone number."); return; }
    setSaving(true);
    setError("");
    try {
      const user = await createUser(email || undefined, phone || undefined, alertMethod);
      localStorage.setItem("userId", String(user.id));
      setUserId(user.id);
      setOnboarded(true);
    } catch {
      setError("Could not save. Check your connection.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!newQuery.trim() || !userId) return;
    await saveSearch(userId, newQuery.trim());
    setNewQuery("");
    loadSearches(userId);
  }

  async function handleDelete(id: number) {
    await deleteSearch(id);
    setSearches(prev => prev.filter(s => s.id !== id));
  }

  if (!onboarded) {
    return (
      <div className="app" style={{ paddingTop: 32, maxWidth: 520 }}>
        <h1>Set Up Alerts</h1>
        <p className="subtitle">Get notified by SMS or email when a card you're watching gets listed or sold.</p>

        <form onSubmit={handleOnboard}>
          <div className="form-group">
            <label>Email</label>
            <input type="email" placeholder="you@email.com" value={email} onChange={e => setEmail(e.target.value)} />
          </div>
          <div className="form-group">
            <label>Phone (for SMS alerts)</label>
            <input type="tel" placeholder="+1 555-555-5555" value={phone} onChange={e => setPhone(e.target.value)} />
          </div>
          <div className="form-group">
            <label>How should we alert you?</label>
            <div className="method-row">
              {(["email", "sms", "both"] as const).map(m => (
                <button key={m} type="button" className={`method-chip${alertMethod === m ? " active" : ""}`} onClick={() => setAlertMethod(m)}>
                  {m.toUpperCase()}
                </button>
              ))}
            </div>
          </div>
          {error && <div className="error-msg">{error}</div>}
          <button className="btn" type="submit" disabled={saving} style={{ width: "100%" }}>
            {saving ? "Saving..." : "Save & Enable Alerts"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="app" style={{ paddingTop: 32 }}>
      <h1>My Alerts</h1>
      <p className="subtitle">You'll get notified when new listings match your saved searches.</p>

      <form className="add-row" onSubmit={handleAddSearch}>
        <input
          type="text"
          placeholder="Add a card to watch (e.g. Patrick Mahomes Rookie PSA 10)"
          value={newQuery}
          onChange={e => setNewQuery(e.target.value)}
        />
        <button className="btn" type="submit">+ Add</button>
      </form>

      {searches.length === 0 ? (
        <div className="empty">
          <div style={{ fontSize: 48, marginBottom: 12 }}>🔔</div>
          <p>No saved searches yet. Add a card above to start getting alerts.</p>
        </div>
      ) : (
        searches.map(s => (
          <div className="saved-item" key={s.id}>
            <div>
              <div className="saved-item-query">{s.query}</div>
              {s.sport && <div className="saved-item-meta">{s.sport}</div>}
            </div>
            <button className="btn btn-sm btn-danger" onClick={() => handleDelete(s.id)}>Remove</button>
          </div>
        ))
      )}
    </div>
  );
}
