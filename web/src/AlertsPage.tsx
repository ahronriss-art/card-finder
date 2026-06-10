import { useState, useEffect } from "react";
import { createUser, updateUser, saveSearch, updateSearch, getSavedSearches, deleteSearch } from "./api/client";

const SPORTS = ["Any", "NBA", "NFL", "MLB", "NHL", "Pokemon", "UFC", "Soccer"];

const INTERVALS = [
  { label: "30 sec", minutes: 0.5 },
  { label: "1 min", minutes: 1 },
  { label: "2 min", minutes: 2 },
  { label: "5 min", minutes: 5 },
  { label: "10 min", minutes: 10 },
  { label: "15 min", minutes: 15 },
  { label: "30 min", minutes: 30 },
  { label: "1 hour", minutes: 60 },
  { label: "3 hours", minutes: 180 },
  { label: "6 hours", minutes: 360 },
  { label: "12 hours", minutes: 720 },
  { label: "Once a day", minutes: 1440 },
];

function intervalLabel(minutes: number): string {
  const match = INTERVALS.find(i => i.minutes === minutes);
  if (match) return match.label;
  if (minutes < 1) return `${Math.round(minutes * 60)} sec`;
  if (minutes < 60) return `${minutes} min`;
  if (minutes < 1440) return `${Math.round(minutes / 60)}h`;
  return `${Math.round(minutes / 1440)}d`;
}

type Method = "email" | "sms" | "both";

type AlertSubmit = {
  query: string;
  sport: string; // "Any" or a sport name
  minPrice?: number;
  maxPrice?: number;
  numberedTo?: number;
  intervalMins: number;
  method: Method;
};

type AlertFormInitial = {
  query?: string;
  sport?: string;
  minPrice?: string;
  maxPrice?: string;
  numberedTo?: string;
  intervalMinutes?: number;
  method?: Method;
};

// Shared form used for both adding a new alert and editing an existing one.
function AlertForm({
  initial,
  submitLabel,
  busy,
  onSubmit,
  onCancel,
}: {
  initial?: AlertFormInitial;
  submitLabel: string;
  busy: boolean;
  onSubmit: (v: AlertSubmit) => void;
  onCancel?: () => void;
}) {
  const initMinutes = initial?.intervalMinutes ?? 15;
  const preset = INTERVALS.find(i => i.minutes === initMinutes);

  const [query, setQuery] = useState(initial?.query ?? "");
  const [sport, setSport] = useState(initial?.sport ?? "Any");
  const [minPrice, setMinPrice] = useState(initial?.minPrice ?? "");
  const [maxPrice, setMaxPrice] = useState(initial?.maxPrice ?? "");
  const [numberedTo, setNumberedTo] = useState(initial?.numberedTo ?? "");
  const [intervalMin, setIntervalMin] = useState(preset ? initMinutes : 15);
  const [useCustom, setUseCustom] = useState(!preset);
  const [customInterval, setCustomInterval] = useState(
    preset ? "" : (initMinutes < 1 ? String(Math.round(initMinutes * 60)) : String(initMinutes))
  );
  const [customUnit, setCustomUnit] = useState<"seconds" | "minutes">(initMinutes < 1 ? "seconds" : "minutes");
  const [method, setMethod] = useState<Method>(initial?.method ?? "both");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    const rawVal = parseFloat(customInterval) || 15;
    const intervalMins = useCustom
      ? Math.max(0.5, Math.min(1440, customUnit === "seconds" ? rawVal / 60 : rawVal))
      : intervalMin;
    onSubmit({
      query: query.trim(),
      sport,
      minPrice: minPrice ? parseFloat(minPrice) : undefined,
      maxPrice: maxPrice ? parseFloat(maxPrice) : undefined,
      numberedTo: numberedTo ? parseInt(numberedTo, 10) : undefined,
      intervalMins,
      method,
    });
  }

  return (
    <form onSubmit={handleSubmit}>
      <input
        className="add-alert-input"
        type="text"
        placeholder="e.g. LeBron James Rookie PSA 10, Charizard Base Set, Mahomes Auto..."
        value={query}
        onChange={e => setQuery(e.target.value)}
      />

      {/* Sport filter */}
      <div className="interval-label-row">
        <span className="interval-section-label">Sport</span>
      </div>
      <div className="add-sport-row" style={{ marginBottom: 14 }}>
        {SPORTS.map(s => (
          <button
            key={s} type="button"
            className={`chip${sport === s ? " active" : ""}`}
            style={{ fontSize: 12, padding: "5px 12px" }}
            onClick={() => setSport(s)}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Price range filter */}
      <div className="interval-label-row">
        <span className="interval-section-label">Price range (optional)</span>
      </div>
      <div className="price-range-row" style={{ marginBottom: 14 }}>
        <div className="price-input-wrap">
          <span className="price-dollar">$</span>
          <input
            type="number" min="0" className="price-input"
            placeholder="Min" value={minPrice}
            onChange={e => setMinPrice(e.target.value)}
          />
        </div>
        <span className="price-dash">–</span>
        <div className="price-input-wrap">
          <span className="price-dollar">$</span>
          <input
            type="number" min="0" className="price-input"
            placeholder="Max" value={maxPrice}
            onChange={e => setMaxPrice(e.target.value)}
          />
        </div>
      </div>

      {/* Serial-numbered filter */}
      <div className="interval-label-row">
        <span className="interval-section-label">Numbered to (optional)</span>
      </div>
      <div className="numbered-row" style={{ marginBottom: 14 }}>
        <span className="numbered-slash">/</span>
        <input
          type="number" min="1" className="numbered-input"
          placeholder="e.g. 99" value={numberedTo}
          onChange={e => setNumberedTo(e.target.value)}
        />
        <span className="numbered-hint">Only alert for cards serial-numbered to this print run (e.g. /99). Leave blank for any.</span>
      </div>

      {/* Alert frequency */}
      <div className="interval-label-row">
        <span className="interval-section-label">Alert me every</span>
      </div>
      <div className="interval-chips">
        {INTERVALS.map(i => (
          <button
            key={i.minutes} type="button"
            className={`chip${!useCustom && intervalMin === i.minutes ? " active" : ""}`}
            style={{ fontSize: 12, padding: "5px 12px" }}
            onClick={() => { setIntervalMin(i.minutes); setUseCustom(false); }}
          >
            {i.label}
          </button>
        ))}
        <button
          type="button"
          className={`chip${useCustom ? " active" : ""}`}
          style={{ fontSize: 12, padding: "5px 12px" }}
          onClick={() => setUseCustom(true)}
        >
          Custom
        </button>
      </div>

      {useCustom && (
        <div className="custom-interval-row">
          <input
            type="number"
            className="custom-interval-input"
            placeholder={customUnit === "seconds" ? "e.g. 30, 90" : "e.g. 5, 45"}
            min={customUnit === "seconds" ? 30 : 1}
            max={customUnit === "seconds" ? 3600 : 1440}
            step={1}
            value={customInterval}
            onChange={e => setCustomInterval(e.target.value)}
          />
          <div className="unit-toggle">
            <button
              type="button"
              className={`unit-btn${customUnit === "seconds" ? " active" : ""}`}
              onClick={() => setCustomUnit("seconds")}
            >sec</button>
            <button
              type="button"
              className={`unit-btn${customUnit === "minutes" ? " active" : ""}`}
              onClick={() => setCustomUnit("minutes")}
            >min</button>
          </div>
        </div>
      )}

      {/* Delivery method for this alert */}
      <div className="interval-label-row" style={{ marginTop: 14 }}>
        <span className="interval-section-label">Notify me by</span>
      </div>
      <div className="interval-chips">
        {([
          { key: "both", icon: "🔔", label: "Email + SMS" },
          { key: "email", icon: "✉️", label: "Email only" },
          { key: "sms", icon: "💬", label: "SMS only" },
        ] as const).map(m => (
          <button
            key={m.key} type="button"
            className={`chip${method === m.key ? " active" : ""}`}
            style={{ fontSize: 12, padding: "5px 12px" }}
            onClick={() => setMethod(m.key)}
          >
            {m.icon} {m.label}
          </button>
        ))}
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 14 }}>
        {onCancel && (
          <button
            className="btn btn-sm" type="button"
            style={{ background: "rgba(255,255,255,0.1)" }}
            onClick={onCancel}
          >
            Cancel
          </button>
        )}
        <button className="btn btn-sm" type="submit" disabled={busy || !query.trim()}>
          {busy ? "Saving..." : submitLabel}
        </button>
      </div>
    </form>
  );
}

export default function AlertsPage() {
  const [userId, setUserId] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [alertMethod, setAlertMethod] = useState<Method>("email");
  const [searches, setSearches] = useState<any[]>([]);
  const [onboarded, setOnboarded] = useState(false);
  const [accountLabel, setAccountLabel] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [settingsEmail, setSettingsEmail] = useState("");
  const [settingsPhone, setSettingsPhone] = useState("");
  const [settingsMethod, setSettingsMethod] = useState<Method>("email");
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addFormKey, setAddFormKey] = useState(0); // bump to reset the add form
  const [editingId, setEditingId] = useState<number | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    const id = localStorage.getItem("userId");
    const label = localStorage.getItem("accountLabel") || "";
    if (id) {
      setUserId(Number(id));
      setAccountLabel(label);
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

  function handleLogout() {
    localStorage.removeItem("userId");
    localStorage.removeItem("accountLabel");
    setUserId(null);
    setAccountLabel("");
    setOnboarded(false);
    setSearches([]);
    setEmail("");
    setPhone("");
    setAlertMethod("email");
    setSuccess("");
    setError("");
  }

  async function handleOnboard(e: React.FormEvent) {
    e.preventDefault();
    if (!email && !phone) { setError("Please enter at least an email or phone number."); return; }
    if (alertMethod === "email" && !email) { setError("Enter an email address for email alerts."); return; }
    if (alertMethod === "sms" && !phone) { setError("Enter a phone number for SMS alerts."); return; }
    setSaving(true);
    setError("");
    try {
      const user = await createUser(email || undefined, phone || undefined, alertMethod);
      const label = email || phone || "";
      localStorage.setItem("userId", String(user.id));
      localStorage.setItem("accountLabel", label);
      setUserId(user.id);
      setAccountLabel(label);
      setOnboarded(true);
      setSuccess("You're signed in! Your alerts are private to this account.");
    } catch {
      setError("Could not save. Make sure the backend is running.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddSearch(v: AlertSubmit) {
    if (!userId) return;
    setAdding(true);
    try {
      await saveSearch(userId, v.query, v.sport === "Any" ? undefined : v.sport, v.intervalMins, v.method, v.minPrice, v.maxPrice, v.numberedTo);
      setAddFormKey(k => k + 1); // reset the add form
      setSuccess(`Alert added — checking every ${intervalLabel(v.intervalMins)}`);
      setTimeout(() => setSuccess(""), 3000);
      loadSearches(userId);
    } catch {
      setError("Could not add alert.");
    } finally {
      setAdding(false);
    }
  }

  async function handleEditSearch(id: number, v: AlertSubmit) {
    if (!userId) return;
    setSavingEdit(true);
    try {
      await updateSearch(id, v.query, v.sport === "Any" ? undefined : v.sport, v.intervalMins, v.method, v.minPrice, v.maxPrice, v.numberedTo);
      setEditingId(null);
      setSuccess(`Alert updated for "${v.query}"`);
      setTimeout(() => setSuccess(""), 3000);
      loadSearches(userId);
    } catch {
      setError("Could not update alert.");
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleDelete(id: number, query: string) {
    await deleteSearch(id);
    setSearches(prev => prev.filter(s => s.id !== id));
    if (editingId === id) setEditingId(null);
    setSuccess(`Removed alert for "${query}"`);
    setTimeout(() => setSuccess(""), 3000);
  }

  if (!onboarded) {
    return (
      <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 560 }}>
        <h1>Card Alerts</h1>
        <p className="subtitle">Sign in with your email or phone to set up your own private alerts. Returning? Enter the same email to access your saved alerts.</p>

        <div className="alert-how-it-works">
          <div className="how-step">
            <div className="how-icon">📋</div>
            <div>
              <div className="how-title">1. Sign in with your email or phone</div>
              <div className="how-desc">Your alerts are private to your account</div>
            </div>
          </div>
          <div className="how-step">
            <div className="how-icon">🔍</div>
            <div>
              <div className="how-title">2. Add cards to watch</div>
              <div className="how-desc">Search by player, set, grade — anything</div>
            </div>
          </div>
          <div className="how-step">
            <div className="how-icon">🔔</div>
            <div>
              <div className="how-title">3. Get alerted instantly</div>
              <div className="how-desc">We check eBay every 15 minutes for new listings</div>
            </div>
          </div>
        </div>

        <form onSubmit={handleOnboard} style={{ marginTop: 32 }}>
          <div className="form-group">
            <label>Email Address</label>
            <input
              type="email" placeholder="you@email.com"
              value={email} onChange={e => setEmail(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>Phone Number (for SMS)</label>
            <input
              type="tel" placeholder="+1 (555) 555-5555"
              value={phone} onChange={e => setPhone(e.target.value)}
            />
            <p className="sms-consent">
              By entering your number and choosing SMS, you agree to receive recurring automated card alert texts from Card Finder.
              Msg &amp; data rates may apply. Reply STOP to unsubscribe, HELP for help.
              See our <a href="/privacy.html" target="_blank" rel="noreferrer">Privacy Policy &amp; SMS Terms</a>.
            </p>
          </div>

          <div className="form-group">
            <label>How do you want to be alerted?</label>
            <div className="method-row">
              {[
                { key: "email", icon: "✉️", label: "Email" },
                { key: "sms", icon: "💬", label: "SMS" },
                { key: "both", icon: "🔔", label: "Both" },
              ].map(m => (
                <button
                  key={m.key} type="button"
                  className={`method-chip${alertMethod === m.key ? " active" : ""}`}
                  onClick={() => setAlertMethod(m.key as any)}
                >
                  {m.icon} {m.label}
                </button>
              ))}
            </div>
          </div>

          {error && <div className="error-msg">{error}</div>}

          <button className="btn" type="submit" disabled={saving} style={{ width: "100%", marginTop: 8 }}>
            {saving ? "Setting up..." : "Enable Alerts →"}
          </button>
        </form>
      </div>
    );
  }

  async function handleUpdateSettings(e: React.FormEvent) {
    e.preventDefault();
    if (!userId) return;
    setSaving(true);
    try {
      await updateUser(userId, settingsEmail || undefined, settingsPhone || undefined, settingsMethod);
      setAlertMethod(settingsMethod);
      setShowSettings(false);
      setSuccess("Alert settings updated!");
      setTimeout(() => setSuccess(""), 3000);
    } catch {
      setError("Could not update settings.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <h1>My Alerts</h1>
          <p className="subtitle">Your private alerts — we check eBay and notify only you when a match is found.</p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
          <button
            className="alert-method-badge"
            style={{ cursor: "pointer", background: "rgba(249,115,22,0.15)", border: "1px solid rgba(249,115,22,0.3)" }}
            onClick={() => { setShowSettings(v => !v); setSettingsMethod(alertMethod as any); }}
          >
            {alertMethod === "email" ? "✉️ Email" : alertMethod === "sms" ? "💬 SMS" : "🔔 Both"} · Edit
          </button>
          {accountLabel && (
            <div className="account-row">
              <span className="account-label">{accountLabel}</span>
              <button className="logout-btn" onClick={handleLogout}>Log out</button>
            </div>
          )}
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <div className="settings-panel">
          <div className="add-alert-title">Alert Settings</div>
          <form onSubmit={handleUpdateSettings}>
            <div className="form-group">
              <label>Email</label>
              <input type="email" placeholder="you@email.com" value={settingsEmail} onChange={e => setSettingsEmail(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Phone (for SMS)</label>
              <input type="tel" placeholder="+1 (555) 555-5555" value={settingsPhone} onChange={e => setSettingsPhone(e.target.value)} />
            </div>
            <div className="form-group">
              <label>Alert method</label>
              <div className="method-row">
                {([
                  { key: "email", icon: "✉️", label: "Email" },
                  { key: "sms", icon: "💬", label: "SMS" },
                  { key: "both", icon: "🔔", label: "Both" },
                ] as const).map(m => (
                  <button key={m.key} type="button"
                    className={`method-chip${settingsMethod === m.key ? " active" : ""}`}
                    onClick={() => setSettingsMethod(m.key as any)}>
                    {m.icon} {m.label}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <button className="btn btn-sm" type="submit" disabled={saving}>{saving ? "Saving..." : "Save"}</button>
              <button className="btn btn-sm" type="button" style={{ background: "rgba(255,255,255,0.1)" }} onClick={() => setShowSettings(false)}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      {success && <div className="success-msg">{success}</div>}
      {error && <div className="error-msg">{error}</div>}

      {/* Add new alert */}
      <div className="add-alert-box">
        <div className="add-alert-title">+ Add a Card to Watch</div>
        <AlertForm
          key={addFormKey}
          submitLabel="Add Alert"
          busy={adding}
          onSubmit={handleAddSearch}
        />
      </div>

      {/* Saved alerts list */}
      {searches.length === 0 ? (
        <div className="empty" style={{ marginTop: 40 }}>
          <div style={{ fontSize: 56, marginBottom: 16 }}>🔔</div>
          <p style={{ fontSize: 16, marginBottom: 8 }}>No alerts set up yet.</p>
          <p style={{ fontSize: 13 }}>Add a card above and we'll text or email you the moment it lists on eBay.</p>
        </div>
      ) : (
        <div style={{ marginTop: 8 }}>
          <div className="alerts-list-header">
            {searches.length} active alert{searches.length !== 1 ? "s" : ""}
          </div>
          {searches.map(s => (
            editingId === s.id ? (
              <div className="alert-edit-box" key={s.id}>
                <div className="add-alert-title">Edit Alert</div>
                <AlertForm
                  initial={{
                    query: s.query,
                    sport: s.sport || "Any",
                    minPrice: s.min_price != null ? String(s.min_price) : "",
                    maxPrice: s.max_price != null ? String(s.max_price) : "",
                    numberedTo: s.numbered_to != null ? String(s.numbered_to) : "",
                    intervalMinutes: s.check_interval_minutes || 15,
                    method: s.alert_method || "both",
                  }}
                  submitLabel="Save Changes"
                  busy={savingEdit}
                  onSubmit={v => handleEditSearch(s.id, v)}
                  onCancel={() => setEditingId(null)}
                />
              </div>
            ) : (
              <div className="alert-item" key={s.id}>
                <div className="alert-item-left">
                  <div className="alert-item-icon">🔔</div>
                  <div>
                    <div className="alert-item-query">{s.query}</div>
                    <div className="alert-item-meta">
                      {s.sport ? `${s.sport} · ` : ""}{s.numbered_to ? `/${s.numbered_to} · ` : ""}{(s.min_price != null || s.max_price != null) ? `$${s.min_price ?? "0"}–$${s.max_price ?? "∞"} · ` : ""}Every {intervalLabel(s.check_interval_minutes || 15)} · {s.alert_method === "email" ? "✉️ Email" : s.alert_method === "sms" ? "💬 SMS" : "🔔 Email + SMS"}
                    </div>
                  </div>
                </div>
                <div className="alert-item-actions">
                  <button
                    className="alert-edit-btn"
                    onClick={() => { setEditingId(s.id); setError(""); }}
                    title="Edit alert"
                  >
                    ✎
                  </button>
                  <button
                    className="alert-remove-btn"
                    onClick={() => handleDelete(s.id, s.query)}
                    title="Remove alert"
                  >
                    ✕
                  </button>
                </div>
              </div>
            )
          ))}
        </div>
      )}
    </div>
  );
}
