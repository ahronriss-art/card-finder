import { useState, useEffect } from "react";
import { updateUser, saveSearch, updateSearch, getSavedSearches, deleteSearch, setSearchFolder, folderAssistant, getAlertsPaused, setAlertsPaused, sendTestAlert, runAlertCheck, getEbayUsage, getTwilioBalance, getNextAlertCheck, getAlertStatus, setAllAlertsMethod, signup, login, requestPasswordReset, resetPassword, changePassword, authMe, authLogout, lintAlert, scanAlertHealth, type LintResult } from "./api/client";
import QuickSearch from "./QuickSearch";

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
  dealThresholdPct?: number;
  folder?: string;
  includeAuctions?: boolean;
  catchMisspellings?: boolean;
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
  dealThresholdPct?: string;
  folder?: string;
  includeAuctions?: boolean;
  catchMisspellings?: boolean;
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
  allowMulti = false,
  folders = [],
}: {
  initial?: AlertFormInitial;
  submitLabel: string;
  busy: boolean;
  onSubmit: (v: AlertSubmit) => void;
  onCancel?: () => void;
  allowMulti?: boolean;
  folders?: string[];
}) {
  const initMinutes = initial?.intervalMinutes ?? 60;
  const preset = INTERVALS.find(i => i.minutes === initMinutes);

  const [query, setQuery] = useState(initial?.query ?? "");
  const [multi, setMulti] = useState(false);
  const [folder, setFolder] = useState(initial?.folder ?? "");
  const [includeAuctions, setIncludeAuctions] = useState(initial?.includeAuctions ?? false);
  const [catchMisspellings, setCatchMisspellings] = useState(initial?.catchMisspellings ?? false);
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
  const [dealThreshold, setDealThreshold] = useState(initial?.dealThresholdPct ?? "");
  const [intervalMin, setIntervalMin] = useState(preset ? initMinutes : 60);
  const [useCustom, setUseCustom] = useState(!preset);
  const [customInterval, setCustomInterval] = useState(
    preset ? "" : (initMinutes < 1 ? String(Math.round(initMinutes * 60)) : String(initMinutes))
  );
  const [customUnit, setCustomUnit] = useState<"seconds" | "minutes">(initMinutes < 1 ? "seconds" : "minutes");
  const [method, setMethod] = useState<Method>(initial?.method ?? "both");

  // Live "lint" of the draft search — warns DEAD/NARROW/too-broad before saving.
  const [lint, setLint] = useState<LintResult | null>(null);
  const [linting, setLinting] = useState(false);
  async function runLint() {
    const lines = query.split("\n").map(l => l.trim()).filter(Boolean);
    const q = multi ? (lines[0] || "") : query.trim();
    if (!q) return;
    setLinting(true);
    try {
      const r = await lintAlert({
        query: q,
        sport: sport === "Any" ? undefined : sport,
        minPrice: minPrice ? parseFloat(minPrice) : undefined,
        maxPrice: maxPrice ? parseFloat(maxPrice) : undefined,
        numberedTo: numberedTo ? parseInt(numberedTo, 10) : undefined,
        brand: brand.trim() || undefined,
        insertType: insertType.trim() || undefined,
        cardNumber: cardNumber.trim() || undefined,
        year: year.trim() || undefined,
        exclude: exclude.trim() || undefined,
        includeAuctions: source === "ebay" ? includeAuctions : false,
      });
      setLint(r);
    } catch {
      setLint({ status: "error", messages: ["Couldn't check right now — try again."], suggestions: [], stats: {} });
    } finally {
      setLinting(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // In multi mode the query box holds one card per line; pass the raw text and
    // let the parent split it into one alert per line (sharing all other filters).
    const lines = query.split("\n").map(l => l.trim()).filter(Boolean);
    if (multi ? lines.length === 0 : !query.trim()) return;
    const rawVal = parseFloat(customInterval) || 15;
    const intervalMins = useCustom
      ? Math.max(0.5, Math.min(1440, customUnit === "seconds" ? rawVal / 60 : rawVal))
      : intervalMin;
    const clean = (s: string) => s.trim() || undefined;
    onSubmit({
      query: multi ? lines.join("\n") : query.trim(),
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
      dealThresholdPct: source === "ebay" && dealThreshold ? parseInt(String(dealThreshold), 10) : undefined,
      folder: folder.trim() || undefined,
      includeAuctions: source === "ebay" ? includeAuctions : false,
      catchMisspellings: source === "ebay" ? catchMisspellings : false,
      intervalMins,
      method,
    });
  }

  return (
    <form onSubmit={handleSubmit}>
      {multi ? (
        <textarea
          className="add-alert-input"
          rows={5}
          placeholder={"One card per line, e.g.\nLeBron James Rookie PSA 10\nCharizard Base Set\nMahomes Auto /99"}
          value={query}
          onChange={e => setQuery(e.target.value)}
          style={{ resize: "vertical", lineHeight: 1.5 }}
        />
      ) : (
        <input
          className="add-alert-input"
          type="text"
          placeholder="e.g. LeBron James Rookie PSA 10, Charizard Base Set, Mahomes Auto..."
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
      )}
      {allowMulti && (
        <button
          type="button"
          onClick={() => setMulti(m => !m)}
          style={{ background: "none", border: "none", cursor: "pointer", textDecoration: "underline",
                   color: "#7c3aed", fontSize: 13, padding: "4px 0 10px", display: "block" }}
        >
          {multi
            ? "← Just one card"
            : "+ Add several at once (one per line) — same filters apply to all"}
        </button>
      )}
      {multi && (() => {
        const n = query.split("\n").map(l => l.trim()).filter(Boolean).length;
        return n > 0 ? <div className="numbered-hint" style={{ marginBottom: 10 }}>{n} alert{n === 1 ? "" : "s"} will be created.</div> : null;
      })()}

      {/* Folder: group related alerts together */}
      <div className="interval-label-row">
        <span className="interval-section-label">Folder (optional)</span>
      </div>
      <input
        className="add-alert-input"
        type="text"
        list="alert-folders"
        placeholder="e.g. NBA Bowman — group related alerts together"
        value={folder}
        onChange={e => setFolder(e.target.value)}
        style={{ marginBottom: 14 }}
      />
      <datalist id="alert-folders">
        {folders.map(f => <option key={f} value={f} />)}
      </datalist>

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
      {source === "ebay" && (
        <label className="numbered-row" style={{ marginBottom: 14, display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={includeAuctions} onChange={e => setIncludeAuctions(e.target.checked)} style={{ width: 18, height: 18 }} />
          <span className="numbered-hint" style={{ margin: 0 }}>
            🔨 Also watch eBay auctions for this card (off by default; only alerts when the card's avg sold price is over $1,000)
          </span>
        </label>
      )}
      {source === "ebay" && (
        <label className="numbered-row" style={{ marginBottom: 14, display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={catchMisspellings} onChange={e => setCatchMisspellings(e.target.checked)} style={{ width: 18, height: 18 }} />
          <span className="numbered-hint" style={{ margin: 0 }}>
            🔤 Also catch misspelled listings (matches common seller typos of the player's name — finds deals others miss)
          </span>
        </label>
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

      {lint && (
        <div style={{
          marginTop: 12, padding: "10px 12px", borderRadius: 10, fontSize: 13, lineHeight: 1.5,
          border: "1px solid",
          borderColor: lint.status === "dead" ? "#fca5a5" : lint.status === "narrow" ? "#fcd34d"
            : lint.status === "ok" ? "#86efac" : "#cbd5e1",
          background: lint.status === "dead" ? "rgba(239,68,68,0.08)" : lint.status === "narrow" ? "rgba(245,158,11,0.08)"
            : lint.status === "ok" ? "rgba(34,197,94,0.08)" : "rgba(0,0,0,0.04)",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>
            {lint.status === "dead" ? "❌ This alert won't catch anything"
              : lint.status === "narrow" ? "⚠️ Matches exist, but under your minimum"
              : lint.status === "ok" ? "✅ Looks good"
              : lint.status === "error" ? "Couldn't check" : "Check your search"}
          </div>
          {(lint.messages || []).map((m, i) => <div key={i}>{m}</div>)}
          {(lint.suggestions || []).length > 0 && (
            <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
              {lint.suggestions.map((sg, i) => <li key={i}>{sg}</li>)}
            </ul>
          )}
        </div>
      )}

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
        <button className="btn btn-sm" type="button"
          style={{ background: "rgba(255,255,255,0.1)" }}
          disabled={linting || !query.trim()} onClick={runLint}>
          {linting ? "Checking…" : "🔎 Check search"}
        </button>
        <button className="btn btn-sm" type="submit" disabled={busy || !query.trim()}>
          {busy ? "Saving..." : (() => {
            if (!multi) return submitLabel;
            const n = query.split("\n").map(l => l.trim()).filter(Boolean).length;
            return n > 1 ? `Add ${n} Alerts` : submitLabel;
          })()}
        </button>
      </div>
    </form>
  );
}

export default function AlertsPage({ auctionAlertSignal = 0 }: { auctionAlertSignal?: number }) {
  const [userId, setUserId] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const [alertMethod, setAlertMethod] = useState<Method>("email");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [authMode, setAuthMode] = useState<"login" | "signup" | "reset">("login");
  const [authBusy, setAuthBusy] = useState(false);
  const [resetStep, setResetStep] = useState<"request" | "sent" | "verify">("request");
  // When arriving via a password-reset LINK (?reset=token&email=…), hold the token here.
  const [linkReset, setLinkReset] = useState<{ email: string; token: string } | null>(null);
  const [searches, setSearches] = useState<any[]>([]);
  const [onboarded, setOnboarded] = useState(false);
  const [accountLabel, setAccountLabel] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [testMsg, setTestMsg] = useState("");
  const [testing, setTesting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkMsg, setCheckMsg] = useState("");
  const [usage, setUsage] = useState<{ remaining: number; cap: number; calls: number } | null>(null);
  const [twilio, setTwilio] = useState<{ available: boolean; balance?: number; currency?: string } | null>(null);
  const [nextSecs, setNextSecs] = useState<number | null>(null);
  const [status, setStatus] = useState<Awaited<ReturnType<typeof getAlertStatus>> | null>(null);
  const [switching, setSwitching] = useState(false);

  // Live "searches left today" + Twilio balance counters — refresh on mount and every 60s.
  useEffect(() => {
    const pull = () => {
      getEbayUsage().then(setUsage).catch(() => {});
      getTwilioBalance().then(setTwilio).catch(() => {});
      getAlertStatus().then(setStatus).catch(() => {});
    };
    pull();
    const id = setInterval(pull, 60000);
    return () => clearInterval(id);
  }, []);

  async function switchAllToEmail() {
    if (!confirm("Set ALL your alerts to Email only? This stops their texts (saves Twilio cost). You can switch any back to SMS/Both later.")) return;
    setSwitching(true);
    try {
      await setAllAlertsMethod("email");
      await Promise.all([loadSearches(userId!), getAlertStatus().then(setStatus)]);
      setSuccess("All your alerts are now Email only.");
      setTimeout(() => setSuccess(""), 3000);
    } catch { setError("Couldn't switch alerts."); }
    finally { setSwitching(false); }
  }

  // Countdown to the next automatic eBay alert search: re-sync with the server every
  // 20s, tick down locally every second for a smooth display.
  useEffect(() => {
    let secs = 0;
    const sync = () => getNextAlertCheck()
      .then(d => { secs = d.seconds_remaining; setNextSecs(secs); })
      .catch(() => setNextSecs(null));
    sync();
    const syncId = setInterval(sync, 20000);
    const tickId = setInterval(() => { secs = Math.max(0, secs - 1); setNextSecs(secs); }, 1000);
    return () => { clearInterval(syncId); clearInterval(tickId); };
  }, []);
  const fmtCountdown = (s: number) => {
    if (s <= 0) return "now…";
    const m = Math.floor(s / 60), ss = s % 60;
    return `${m}:${ss.toString().padStart(2, "0")}`;
  };
  const [settingsEmail, setSettingsEmail] = useState("");
  const [settingsPhone, setSettingsPhone] = useState("");
  const [settingsMethod, setSettingsMethod] = useState<Method>("email");
  const [settingsExtraEmails, setSettingsExtraEmails] = useState("");
  const [settingsExtraPhones, setSettingsExtraPhones] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwMsg, setPwMsg] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);
  const [account, setAccount] = useState<any>(null);  // current user (email/phone/extras)
  const [alertsPaused, setAlertsPausedState] = useState<boolean | null>(null);
  const [pauseBusy, setPauseBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [addFormKey, setAddFormKey] = useState(0); // bump to reset the add form
  const [addSource, setAddSource] = useState("ebay"); // default source for the add form
  const [editingId, setEditingId] = useState<number | null>(null);
  const [alertFilter, setAlertFilter] = useState(""); // search box over saved alerts
  const [collapsedFolders, setCollapsedFolders] = useState<Record<string, boolean>>({});
  const [aiFolder, setAiFolder] = useState<string | null>(null);  // folder whose AI box is open
  const [aiText, setAiText] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiResult, setAiResult] = useState<{ summary: string; applied: string[] } | null>(null);
  const [orgOpen, setOrgOpen] = useState(false);  // global "organize with AI" box
  const [orgText, setOrgText] = useState("");
  const [orgBusy, setOrgBusy] = useState(false);
  const [orgResult, setOrgResult] = useState<{ summary: string; applied: string[] } | null>(null);
  const [selecting, setSelecting] = useState(false);            // "Organize" mode
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [moveFolder, setMoveFolder] = useState("");
  const [moving, setMoving] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    // Arrived from a password-reset link? Capture the token, show the set-password
    // screen, and strip the params from the URL so they don't linger.
    const params = new URLSearchParams(window.location.search);
    const rtok = params.get("reset");
    const remail = params.get("email");
    if (rtok && remail) {
      setLinkReset({ email: remail, token: rtok });
      setEmail(remail);
      setAuthMode("reset");
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    // Restore the session from the saved token; verify it's still valid.
    const token = localStorage.getItem("authToken");
    if (!token) return;
    authMe()
      .then(user => {
        setUserId(user.id);
        setAccount(user);
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

  useEffect(() => {
    if (userId) getAlertsPaused().then(setAlertsPausedState).catch(() => {});
  }, [userId]);

  async function togglePause() {
    setPauseBusy(true);
    try {
      const next = !alertsPaused;
      const v = await setAlertsPaused(next);
      setAlertsPausedState(v);
    } catch {
      setError("Couldn't change the alerts switch.");
    } finally {
      setPauseBusy(false);
    }
  }

  async function loadSearches(id: number) {
    try {
      const data = await getSavedSearches(id);
      setSearches(data);
    } catch {}
  }

  const [rescanning, setRescanning] = useState(false);
  async function handleRescanHealth() {
    if (!userId) return;
    setRescanning(true);
    try {
      await scanAlertHealth();
      await loadSearches(userId);
    } catch {
      setError("Couldn't scan alert health right now.");
    } finally {
      setRescanning(false);
    }
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
    setPassword("");
    setAlertMethod("email");
    setSuccess("");
    setError("");
  }

  // Email + password sign in / sign up → get a session token (stays signed in).
  async function handleAuth(e: React.FormEvent) {
    e.preventDefault();
    const addr = email.trim();
    if (!addr || !addr.includes("@")) { setError("Enter a valid email address."); return; }
    if (password.length < 6) { setError("Password must be at least 6 characters."); return; }
    setAuthBusy(true);
    setError("");
    try {
      const { token, user } = authMode === "signup"
        ? await signup(addr, password)
        : await login(addr, password);
      applySession(token, user);
    } catch (err: any) {
      setError(err?.response?.data?.detail ||
        (authMode === "signup" ? "Couldn't create your account." : "Couldn't sign in."));
    } finally {
      setAuthBusy(false);
    }
  }

  function applySession(token: string, user: any) {
    const label = user.email || user.phone || "";
    localStorage.setItem("authToken", token);
    localStorage.setItem("userId", String(user.id));
    localStorage.setItem("accountLabel", label);
    setUserId(user.id);
    setAccount(user);
    setAccountLabel(label);
    setOnboarded(true);
    setPassword("");
    setSuccess("You're signed in! Your alerts are private to this account.");
    loadSearches(user.id);
  }

  async function handleRequestReset(e: React.FormEvent) {
    e.preventDefault();
    const addr = email.trim();
    if (!addr || !addr.includes("@")) { setError("Enter a valid email address."); return; }
    setAuthBusy(true); setError(""); setSuccess("");
    try {
      const { message } = await requestPasswordReset(addr);
      setResetStep("sent");
      setSuccess(message || "If that email has an account, a reset link is on its way. Check your inbox (and spam).");
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Couldn't send the reset link. Try again in a moment.");
    } finally { setAuthBusy(false); }
  }

  async function handleLinkReset(e: React.FormEvent) {
    e.preventDefault();
    if (!linkReset) return;
    if (password.length < 6) { setError("New password must be at least 6 characters."); return; }
    setAuthBusy(true); setError("");
    try {
      const { token, user } = await resetPassword(linkReset.email, linkReset.token, password);
      setLinkReset(null);
      setAuthMode("login");
      applySession(token, user);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "This reset link is invalid or expired. Request a new one.");
    } finally { setAuthBusy(false); }
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
      dealThresholdPct: v.dealThresholdPct,
      folder: v.folder,
      includeAuctions: v.includeAuctions,
      catchMisspellings: v.catchMisspellings,
    };
  }

  async function handleAddSearch(v: AlertSubmit) {
    if (!userId) return;
    // The query may hold several cards (one per line in "add several" mode).
    // Create one alert per line, all sharing the same filters/settings.
    const queries = v.query.split("\n").map(q => q.trim()).filter(Boolean);
    if (queries.length === 0) return;
    setAdding(true);
    try {
      for (const q of queries) {
        await saveSearch(userId, toPayload({ ...v, query: q }));
      }
      setAddSource("ebay");
      setAddFormKey(k => k + 1); // reset the add form
      setSuccess(queries.length > 1
        ? `${queries.length} alerts added — checking every ${intervalLabel(v.intervalMins)}`
        : `Alert added — checking every ${intervalLabel(v.intervalMins)}`);
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

  function toggleSelected(id: number) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function exitOrganize() {
    setSelecting(false);
    setSelectedIds(new Set());
    setMoveFolder("");
  }

  // Rename a folder: applies the new name to every alert currently in it.
  async function handleRenameFolder(fname: string) {
    const next = window.prompt(`Rename folder "${fname}" to:`, fname);
    if (next == null) return;
    const trimmed = next.trim();
    if (!trimmed || trimmed === fname) return;
    const ids = searches.filter(s => (s.folder || "").trim() === fname).map(s => s.id);
    try {
      for (const id of ids) await setSearchFolder(id, trimmed);
      setSearches(prev => prev.map(s => (s.folder || "").trim() === fname ? { ...s, folder: trimmed } : s));
      setSuccess(`Renamed folder to "${trimmed}"`);
      setTimeout(() => setSuccess(""), 3000);
    } catch {
      setError("Could not rename folder.");
    }
  }

  async function handleOrganizeAI() {
    if (!userId || !orgText.trim()) return;
    setOrgBusy(true);
    setOrgResult(null);
    try {
      const r = await folderAssistant("", orgText.trim());  // blank folder = organize all
      setOrgResult(r);
      setOrgText("");
      loadSearches(userId);
    } catch {
      setOrgResult({ summary: "Sorry, the assistant couldn't do that — try rephrasing.", applied: [] });
    } finally {
      setOrgBusy(false);
    }
  }

  async function handleFolderAssistant(fname: string) {
    if (!userId || !aiText.trim()) return;
    setAiBusy(true);
    setAiResult(null);
    try {
      const r = await folderAssistant(fname, aiText.trim());
      setAiResult(r);
      setAiText("");
      loadSearches(userId);  // reflect any changes the assistant made
    } catch {
      setAiResult({ summary: "Sorry, the assistant couldn't do that — try rephrasing.", applied: [] });
    } finally {
      setAiBusy(false);
    }
  }

  // Move the selected existing alerts into a folder (blank = remove from folder).
  async function handleMoveToFolder() {
    if (!userId || selectedIds.size === 0) return;
    const target = moveFolder.trim();
    setMoving(true);
    try {
      const ids = Array.from(selectedIds);
      for (const id of ids) {
        await setSearchFolder(id, target || null);
      }
      setSearches(prev => prev.map(s => selectedIds.has(s.id) ? { ...s, folder: target || null } : s));
      setSuccess(target
        ? `Moved ${ids.length} alert${ids.length === 1 ? "" : "s"} to "${target}"`
        : `Removed ${ids.length} alert${ids.length === 1 ? "" : "s"} from their folder`);
      setTimeout(() => setSuccess(""), 3000);
      exitOrganize();
    } catch {
      setError("Could not move alerts.");
    } finally {
      setMoving(false);
    }
  }

  if (!onboarded) {
    return (
      <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 560 }}>
        <h1>Card Alerts</h1>
        <p className="subtitle">
          {authMode === "signup"
            ? "Create an account with your email and a password to set up your own private alerts."
            : "Sign in with your email and password to access your private alerts. You'll stay signed in."}
        </p>

        <div className="alert-how-it-works">
          <div className="how-step">
            <div className="how-icon">🔐</div>
            <div>
              <div className="how-title">1. {authMode === "signup" ? "Create your account" : "Sign in"}</div>
              <div className="how-desc">Email + password — you stay signed in after</div>
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

        {linkReset ? (
          <form onSubmit={handleLinkReset} style={{ marginTop: 32 }}>
            <p className="subtitle" style={{ marginBottom: 16 }}>
              Set a new password for <strong>{linkReset.email}</strong>.
            </p>
            <div className="form-group">
              <label>New password</label>
              <div style={{ position: "relative" }}>
                <input
                  id="login-password" name="password"
                  type={showPassword ? "text" : "password"} placeholder="••••••••" autoFocus
                  autoComplete="new-password"
                  value={password} onChange={e => setPassword(e.target.value)}
                  style={{ width: "100%", paddingRight: 44 }}
                />
                <button
                  type="button" onClick={() => setShowPassword(s => !s)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
                    background: "none", border: "none", cursor: "pointer", fontSize: 18, lineHeight: 1,
                    color: "#94a3b8", padding: 4 }}
                >
                  {showPassword ? "🙈" : "👁️"}
                </button>
              </div>
            </div>
            {error && <div className="error-msg">{error}</div>}
            {success && <div className="success-msg">{success}</div>}
            <button className="btn" type="submit" disabled={authBusy} style={{ width: "100%", marginTop: 8 }}>
              {authBusy ? "Saving..." : "Set new password & sign in →"}
            </button>
            <button
              type="button"
              onClick={() => { setLinkReset(null); setAuthMode("login"); setError(""); setSuccess(""); setPassword(""); }}
              style={{ width: "100%", marginTop: 12, background: "none", border: "none", cursor: "pointer", textDecoration: "underline", color: "#888" }}
            >
              Back to sign in
            </button>
          </form>
        ) : authMode === "reset" ? (
          resetStep === "sent" ? (
            <div style={{ marginTop: 32 }}>
              <div className="success-msg">{success || "Check your email for a reset link. Look in spam too — it expires in 1 hour."}</div>
              <button
                type="button"
                onClick={() => { setAuthMode("login"); setResetStep("request"); setError(""); setSuccess(""); }}
                style={{ width: "100%", marginTop: 16, background: "none", border: "none", cursor: "pointer", textDecoration: "underline", color: "#888" }}
              >
                Back to sign in
              </button>
            </div>
          ) : (
            <form onSubmit={handleRequestReset} style={{ marginTop: 32 }}>
              <div className="form-group">
                <label>Email Address</label>
                <input
                  id="login-email" name="email" type="email" placeholder="you@email.com"
                  autoComplete="username" autoFocus
                  value={email} onChange={e => setEmail(e.target.value)}
                />
              </div>
              {error && <div className="error-msg">{error}</div>}
              {success && <div className="success-msg">{success}</div>}
              <button className="btn" type="submit" disabled={authBusy} style={{ width: "100%", marginTop: 8 }}>
                {authBusy ? "Sending link..." : "Email me a reset link →"}
              </button>
              <button
                type="button"
                onClick={() => { setAuthMode("login"); setResetStep("request"); setError(""); setSuccess(""); }}
                style={{ width: "100%", marginTop: 12, background: "none", border: "none", cursor: "pointer", textDecoration: "underline", color: "#888" }}
              >
                Back to sign in
              </button>
            </form>
          )
        ) : (
        <form onSubmit={handleAuth} style={{ marginTop: 32 }}>
          <div className="form-group">
            <label>Email Address</label>
            <input
              id="login-email" name="email" type="email" placeholder="you@email.com"
              autoComplete="username" autoFocus
              value={email} onChange={e => setEmail(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label>Password</label>
            <div style={{ position: "relative" }}>
              <input
                id="login-password" name="password"
                type={showPassword ? "text" : "password"} placeholder="••••••••"
                autoComplete={authMode === "signup" ? "new-password" : "current-password"}
                value={password} onChange={e => setPassword(e.target.value)}
                style={{ width: "100%", paddingRight: 44 }}
              />
              <button
                type="button" onClick={() => setShowPassword(s => !s)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                title={showPassword ? "Hide password" : "Show password"}
                style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
                  background: "none", border: "none", cursor: "pointer", fontSize: 18, lineHeight: 1,
                  color: "#94a3b8", padding: 4 }}
              >
                {showPassword ? "🙈" : "👁️"}
              </button>
            </div>
          </div>
          {error && <div className="error-msg">{error}</div>}
          {success && <div className="success-msg">{success}</div>}
          <button className="btn" type="submit" disabled={authBusy} style={{ width: "100%", marginTop: 8 }}>
            {authBusy
              ? (authMode === "signup" ? "Creating account..." : "Signing in...")
              : (authMode === "signup" ? "Create account →" : "Sign in →")}
          </button>
          <button
            type="button"
            onClick={() => { setAuthMode(m => m === "signup" ? "login" : "signup"); setError(""); setSuccess(""); }}
            style={{ width: "100%", marginTop: 12, background: "none", border: "none", cursor: "pointer", textDecoration: "underline", color: "#888" }}
          >
            {authMode === "signup" ? "Already have an account? Sign in" : "New here? Create an account"}
          </button>
          {authMode === "login" && (
            <button
              type="button"
              onClick={() => { setAuthMode("reset"); setResetStep("request"); setError(""); setSuccess(""); setPassword(""); }}
              style={{ width: "100%", marginTop: 8, background: "none", border: "none", cursor: "pointer", textDecoration: "underline", color: "#888", fontSize: 13 }}
            >
              Forgot your password?
            </button>
          )}
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

  async function handleCheckNow() {
    setChecking(true);
    setCheckMsg("");
    try {
      await runAlertCheck();
      setCheckMsg("🔎 Searching all your alerts on eBay now — any new finds will be sent to you within a minute or two.");
      // a full check consumes ~1 search per alert — refresh the remaining counter shortly after
      setTimeout(() => getEbayUsage().then(setUsage).catch(() => {}), 8000);
    } catch (e: any) {
      setCheckMsg(`⚠️ ${e?.response?.data?.detail || "Couldn't start the check. Try again in a moment."}`);
    } finally {
      setChecking(false);
      setTimeout(() => setCheckMsg(""), 12000);
    }
  }

  async function handleUpdateSettings(e: React.FormEvent) {
    e.preventDefault();
    if (!userId) return;
    setSaving(true);
    try {
      // Pass settingsPhone as-is (even "") so emptying the field clears the primary phone;
      // email stays `|| undefined` so it's never accidentally blanked (it's the login id).
      const updated = await updateUser(userId, settingsEmail || undefined, settingsPhone, settingsMethod,
        settingsExtraEmails, settingsExtraPhones);
      setAccount(updated);
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

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwMsg("");
    if (newPw.length < 6) { setPwMsg("Password must be at least 6 characters."); return; }
    setPwBusy(true);
    try {
      await changePassword(newPw);
      setNewPw("");
      setPwMsg("✓ Password changed. Your browser will offer to save the new one.");
    } catch (err: any) {
      setPwMsg(err?.response?.data?.detail || "Couldn't change password.");
    } finally {
      setPwBusy(false);
    }
  }

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <button
          onClick={handleCheckNow}
          disabled={checking}
          title="Search all your alerts on eBay right now (also runs automatically every ~40 min)"
          style={{ background: checking ? "#94a3b8" : "#2563eb", color: "#fff", border: "none", borderRadius: 10, padding: "11px 22px", fontSize: 15, fontWeight: 700, cursor: checking ? "default" : "pointer" }}
        >
          {checking ? "🔎 Searching…" : "🔎 Search alerts now"}
        </button>
        {usage && (
          <span
            title={`${usage.calls.toLocaleString()} of ${usage.cap.toLocaleString()} daily eBay searches used (resets midnight Pacific)`}
            style={{ fontSize: 13, fontWeight: 600, padding: "6px 12px", borderRadius: 8, whiteSpace: "nowrap",
              color: usage.remaining < 300 ? "#f87171" : usage.remaining < 1000 ? "#fbbf24" : "#34d399",
              background: "rgba(148,163,184,0.12)", border: "1px solid rgba(148,163,184,0.25)" }}
          >
            🔎 {usage.remaining.toLocaleString()} searches left today
          </span>
        )}
        {twilio?.available && twilio.balance != null && (
          <span
            title="Remaining Twilio balance for sending SMS/MMS alerts"
            style={{ fontSize: 13, fontWeight: 600, padding: "6px 12px", borderRadius: 8, whiteSpace: "nowrap",
              color: twilio.balance < 5 ? "#f87171" : twilio.balance < 20 ? "#fbbf24" : "#34d399",
              background: "rgba(148,163,184,0.12)", border: "1px solid rgba(148,163,184,0.25)" }}
          >
            💬 ${twilio.balance.toFixed(2)} {twilio.currency || "USD"} SMS left
          </span>
        )}
        {nextSecs != null && (
          <span
            title="Time until the next automatic eBay alert search (runs every ~15 min)"
            style={{ fontSize: 13, fontWeight: 600, padding: "6px 12px", borderRadius: 8, whiteSpace: "nowrap",
              color: "#60a5fa", background: "rgba(148,163,184,0.12)", border: "1px solid rgba(148,163,184,0.25)" }}
          >
            ⏱️ next search {nextSecs <= 0 ? "now…" : `in ${fmtCountdown(nextSecs)}`}
          </span>
        )}
        {checkMsg && <span className="subtitle" style={{ margin: 0, fontSize: 13 }}>{checkMsg}</span>}
      </div>

      {/* SMS spend panel — texts cost Twilio $; email is free */}
      {status && (
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 14,
          padding: "10px 14px", borderRadius: 12, background: "rgba(124,58,237,0.10)", border: "1px solid rgba(124,58,237,0.25)" }}>
          <span style={{ fontWeight: 700, fontSize: 13 }}>💬 SMS spend</span>
          <span style={{ fontSize: 13, color: "#c4b5fd" }}>
            <strong>{status.sms_sending}</strong> alerts text (Twilio $) · <strong>{status.email_sending}</strong> email (free)
          </span>
          <span style={{ fontSize: 13, color: "rgba(255,255,255,0.65)" }}>
            {status.alerts_sent_today} sent today
          </span>
          {twilio?.available && twilio.balance != null &&
            <span style={{ fontSize: 13, color: "rgba(255,255,255,0.65)" }}>· ${twilio.balance.toFixed(2)} Twilio left</span>}
          {status.sms_sending > 0 && (
            <button className="btn btn-sm" type="button" onClick={switchAllToEmail} disabled={switching}
              style={{ marginLeft: "auto", fontSize: 12, padding: "5px 12px" }}>
              {switching ? "Switching…" : "✉️ Set my alerts to Email only"}
            </button>
          )}
        </div>
      )}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
        <div>
          <h1>My Alerts</h1>
          <p className="subtitle">Your private alerts — we check eBay and notify only you when a match is found.</p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
          {alertsPaused !== null && (
            <button
              className="alert-method-badge"
              disabled={pauseBusy}
              onClick={togglePause}
              title={alertsPaused ? "Alerts are OFF — click to turn on" : "Alerts are ON — click to turn off"}
              style={{
                cursor: "pointer", fontWeight: 700,
                background: alertsPaused ? "rgba(248,113,113,0.18)" : "rgba(34,197,94,0.18)",
                border: `1px solid ${alertsPaused ? "rgba(248,113,113,0.45)" : "rgba(34,197,94,0.45)"}`,
                color: alertsPaused ? "#f87171" : "#34d399",
              }}
            >
              {pauseBusy ? "…" : alertsPaused ? "⏸ Alerts OFF — turn ON" : "🟢 Alerts ON — turn OFF"}
            </button>
          )}
          <button
            className="alert-method-badge"
            style={{ cursor: "pointer", background: "rgba(249,115,22,0.15)", border: "1px solid rgba(249,115,22,0.3)" }}
            onClick={() => {
              const open = !showSettings;
              setShowSettings(open);
              if (open) {
                setSettingsEmail(account?.email || "");
                setSettingsPhone(account?.phone || "");
                setSettingsMethod((account?.alert_method as any) || alertMethod);
                setSettingsExtraEmails(account?.extra_emails || "");
                setSettingsExtraPhones(account?.extra_phones || "");
              }
            }}
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

      <QuickSearch />

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
              <label>Additional emails (optional, one per line)</label>
              <textarea rows={2} placeholder={"partner@email.com\nbackup@email.com"} value={settingsExtraEmails}
                onChange={e => setSettingsExtraEmails(e.target.value)}
                style={{ width: "100%", resize: "vertical", lineHeight: 1.5 }} />
            </div>
            <div className="form-group">
              <label>Additional phone numbers (optional, one per line)</label>
              <textarea rows={2} placeholder={"+1 (555) 222-3333\n+1 (555) 444-5555"} value={settingsExtraPhones}
                onChange={e => setSettingsExtraPhones(e.target.value)}
                style={{ width: "100%", resize: "vertical", lineHeight: 1.5 }} />
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

          {/* Change password — separate from alert settings */}
          <form onSubmit={handleChangePassword} style={{ marginTop: 24, paddingTop: 20, borderTop: "1px solid rgba(255,255,255,0.1)" }}>
            <div className="form-group">
              <label>Change password</label>
              <div style={{ position: "relative" }}>
                <input
                  name="new-password" type={showNewPw ? "text" : "password"}
                  placeholder="New password (6+ characters)" autoComplete="new-password"
                  value={newPw} onChange={e => setNewPw(e.target.value)}
                  style={{ width: "100%", paddingRight: 44 }}
                />
                <button
                  type="button" onClick={() => setShowNewPw(s => !s)}
                  aria-label={showNewPw ? "Hide password" : "Show password"}
                  style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
                    background: "none", border: "none", cursor: "pointer", fontSize: 18, lineHeight: 1,
                    color: "#94a3b8", padding: 4 }}
                >
                  {showNewPw ? "🙈" : "👁️"}
                </button>
              </div>
            </div>
            {pwMsg && <div className={pwMsg.startsWith("✓") ? "success-msg" : "error-msg"}>{pwMsg}</div>}
            <button className="btn btn-sm" type="submit" disabled={pwBusy || !newPw}>
              {pwBusy ? "Changing..." : "Change password"}
            </button>
          </form>
        </div>
      )}

      {testMsg && <div className={testMsg.startsWith("✅") ? "success-msg" : "error-msg"}>{testMsg}</div>}
      {success && <div className="success-msg">{success}</div>}
      {error && <div className="error-msg">{error}</div>}

      {/* Filter alerts — at the top so it's visible above the add-card form */}
      {searches.length > 0 && (
        <div className="alert-search-wrap" style={{ marginBottom: 14 }}>
          <span className="alert-search-icon">🔎</span>
          <input
            className="alert-search-input"
            type="text"
            placeholder="Search your alerts (player, brand, folder…)"
            value={alertFilter}
            onChange={e => setAlertFilter(e.target.value)}
          />
          {alertFilter && <button className="alert-search-clear" onClick={() => setAlertFilter("")} title="Clear">✕</button>}
        </div>
      )}

      {/* Add new alert */}
      <div className="add-alert-box">
        <div className="add-alert-title">+ Add a Card to Watch</div>
        <AlertForm
          key={addFormKey}
          initial={{ source: addSource }}
          submitLabel="Add Alert"
          busy={adding}
          onSubmit={handleAddSearch}
          allowMulti
          folders={Array.from(new Set(searches.map(s => s.folder).filter(Boolean))) as string[]}
        />
      </div>

      {/* Alert health summary + rescan */}
      {searches.length > 0 && (() => {
        const dead = searches.filter(s => s.health_status === "dead").length;
        const narrow = searches.filter(s => s.health_status === "narrow").length;
        const anyChecked = searches.some(s => s.health_checked_at);
        return (
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginTop: 18, marginBottom: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Alert health:</span>
            {!anyChecked ? (
              <span style={{ fontSize: 13, opacity: 0.7 }}>not scanned yet</span>
            ) : dead || narrow ? (
              <span style={{ fontSize: 13 }}>
                {dead > 0 && <span style={{ color: "#b91c1c", fontWeight: 600 }}>❌ {dead} not matching</span>}
                {dead > 0 && narrow > 0 && " · "}
                {narrow > 0 && <span style={{ color: "#b45309", fontWeight: 600 }}>⚠️ {narrow} under $ floor</span>}
              </span>
            ) : (
              <span style={{ fontSize: 13, color: "#15803d", fontWeight: 600 }}>✅ all healthy</span>
            )}
            <button className="btn btn-sm" type="button" style={{ background: "rgba(255,255,255,0.1)" }}
              disabled={rescanning} onClick={handleRescanHealth}>
              {rescanning ? "Scanning…" : "↻ Rescan"}
            </button>
          </div>
        );
      })()}

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
          ? searches.filter(s => [s.query, s.sport, s.brand, s.insert_type, s.card_number, s.year, s.exclude, s.folder]
              .filter(Boolean).join(" ").toLowerCase().includes(term))
          : searches;
        const allFolders = Array.from(new Set(searches.map(s => s.folder).filter(Boolean))) as string[];

        const renderAlert = (s: any) => (
          editingId === s.id ? (
            <div className="alert-edit-box" key={s.id}>
              <div className="add-alert-title">Edit Alert</div>
              <AlertForm
                folders={allFolders}
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
                  dealThresholdPct: s.deal_threshold_pct != null ? String(s.deal_threshold_pct) : "",
                  folder: s.folder || "",
                  includeAuctions: !!s.include_auctions,
                  catchMisspellings: !!s.catch_misspellings,
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
            <div
              className="alert-item"
              key={s.id}
              onClick={selecting ? () => toggleSelected(s.id) : undefined}
              style={selecting ? { cursor: "pointer" } : undefined}
            >
              <div className="alert-item-left">
                {selecting && (
                  <input
                    type="checkbox"
                    checked={selectedIds.has(s.id)}
                    onChange={() => toggleSelected(s.id)}
                    onClick={e => e.stopPropagation()}
                    style={{ marginRight: 4, width: 18, height: 18, flexShrink: 0 }}
                  />
                )}
                <div className="alert-item-icon">{s.source === "auction" ? "🔨" : "🔔"}</div>
                <div>
                  <div className="alert-item-query" style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    {s.query}
                    {s.health_status && s.health_status !== "ok" && (
                      <span title={s.health_detail || ""}
                        style={{ fontSize: 11, fontWeight: 700, padding: "1px 7px", borderRadius: 999, whiteSpace: "nowrap",
                          background: s.health_status === "dead" ? "rgba(239,68,68,0.15)" : "rgba(245,158,11,0.15)",
                          color: s.health_status === "dead" ? "#b91c1c" : "#b45309" }}>
                        {s.health_status === "dead" ? "❌ not matching" : "⚠️ under $ floor"}
                      </span>
                    )}
                  </div>
                  <div className="alert-item-meta">
                    {[
                      s.source === "auction" ? "Goldin auctions" : null,
                      s.source === "auction" && s.dry_spell_months ? `not sold ${s.dry_spell_months}mo+` : null,
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
              {!selecting && (
                <div className="alert-item-actions">
                  <button className="alert-edit-btn" onClick={() => { setEditingId(s.id); setError(""); }} title="Edit alert">✎</button>
                  <button className="alert-remove-btn" onClick={() => handleDelete(s.id, s.query)} title="Remove alert">✕</button>
                </div>
              )}
            </div>
          )
        );

        // Group visible alerts by folder, foldered groups first (alphabetical), then ungrouped.
        const grouped = new Map<string, any[]>();
        for (const s of visible) {
          const key = (s.folder || "").trim();
          if (!grouped.has(key)) grouped.set(key, []);
          grouped.get(key)!.push(s);
        }
        const folderKeys = Array.from(grouped.keys()).filter(Boolean).sort((a, b) => a.localeCompare(b));
        const ungrouped = grouped.get("") || [];

        return (
        <div style={{ marginTop: 8 }}>
          <div className="alerts-list-header" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <span>{term ? `${visible.length} of ${searches.length}` : searches.length} active alert{searches.length !== 1 ? "s" : ""}</span>
            <div style={{ display: "flex", gap: 14 }}>
              <button
                type="button"
                onClick={() => { setOrgOpen(o => !o); setOrgResult(null); setOrgText(""); }}
                style={{ background: "none", border: "none", cursor: "pointer", textDecoration: "underline", color: "#7c3aed", fontSize: 13 }}
              >
                ✨ Organize with AI
              </button>
              <button
                type="button"
                onClick={() => selecting ? exitOrganize() : setSelecting(true)}
                style={{ background: "none", border: "none", cursor: "pointer", textDecoration: "underline", color: "#7c3aed", fontSize: 13 }}
              >
                {selecting ? "Done" : "🗂 Organize into folders"}
              </button>
            </div>
          </div>

          {orgOpen && (
            <div className="add-alert-box" style={{ marginBottom: 12, padding: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>✨ Organize all alerts with AI</div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input
                  className="add-alert-input"
                  placeholder={`e.g. "file every alert into folders by player", "put all PSA 10s in a Graded folder", "group by set"`}
                  value={orgText}
                  onChange={e => setOrgText(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") handleOrganizeAI(); }}
                  style={{ flex: 1, minWidth: 220 }}
                />
                <button className="btn btn-sm" disabled={orgBusy || !orgText.trim()} onClick={handleOrganizeAI}>
                  {orgBusy ? "Working…" : "Ask"}
                </button>
              </div>
              {orgResult && (
                <div style={{ marginTop: 8, fontSize: 13 }}>
                  {orgResult.summary && <div style={{ opacity: 0.9 }}>{orgResult.summary}</div>}
                  {orgResult.applied.length > 0 && (
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18, opacity: 0.8 }}>
                      {orgResult.applied.map((a, i) => <li key={i}>{a}</li>)}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}

          {selecting && (
            <div className="add-alert-box" style={{ marginBottom: 14, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>{selectedIds.size} selected</span>
              <input
                type="text"
                list="organize-folders"
                placeholder="Folder name (blank = remove from folder)"
                value={moveFolder}
                onChange={e => setMoveFolder(e.target.value)}
                style={{ flex: 1, minWidth: 160, padding: "8px 10px", borderRadius: 8,
                         border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit" }}
              />
              <datalist id="organize-folders">
                {allFolders.map(f => <option key={f} value={f} />)}
              </datalist>
              <button
                className="btn btn-sm"
                disabled={selectedIds.size === 0 || moving}
                onClick={handleMoveToFolder}
              >
                {moving ? "Moving…" : `Move ${selectedIds.size || ""}`.trim()}
              </button>
            </div>
          )}
          {visible.length === 0 && (
            <div className="empty" style={{ marginTop: 24 }}>
              <p style={{ fontSize: 14 }}>No alerts match "{alertFilter}".</p>
            </div>
          )}

          {folderKeys.map(fname => {
            // While searching, always expand so matches are visible.
            const collapsed = !term && collapsedFolders[fname];
            const items = grouped.get(fname)!;
            return (
              <div key={`folder-${fname}`} className="alert-folder">
                <div className="alert-folder-header" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <button
                    type="button"
                    onClick={() => setCollapsedFolders(c => ({ ...c, [fname]: !c[fname] }))}
                    style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, background: "none",
                             border: "none", cursor: "pointer", color: "inherit", padding: "10px 2px", fontSize: 15, fontWeight: 600, textAlign: "left" }}
                  >
                    <span style={{ fontSize: 12, opacity: 0.7 }}>{collapsed ? "▶" : "▼"}</span>
                    <span>📁 {fname}</span>
                    <span style={{ fontSize: 12, opacity: 0.6, fontWeight: 400 }}>{items.length}</span>
                  </button>
                  <button
                    type="button"
                    className="alert-edit-btn"
                    onClick={() => { setAiFolder(aiFolder === fname ? null : fname); setAiResult(null); setAiText(""); }}
                    title="AI assistant for this folder"
                  >
                    ✨
                  </button>
                  <button
                    type="button"
                    className="alert-edit-btn"
                    onClick={() => handleRenameFolder(fname)}
                    title="Rename folder"
                  >
                    ✎
                  </button>
                </div>

                {aiFolder === fname && (
                  <div className="add-alert-box" style={{ margin: "6px 0 10px", padding: 12 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>✨ Folder assistant</div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <input
                        className="add-alert-input"
                        placeholder={`e.g. "rename to ${fname} PSA", "delete anything under $500", "move all Jokic to a Jokic folder", "set all to 60 min"`}
                        value={aiText}
                        onChange={e => setAiText(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter") handleFolderAssistant(fname); }}
                        style={{ flex: 1, minWidth: 200 }}
                      />
                      <button className="btn btn-sm" disabled={aiBusy || !aiText.trim()} onClick={() => handleFolderAssistant(fname)}>
                        {aiBusy ? "Working…" : "Ask"}
                      </button>
                    </div>
                    {aiResult && (
                      <div style={{ marginTop: 8, fontSize: 13 }}>
                        {aiResult.summary && <div style={{ opacity: 0.9 }}>{aiResult.summary}</div>}
                        {aiResult.applied.length > 0 && (
                          <ul style={{ margin: "6px 0 0", paddingLeft: 18, opacity: 0.8 }}>
                            {aiResult.applied.map((a, i) => <li key={i}>{a}</li>)}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {!collapsed && <div style={{ paddingLeft: 6 }}>{items.map(renderAlert)}</div>}
              </div>
            );
          })}

          {ungrouped.length > 0 && (
            <div className="alert-folder">
              {folderKeys.length > 0 && (
                <div className="alert-folder-header" style={{ padding: "10px 2px", fontSize: 15, fontWeight: 600, opacity: 0.8 }}>
                  📋 Ungrouped <span style={{ fontSize: 12, opacity: 0.6, fontWeight: 400 }}>{ungrouped.length}</span>
                </div>
              )}
              {ungrouped.map(renderAlert)}
            </div>
          )}
        </div>
        );
      })()}
    </div>
  );
}
