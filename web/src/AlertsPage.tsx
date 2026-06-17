import { useState, useEffect } from "react";
import { updateUser, saveSearch, updateSearch, getSavedSearches, deleteSearch, sendTestAlert, requestLoginCode, verifyLoginCode, authMe, authLogout } from "./api/client";

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
  brand?: string;
  insertType?: string;
  cardNumber?: string;
  year?: string;
  exclude?: string;
  source: string;          // "ebay" or "auction"
  drySpellMonths?: number;
  catchMisspellings?: boolean;
  dealThresholdPct?: number;
  intervalMins: number;
  method: Method;
};

type AlertFormInitial = {
  query?: string;
  sport?: string;
  minPrice?: string;
  maxPrice?: string;
  numberedTo?: string;
  brand?: string;
  insertType?: string;
  cardNumber?: string;
  year?: string;
  exclude?: string;
  source?: string;
  drySpellMonths?: string;
  catchMisspellings?: boolean;
  dealThresholdPct?: string;
  intervalMinutes?: number;
  method?: Method;
};

const BRANDS = ["Topps", "Topps Chrome", "Bowman", "Bowman Chrome", "Panini Prizm", "Panini Select", "Panini Mosaic", "Panini Optic", "Donruss", "Score", "Fleer", "Upper Deck", "Leaf"];
const INSERTS = ["Refractor", "Base", "Gold", "Silver", "Black", "Pink", "Orange", "Blue", "Green", "Red", "Purple", "Cherry Blossom", "Wave", "Mojo", "Disco", "Shimmer", "Auto", "Rookie", "1st"];

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
  const [brand, setBrand] = useState(initial?.brand ?? "");
  const [insertType, setInsertType] = useState(initial?.insertType ?? "");
  const [cardNumber, setCardNumber] = useState(initial?.cardNumber ?? "");
  const [year, setYear] = useState(initial?.year ?? "");
  const [exclude, setExclude] = useState(initial?.exclude ?? "");
  const [source, setSource] = useState(initial?.source ?? "ebay");
  const [drySpell, setDrySpell] = useState(initial?.drySpellMonths ?? "");
  const [catchMisspellings, setCatchMisspellings] = useState(initial?.catchMisspellings ?? false);
  const [dealThreshold, setDealThreshold] = useState(initial?.dealThresholdPct ?? "");
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
    const clean = (s: string) => s.trim() || undefined;
    onSubmit({
      query: query.trim(),
      sport,
      minPrice: minPrice ? parseFloat(minPrice) : undefined,
      maxPrice: maxPrice ? parseFloat(maxPrice) : undefined,
      numberedTo: numberedTo ? parseInt(numberedTo, 10) : undefined,
      brand: clean(brand),
      insertType: clean(insertType),
      cardNumber: clean(cardNumber),
      year: clean(year),
      exclude: clean(exclude),
      source,
      drySpellMonths: source === "auction" && drySpell ? parseInt(drySpell, 10) : undefined,
      catchMisspellings: source === "ebay" ? catchMisspellings : false,
      dealThresholdPct: source === "ebay" && dealThreshold ? parseInt(String(dealThreshold), 10) : undefined,
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

      {/* What to watch: eBay listings vs Goldin live auctions */}
      <div className="interval-label-row">
        <span className="interval-section-label">Watch for</span>
      </div>
      <div className="interval-chips" style={{ marginBottom: 14 }}>
        {([
          { key: "ebay", icon: "🛒", label: "eBay listings" },
          { key: "auction", icon: "🔨", label: "Goldin auctions" },
        ] as const).map(o => (
          <button key={o.key} type="button"
            className={`chip${source === o.key ? " active" : ""}`}
            style={{ fontSize: 12, padding: "5px 12px" }}
            onClick={() => setSource(o.key)}>
            {o.icon} {o.label}
          </button>
        ))}
      </div>
      {source === "auction" && (
        <div className="numbered-row" style={{ marginBottom: 14 }}>
          <span className="interval-section-label" style={{ whiteSpace: "nowrap" }}>Only if not sold in</span>
          <input
            type="number" min="1" className="numbered-input"
            placeholder="e.g. 6" value={drySpell}
            onChange={e => setDrySpell(e.target.value)}
          />
          <span className="numbered-hint">months — catch rare cards coming to auction. Leave blank to alert on every matching auction.</span>
        </div>
      )}
      {source === "ebay" && (
        <div className="misspelling-toggle" style={{ marginBottom: 14 }}
          onClick={() => setCatchMisspellings(v => !v)}>
          <input type="checkbox" checked={catchMisspellings} readOnly />
          <span>Also catch misspellings — sweep misspelled variants buyers miss (often cheaper)</span>
        </div>
      )}
      {source === "ebay" && (
        <div className="numbered-row" style={{ marginBottom: 14 }}>
          <span className="interval-section-label" style={{ whiteSpace: "nowrap" }}>Only alert if at least</span>
          <input
            type="number" min="1" max="99" className="numbered-input"
            placeholder="e.g. 20" value={dealThreshold}
            onChange={e => setDealThreshold(e.target.value)}
          />
          <span className="numbered-hint">% below market value — only the real steals. Leave blank to alert on every match.</span>
        </div>
      )}

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

      {/* More card filters */}
      <div className="interval-label-row">
        <span className="interval-section-label">More filters (optional)</span>
      </div>
      <datalist id="brand-options">{BRANDS.map(b => <option key={b} value={b} />)}</datalist>
      <datalist id="insert-options">{INSERTS.map(i => <option key={i} value={i} />)}</datalist>
      <div className="alert-filters-grid">
        <label className="alert-filter">
          <span>Brand / set</span>
          <input type="text" list="brand-options" placeholder="e.g. Bowman Chrome" value={brand} onChange={e => setBrand(e.target.value)} />
        </label>
        <label className="alert-filter">
          <span>Insert / parallel</span>
          <input type="text" list="insert-options" placeholder="e.g. Gold, Cherry Blossom" value={insertType} onChange={e => setInsertType(e.target.value)} />
        </label>
        <label className="alert-filter">
          <span>Year</span>
          <input type="text" inputMode="numeric" placeholder="e.g. 2023" value={year} onChange={e => setYear(e.target.value)} />
        </label>
        <label className="alert-filter">
          <span>Card #</span>
          <input type="text" placeholder="e.g. 150" value={cardNumber} onChange={e => setCardNumber(e.target.value)} />
        </label>
        <label className="alert-filter alert-filter-wide">
          <span>Exclude words</span>
          <input type="text" placeholder="e.g. reprint lot psa" value={exclude} onChange={e => setExclude(e.target.value)} />
        </label>
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

export default function AlertsPage({ auctionAlertSignal = 0 }: { auctionAlertSignal?: number }) {
  const [userId, setUserId] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [alertMethod, setAlertMethod] = useState<Method>("email");
  const [loginCode, setLoginCode] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [searches, setSearches] = useState<any[]>([]);
  const [onboarded, setOnboarded] = useState(false);
  const [accountLabel, setAccountLabel] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [testMsg, setTestMsg] = useState("");
  const [testing, setTesting] = useState(false);
  const [settingsEmail, setSettingsEmail] = useState("");
  const [settingsPhone, setSettingsPhone] = useState("");
  const [settingsMethod, setSettingsMethod] = useState<Method>("email");
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addFormKey, setAddFormKey] = useState(0); // bump to reset the add form
  const [addSource, setAddSource] = useState("ebay"); // default source for the add form
  const [editingId, setEditingId] = useState<number | null>(null);
  const [alertFilter, setAlertFilter] = useState(""); // search box over saved alerts
  const [savingEdit, setSavingEdit] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    // Restore the session from the saved token; verify it's still valid.
    const token = localStorage.getItem("authToken");
    if (!token) return;
    authMe()
      .then(user => {
        setUserId(user.id);
        setAccountLabel(user.email || user.phone || "");
        setOnboarded(true);
        loadSearches(user.id);
      })
      .catch(() => {
        // Expired/invalid token — clear it and show the login screen.
        localStorage.removeItem("authToken");
        localStorage.removeItem("userId");
      });
  }, []);

  // When the user clicks "Create auction alert" on the Auctions tab, default
  // the add form to Goldin auctions and scroll it into view.
  useEffect(() => {
    if (auctionAlertSignal > 0) {
      setAddSource("auction");
      setAddFormKey(k => k + 1);
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [auctionAlertSignal]);

  async function loadSearches(id: number) {
    try {
      const data = await getSavedSearches(id);
      setSearches(data);
    } catch {}
  }

  function handleLogout() {
    authLogout();
    localStorage.removeItem("authToken");
    localStorage.removeItem("userId");
    localStorage.removeItem("accountLabel");
    setUserId(null);
    setAccountLabel("");
    setOnboarded(false);
    setSearches([]);
    setEmail("");
    setPhone("");
    setLoginCode("");
    setCodeSent(false);
    setAlertMethod("email");
    setSuccess("");
    setError("");
  }

  // Step 1: email the user a 6-digit sign-in code.
  async function handleRequestCode(e: React.FormEvent) {
    e.preventDefault();
    const addr = email.trim();
    if (!addr || !addr.includes("@")) { setError("Enter a valid email address."); return; }
    setSendingCode(true);
    setError("");
    try {
      await requestLoginCode(addr);
      setCodeSent(true);
      setSuccess(`We emailed a 6-digit code to ${addr}. Enter it below.`);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't send the code. Try again shortly.");
    } finally {
      setSendingCode(false);
    }
  }

  // Step 2: verify the code → get a session token → sign in.
  async function handleVerifyCode(e: React.FormEvent) {
    e.preventDefault();
    const code = loginCode.trim();
    if (!code) { setError("Enter the code from your email."); return; }
    setVerifying(true);
    setError("");
    try {
      const { token, user } = await verifyLoginCode(email.trim(), code);
      const label = user.email || user.phone || "";
      localStorage.setItem("authToken", token);
      localStorage.setItem("userId", String(user.id));
      localStorage.setItem("accountLabel", label);
      setUserId(user.id);
      setAccountLabel(label);
      setOnboarded(true);
      setSuccess("You're signed in! Your alerts are private to this account.");
      loadSearches(user.id);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "That code is invalid or expired.");
    } finally {
      setVerifying(false);
    }
  }

  function toPayload(v: AlertSubmit) {
    return {
      query: v.query,
      sport: v.sport === "Any" ? undefined : v.sport,
      intervalMinutes: v.intervalMins,
      alertMethod: v.method,
      minPrice: v.minPrice, maxPrice: v.maxPrice, numberedTo: v.numberedTo,
      brand: v.brand, insertType: v.insertType, cardNumber: v.cardNumber,
      year: v.year, exclude: v.exclude,
      source: v.source, drySpellMonths: v.drySpellMonths,
      catchMisspellings: v.catchMisspellings,
      dealThresholdPct: v.dealThresholdPct,
    };
  }

  async function handleAddSearch(v: AlertSubmit) {
    if (!userId) return;
    setAdding(true);
    try {
      await saveSearch(userId, toPayload(v));
      setAddSource("ebay");
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
      await updateSearch(id, toPayload(v));
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
        <p className="subtitle">Sign in with your email to access your private alerts. We'll email you a one-time code — no password needed.</p>

        <div className="alert-how-it-works">
          <div className="how-step">
            <div className="how-icon">📧</div>
            <div>
              <div className="how-title">1. Enter your email</div>
              <div className="how-desc">We email you a 6-digit sign-in code</div>
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

        {!codeSent ? (
          <form onSubmit={handleRequestCode} style={{ marginTop: 32 }}>
            <div className="form-group">
              <label>Email Address</label>
              <input
                type="email" placeholder="you@email.com" autoFocus
                value={email} onChange={e => setEmail(e.target.value)}
              />
            </div>
            {error && <div className="error-msg">{error}</div>}
            {success && <div className="success-msg">{success}</div>}
            <button className="btn" type="submit" disabled={sendingCode} style={{ width: "100%", marginTop: 8 }}>
              {sendingCode ? "Sending code..." : "Email me a sign-in code →"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerifyCode} style={{ marginTop: 32 }}>
            <div className="form-group">
              <label>Enter the 6-digit code we emailed to {email}</label>
              <input
                type="text" inputMode="numeric" autoComplete="one-time-code"
                placeholder="123456" maxLength={6} autoFocus
                value={loginCode} onChange={e => setLoginCode(e.target.value.replace(/\D/g, ""))}
                style={{ letterSpacing: 6, fontSize: 22, textAlign: "center" }}
              />
            </div>
            {error && <div className="error-msg">{error}</div>}
            {success && <div className="success-msg">{success}</div>}
            <button className="btn" type="submit" disabled={verifying} style={{ width: "100%", marginTop: 8 }}>
              {verifying ? "Verifying..." : "Sign in →"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => { setCodeSent(false); setLoginCode(""); setError(""); setSuccess(""); }}
              style={{ width: "100%", marginTop: 10, background: "none", border: "none", cursor: "pointer", textDecoration: "underline", color: "#888" }}
            >
              Use a different email
            </button>
          </form>
        )}
      </div>
    );
  }

  async function handleTestAlert() {
    if (!userId) return;
    setTesting(true);
    setTestMsg("");
    try {
      const r = await sendTestAlert(userId);
      setTestMsg(`✅ Test alert sent via ${r.via.join(" & ")} — check now (may take a minute).`);
    } catch (e: any) {
      setTestMsg(`⚠️ ${e?.response?.data?.detail || "Couldn't send the test alert."}`);
    } finally {
      setTesting(false);
      setTimeout(() => setTestMsg(""), 9000);
    }
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
          <button
            className="alert-method-badge"
            style={{ cursor: "pointer", background: "rgba(34,197,94,0.15)", border: "1px solid rgba(34,197,94,0.35)" }}
            onClick={handleTestAlert}
            disabled={testing}
            title="Send yourself a sample alert to confirm alerts reach you"
          >
            {testing ? "Sending..." : "🧪 Send test alert"}
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

      {testMsg && <div className={testMsg.startsWith("✅") ? "success-msg" : "error-msg"}>{testMsg}</div>}
      {success && <div className="success-msg">{success}</div>}
      {error && <div className="error-msg">{error}</div>}

      {/* Add new alert */}
      <div className="add-alert-box">
        <div className="add-alert-title">+ Add a Card to Watch</div>
        <AlertForm
          key={addFormKey}
          initial={{ source: addSource }}
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
      ) : (() => {
        const term = alertFilter.trim().toLowerCase();
        const visible = term
          ? searches.filter(s => [s.query, s.sport, s.brand, s.insert_type, s.card_number, s.year, s.exclude]
              .filter(Boolean).join(" ").toLowerCase().includes(term))
          : searches;
        return (
        <div style={{ marginTop: 8 }}>
          <div className="alert-search-wrap">
            <span className="alert-search-icon">🔎</span>
            <input
              className="alert-search-input"
              type="text"
              placeholder="Search your alerts (player, brand, insert…)"
              value={alertFilter}
              onChange={e => setAlertFilter(e.target.value)}
            />
            {alertFilter && <button className="alert-search-clear" onClick={() => setAlertFilter("")} title="Clear">✕</button>}
          </div>
          <div className="alerts-list-header">
            {term ? `${visible.length} of ${searches.length}` : searches.length} active alert{searches.length !== 1 ? "s" : ""}
          </div>
          {visible.length === 0 && (
            <div className="empty" style={{ marginTop: 24 }}>
              <p style={{ fontSize: 14 }}>No alerts match "{alertFilter}".</p>
            </div>
          )}
          {visible.map(s => (
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
                    brand: s.brand || "",
                    insertType: s.insert_type || "",
                    cardNumber: s.card_number || "",
                    year: s.year || "",
                    exclude: s.exclude || "",
                    source: s.source || "ebay",
                    drySpellMonths: s.dry_spell_months != null ? String(s.dry_spell_months) : "",
                    catchMisspellings: !!s.catch_misspellings,
                    dealThresholdPct: s.deal_threshold_pct != null ? String(s.deal_threshold_pct) : "",
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
                  <div className="alert-item-icon">{s.source === "auction" ? "🔨" : "🔔"}</div>
                  <div>
                    <div className="alert-item-query">{s.query}</div>
                    <div className="alert-item-meta">
                      {[
                        s.source === "auction" ? "Goldin auctions" : null,
                        s.source === "auction" && s.dry_spell_months ? `not sold ${s.dry_spell_months}mo+` : null,
                        s.source !== "auction" && s.catch_misspellings ? "✏️ catches misspellings" : null,
                        s.source !== "auction" && s.deal_threshold_pct ? `📉 ${s.deal_threshold_pct}%+ below market` : null,
                        s.sport,
                        s.year,
                        s.brand,
                        s.insert_type,
                        s.card_number ? `#${String(s.card_number).replace(/^#/, "")}` : null,
                        s.numbered_to ? `/${s.numbered_to}` : null,
                        (s.min_price != null || s.max_price != null) ? `$${s.min_price ?? "0"}–$${s.max_price ?? "∞"}` : null,
                        s.exclude ? `−${s.exclude}` : null,
                        `Every ${intervalLabel(s.check_interval_minutes || 15)}`,
                        s.alert_method === "email" ? "✉️ Email" : s.alert_method === "sms" ? "💬 SMS" : "🔔 Email + SMS",
                      ].filter(Boolean).join(" · ")}
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
        );
      })()}
    </div>
  );
}
