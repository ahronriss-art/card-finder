import { useEffect, useMemo, useState } from "react";
import {
  listMasterShops, updateMasterShop, createMasterShop, deleteMasterShop, moveMasterShopToTcg,
  syncMasterShops, getMasterSyncStatus, askMasterShops, type MasterShop,
  getShopsPassword, saveShopsPassword, clearShopsPassword, checkShopPassword,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";
import { ContactCardButton } from "./ContactCard";
import { CallRecapBox } from "./CallRecap";
import { useShopArrowNav, shopCursorStyle } from "./useShopArrowNav";

// Editable fields shown in the detail modal. Sheet-owned fields (top group) push
// back to the Google Sheet on save; the site-owned group stays on the site only.
const SHEET_FIELDS: { key: keyof MasterShop; label: string }[] = [
  { key: "name", label: "Shop name" },
  { key: "owner_name", label: "Owner" },
  { key: "store_type", label: "Store type" },
  { key: "street_address", label: "Street address" },
  { key: "city", label: "City" },
  { key: "state", label: "State" },
  { key: "zip_code", label: "ZIP" },
  { key: "county", label: "County" },
  { key: "metro_area", label: "Metro area" },
  { key: "latitude", label: "Latitude" },
  { key: "longitude", label: "Longitude" },
  { key: "google_maps_url", label: "Google Maps URL" },
  { key: "phone", label: "Phone" },
  { key: "email", label: "Email" },
  { key: "website", label: "Website" },
  { key: "instagram", label: "Instagram" },
  { key: "facebook", label: "Facebook" },
  { key: "twitter", label: "X (Twitter)" },
  { key: "youtube", label: "YouTube" },
  { key: "whatnot", label: "Whatnot" },
  { key: "ebay_store", label: "eBay store" },
  { key: "google_rating", label: "Google rating" },
  { key: "num_reviews", label: "# reviews" },
  { key: "years_in_business", label: "Years in business" },
  { key: "store_hours", label: "Hours" },
  { key: "appointment_only", label: "Appointment only?" },
  { key: "buying_cards", label: "Buying cards?" },
  { key: "selling_wax", label: "Selling sealed wax?" },
  { key: "high_end", label: "High-end inventory?" },
  { key: "pokemon", label: "Pokémon" },
  { key: "sports_cards", label: "Sports cards" },
  { key: "tcg_other", label: "TCG (other)" },
  { key: "memorabilia", label: "Memorabilia" },
  { key: "autograph_auth", label: "Autograph auth. services" },
  { key: "psa_dealer", label: "PSA dealer?" },
  { key: "beckett_dealer", label: "Beckett dealer?" },
  { key: "sgc_dealer", label: "SGC dealer?" },
  { key: "cgc_dealer", label: "CGC dealer?" },
  { key: "comc_partner", label: "COMC partner?" },
  { key: "card_show_vendor", label: "Card show vendor?" },
  { key: "price_tier", label: "Price tier (1-5)" },
  { key: "verification_status", label: "Verification status" },
  { key: "data_sources", label: "Data source(s)" },
  { key: "last_verified", label: "Last verified" },
  { key: "duplicate_check_id", label: "Duplicate check ID" },
  { key: "notes", label: "Notes" },
];
const SITE_FIELDS: { key: keyof MasterShop; label: string }[] = [
  { key: "contacted", label: "Contacted? (who/status)" },
  { key: "contact_name", label: "Contact name" },
  { key: "contact_phone", label: "Contact number" },
  { key: "contacted_by", label: "Contacted by (our team)" },
  { key: "call_notes", label: "Call notes" },
];

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "7px 10px", borderRadius: 8,
  border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit",
};
const selStyle: React.CSSProperties = {
  padding: "8px 12px", borderRadius: 10, border: "1.5px solid rgba(255,255,255,0.15)",
  background: "rgba(255,255,255,0.08)", color: "#fff", fontSize: 13, maxWidth: 220,
};
function FilterChip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="chip" style={on ? {
      background: "linear-gradient(135deg, #f97316, #ec4899)", color: "#fff", borderColor: "transparent",
    } : undefined}>{children}</button>
  );
}

// Toggle filters — each keeps only shops where test() is true. Grouped for layout.
const FLAG_FILTERS: { id: string; label: string; test: (s: MasterShop) => boolean; group: string }[] = [
  { id: "website", label: "Has website", test: s => !!s.website, group: "contact" },
  { id: "email", label: "Has email", test: s => !!s.email, group: "contact" },
  { id: "phone", label: "Has phone", test: s => !!s.phone, group: "contact" },
  { id: "instagram", label: "Has Instagram", test: s => !!s.instagram, group: "contact" },
  { id: "facebook", label: "Has Facebook", test: s => !!s.facebook, group: "contact" },
  { id: "whatnot", label: "Has Whatnot", test: s => !!s.whatnot, group: "contact" },
  { id: "ebay", label: "Has eBay store", test: s => !!s.ebay_store, group: "contact" },
  { id: "psa", label: "PSA", test: s => !!s.psa_dealer, group: "grading" },
  { id: "beckett", label: "Beckett", test: s => !!s.beckett_dealer, group: "grading" },
  { id: "sgc", label: "SGC", test: s => !!s.sgc_dealer, group: "grading" },
  { id: "cgc", label: "CGC", test: s => !!s.cgc_dealer, group: "grading" },
  { id: "comc", label: "COMC", test: s => !!s.comc_partner, group: "grading" },
  { id: "sports", label: "Sports cards", test: s => !!s.sports_cards, group: "product" },
  { id: "pokemon", label: "Pokémon", test: s => !!s.pokemon, group: "product" },
  { id: "tcg", label: "TCG (other)", test: s => !!s.tcg_other, group: "product" },
  { id: "memorabilia", label: "Memorabilia", test: s => !!s.memorabilia, group: "product" },
  { id: "wax", label: "Sealed wax", test: s => !!s.selling_wax, group: "product" },
  { id: "highend", label: "High-end", test: s => !!s.high_end, group: "product" },
  { id: "buying", label: "Buying cards", test: s => !!s.buying_cards, group: "biz" },
  { id: "auto", label: "Autograph auth", test: s => !!s.autograph_auth, group: "biz" },
  { id: "show", label: "Card show vendor", test: s => !!s.card_show_vendor, group: "biz" },
  { id: "appt", label: "Appt only", test: s => !!s.appointment_only, group: "biz" },
];

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const secs = Math.max(0, (Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export default function NewShopsPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const stored = getShopsPassword();
    const url = new URL(window.location.href);
    const key = url.searchParams.get("key");
    const candidate = key || stored;
    if (key) { url.searchParams.delete("key"); window.history.replaceState({}, "", url.toString()); }
    if (!candidate) { setChecking(false); return; }
    saveShopsPassword(candidate, true);
    setUnlocked(true); setChecking(false);
    checkShopPassword(candidate).catch((err: any) => {
      if (err?.response?.status === 401) { clearShopsPassword(); setUnlocked(false); }
    });
  }, []);

  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;
  if (!unlocked) {
    return <ShopPasswordForm title="New Shops List" subtitle="This directory is private. Enter the password to continue." onUnlocked={() => setUnlocked(true)} />;
  }
  return <NewShopsInner />;
}

function NewShopsInner() {
  const [shops, setShops] = useState<MasterShop[]>([]);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const [storeType, setStoreType] = useState("");
  const [contacted, setContacted] = useState("");   // "", "yes", "no"
  const [active, setActive] = useState("");          // "", "yes", "no"
  const [verif, setVerif] = useState("");
  const [metro, setMetro] = useState("");
  const [priceTier, setPriceTier] = useState("");
  const [minRating, setMinRating] = useState("");
  const [minReviews, setMinReviews] = useState("");
  const [sort, setSort] = useState("name");
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [aiQ, setAiQ] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiResult, setAiResult] = useState<{ answer: string; shops: MasterShop[]; total: number } | null>(null);
  const [selected, setSelected] = useState<MasterShop | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");
  const [syncEnabled, setSyncEnabled] = useState(true);
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  async function load() {
    setLoading(true);
    try { setShops(await listMasterShops()); }
    catch { /* ignore */ }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);
  useEffect(() => {
    getMasterSyncStatus().then(s => { setSyncEnabled(s.enabled); setLastSync(s.last?.at ?? null); }).catch(() => {});
  }, []);

  const counts = (get: (s: MasterShop) => string | null | undefined) => {
    const m = new Map<string, number>();
    shops.forEach(s => { const v = (get(s) || "").trim(); if (v) m.set(v, (m.get(v) || 0) + 1); });
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  };
  const states = useMemo(() => counts(s => s.state), [shops]);
  const storeTypes = useMemo(() => counts(s => s.store_type), [shops]);
  const verifs = useMemo(() => counts(s => s.verification_status), [shops]);
  const metros = useMemo(() => counts(s => s.metro_area), [shops]);
  const priceTiers = useMemo(() => counts(s => s.price_tier), [shops]);

  const activeFlags = FLAG_FILTERS.filter(f => flags[f.id]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const out = shops.filter(s => {
      if (state && s.state !== state) return false;
      if (storeType && s.store_type !== storeType) return false;
      if (verif && s.verification_status !== verif) return false;
      if (metro && s.metro_area !== metro) return false;
      if (priceTier && s.price_tier !== priceTier) return false;
      if (contacted === "yes" && !s.contacted) return false;
      if (contacted === "no" && s.contacted) return false;
      if (active === "yes" && s.active === "no") return false;
      if (active === "no" && s.active !== "no") return false;
      if (minRating && (s.google_rating ?? 0) < Number(minRating)) return false;
      if (minReviews && (s.num_reviews ?? 0) < Number(minReviews)) return false;
      if (!activeFlags.every(f => f.test(s))) return false;
      if (!needle) return true;
      return [s.name, s.city, s.state, s.owner_name, s.street_address, s.phone, s.website, s.notes, s.zip_code, s.metro_area]
        .some(v => (v || "").toString().toLowerCase().includes(needle));
    });
    const dir = (a: number, b: number) => b - a;
    out.sort((a, b) =>
      sort === "rating" ? dir(a.google_rating ?? 0, b.google_rating ?? 0) :
      sort === "reviews" ? dir(a.num_reviews ?? 0, b.num_reviews ?? 0) :
      sort === "state" ? (a.state || "").localeCompare(b.state || "") || (a.name || "").localeCompare(b.name || "") :
      (a.name || "").localeCompare(b.name || ""));
    return out;
  }, [shops, q, state, storeType, verif, metro, priceTier, contacted, active, minRating, minReviews, sort, flags]);

  async function runSync() {
    setSyncing(true); setSyncMsg("");
    try {
      const r = await syncMasterShops();
      if (r.ok) { setSyncMsg(`Synced: ${r.created ?? 0} added, ${r.updated ?? 0} updated`); setLastSync(r.at ?? new Date().toISOString()); await load(); }
      else setSyncMsg(r.reason || "Sync not configured yet.");
    } catch { setSyncMsg("Sync failed."); }
    finally { setSyncing(false); }
  }

  async function runAsk() {
    const question = aiQ.trim();
    if (!question || aiBusy) return;
    setAiBusy(true);
    try { setAiResult(await askMasterShops(question)); }
    catch { setAiResult({ answer: "Couldn't reach the AI — try again.", shops: [], total: 0 }); }
    finally { setAiBusy(false); }
  }

  function onRowSaved(u: MasterShop) { setShops(prev => prev.map(s => s.id === u.id ? u : s)); if (selected?.id === u.id) setSelected(u); }
  function onDeleted(id: number) { setShops(prev => prev.filter(s => s.id !== id)); setSelected(null); }

  // Arrow-key navigation over exactly the rows on screen (AI results when shown).
  const shown = aiResult ? aiResult.shops : filtered;
  const [cursor, setCursor] = useState(-1);
  useEffect(() => { setCursor(-1); }, [shown.length, aiResult]);
  useShopArrowNav({ items: shown, selected, setSelected, cursor, setCursor });

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
        <h1>New Shops List</h1>
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          <button className="btn btn-sm" onClick={() => setAdding(true)}>+ Add shop</button>
          <button className="btn btn-sm" onClick={runSync} disabled={syncing} title="Pull the latest from the Google Sheet">
            {syncing ? "Syncing…" : "⟳ Sync now"}
          </button>
        </div>
      </div>
      <p className="subtitle">
        Master card-shop database, two-way synced with the Google Sheet. Edits here push back to the sheet;
        sheet changes appear here on sync. {syncEnabled ? `Last sync: ${timeAgo(lastSync)}.` : "Sheet sync isn’t configured yet."}
        {syncMsg && <span style={{ marginLeft: 8, color: "#fbbf24" }}>{syncMsg}</span>}
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <input className="auction-ask-input" style={{ flex: 1 }}
          placeholder="✨ Ask anything: 'top rated PSA dealers in Texas I haven't contacted'"
          value={aiQ} onChange={e => setAiQ(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") runAsk(); }} />
        <button className="btn btn-sm" onClick={runAsk} disabled={aiBusy || !aiQ.trim()}>{aiBusy ? "Asking…" : "Ask AI"}</button>
      </div>
      {aiResult && (
        <div className="add-alert-box" style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
            <div style={{ fontSize: 14, lineHeight: 1.5 }}>✨ {aiResult.answer}</div>
            <button className="modal-close" onClick={() => { setAiResult(null); setAiQ(""); }}>✕</button>
          </div>
          <div style={{ fontSize: 12, color: "rgba(255,255,255,0.5)", marginTop: 6 }}>
            {aiResult.total} matching · showing {aiResult.shops.length} below
          </div>
        </div>
      )}

      <div className="search-bar" style={{ marginBottom: 10 }}>
        <input placeholder="Search name, city, owner, address, ZIP…" value={q} onChange={e => setQ(e.target.value)} />
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap", alignItems: "center" }}>
        <select value={state} onChange={e => setState(e.target.value)} style={selStyle}>
          <option value="">All states ({shops.length})</option>
          {states.map(([st, n]) => <option key={st} value={st}>{st} ({n})</option>)}
        </select>
        <select value={storeType} onChange={e => setStoreType(e.target.value)} style={selStyle}>
          <option value="">All types</option>
          {storeTypes.map(([t, n]) => <option key={t} value={t}>{t} ({n})</option>)}
        </select>
        <select value={contacted} onChange={e => setContacted(e.target.value)} style={selStyle}>
          <option value="">Contacted: any</option>
          <option value="yes">Contacted</option>
          <option value="no">Not contacted</option>
        </select>
        <select value={active} onChange={e => setActive(e.target.value)} style={selStyle}>
          <option value="">Active: any</option>
          <option value="yes">Active</option>
          <option value="no">Inactive</option>
        </select>
        <select value={minRating} onChange={e => setMinRating(e.target.value)} style={selStyle}>
          <option value="">Any rating</option>
          <option value="4.5">4.5+ ★</option>
          <option value="4">4.0+ ★</option>
          <option value="3.5">3.5+ ★</option>
        </select>
        <select value={minReviews} onChange={e => setMinReviews(e.target.value)} style={selStyle}>
          <option value="">Any # reviews</option>
          <option value="100">100+ reviews</option>
          <option value="50">50+ reviews</option>
          <option value="10">10+ reviews</option>
        </select>
        <select value={verif} onChange={e => setVerif(e.target.value)} style={selStyle}>
          <option value="">Any verification</option>
          {verifs.map(([v, n]) => <option key={v} value={v}>{v} ({n})</option>)}
        </select>
        <select value={metro} onChange={e => setMetro(e.target.value)} style={selStyle}>
          <option value="">Any metro area</option>
          {metros.map(([m, n]) => <option key={m} value={m}>{m} ({n})</option>)}
        </select>
        <select value={priceTier} onChange={e => setPriceTier(e.target.value)} style={selStyle}>
          <option value="">Any price tier</option>
          {priceTiers.map(([p, n]) => <option key={p} value={p}>Tier {p} ({n})</option>)}
        </select>
        <select value={sort} onChange={e => setSort(e.target.value)} style={selStyle}>
          <option value="name">Sort: Name</option>
          <option value="rating">Sort: Rating</option>
          <option value="reviews">Sort: Reviews</option>
          <option value="state">Sort: State</option>
        </select>
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        {FLAG_FILTERS.map(f => (
          <FilterChip key={f.id} on={!!flags[f.id]} onClick={() => setFlags(p => ({ ...p, [f.id]: !p[f.id] }))}>{f.label}</FilterChip>
        ))}
        {(state || storeType || verif || metro || priceTier || contacted || active || minRating || minReviews || activeFlags.length || q) && (
          <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.1)", boxShadow: "none" }}
            onClick={() => { setQ(""); setState(""); setStoreType(""); setVerif(""); setMetro(""); setPriceTier(""); setContacted(""); setActive(""); setMinRating(""); setMinReviews(""); setFlags({}); }}>
            Clear
          </button>
        )}
      </div>

      <div className="results-count">{loading ? "Loading…" : `${shown.length} shop${shown.length === 1 ? "" : "s"}${aiResult ? " (AI results)" : ""}`}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {shown.map((s, i) => (
          <ShopRow key={s.id} shop={s} active={i === cursor}
            onOpen={() => { setCursor(i); setSelected(s); }}
            onRowSaved={onRowSaved} onDeleted={onDeleted} />
        ))}
      </div>

      {selected && <DetailModal shop={selected} onClose={() => setSelected(null)} onSaved={onRowSaved} onDeleted={onDeleted} />}
      {adding && <AddModal onClose={() => setAdding(false)} onCreated={s => { setShops(prev => [s, ...prev]); setAdding(false); }} />}
    </div>
  );
}

function badge(text: string, bg: string, color: string) {
  return <span style={{ fontSize: 11, padding: "2px 7px", borderRadius: 6, background: bg, color, whiteSpace: "nowrap" }}>{text}</span>;
}

function ShopRow({ shop, active, onOpen, onRowSaved, onDeleted }: {
  shop: MasterShop; active?: boolean; onOpen: () => void;
  onRowSaved: (s: MasterShop) => void; onDeleted: (id: number) => void;
}) {
  const contacted = !!shop.contacted;
  const [cName, setCName] = useState(shop.contact_name || "");
  const [cPhone, setCPhone] = useState(shop.contact_phone || "");
  const [busy, setBusy] = useState(false);
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();

  async function save(patch: Partial<MasterShop>) {
    setBusy(true);
    try { onRowSaved(await updateMasterShop(shop.id, patch)); } catch { /* ignore */ } finally { setBusy(false); }
  }
  // Copy into the TCG Shops List tab; the row leaves this list (sheet row is kept).
  async function moveToTcg(e: React.MouseEvent) {
    stop(e);
    if (!confirm(`Move "${shop.name}" to the TCG Shops List?`)) return;
    setBusy(true);
    try { await moveMasterShopToTcg(shop.id); onDeleted(shop.id); } catch { setBusy(false); }
  }
  async function remove(e: React.MouseEvent) {
    stop(e);
    if (!confirm(`Remove "${shop.name}" from the site list? (The sheet row is kept.)`)) return;
    setBusy(true);
    try { await deleteMasterShop(shop.id); onDeleted(shop.id); } catch { setBusy(false); }
  }

  return (
    <div className="alert-item" data-shop-id={shop.id}
      style={{ display: "block", ...(active ? shopCursorStyle : null) }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div className="alert-item-left" style={{ cursor: "pointer" }} onClick={onOpen}>
          <div className="alert-item-icon">🏪</div>
          <div>
            <div className="alert-item-query">
              {shop.name}
              <span style={{ display: "inline-flex", gap: 6, marginLeft: 8, verticalAlign: "middle" }}>
                {shop.psa_dealer && badge("PSA", "rgba(59,130,246,0.22)", "#93c5fd")}
                {shop.verification_status && badge(shop.verification_status, "rgba(255,255,255,0.08)", "rgba(255,255,255,0.7)")}
              </span>
            </div>
            <div className="alert-item-meta">
              {[shop.city, shop.state].filter(Boolean).join(", ")}
              {shop.google_rating ? ` · ⭐ ${shop.google_rating} (${shop.num_reviews ?? 0})` : ""}
              {shop.phone ? ` · ${shop.phone}` : ""}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button className="btn btn-sm" onClick={moveToTcg} disabled={busy}
            style={{ background: "rgba(255,255,255,0.1)", fontSize: 11 }}
            title="Move to the TCG Shops List">→ TCG list</button>
          <button className="alert-remove-btn" onClick={remove} disabled={busy} title="Remove from site list">🗑</button>
        </div>
      </div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
        <button type="button" onClick={e => { stop(e); save({ contacted: contacted ? "" : "yes" }); }} disabled={busy}
          style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13, fontWeight: 600, padding: "4px 10px", borderRadius: 8,
            border: "1px solid rgba(255,255,255,0.15)", background: contacted ? "rgba(52,211,153,0.18)" : "rgba(255,255,255,0.05)", color: contacted ? "#34d399" : "#f87171" }}>
          {contacted ? "✓ Contacted" : "✗ Not contacted"}
        </button>
        <input type="text" placeholder="Contact name" value={cName} onClick={stop} onChange={e => setCName(e.target.value)}
          onBlur={() => { if (cName !== (shop.contact_name || "")) save({ contact_name: cName }); }}
          style={{ flex: 1, minWidth: 130, padding: "6px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit" }} />
        <input type="tel" placeholder="Contact number" value={cPhone} onClick={stop} onChange={e => setCPhone(e.target.value)}
          onBlur={() => { if (cPhone !== (shop.contact_phone || "")) save({ contact_phone: cPhone }); }}
          style={{ flex: 1, minWidth: 130, padding: "6px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit" }} />
      </div>
    </div>
  );
}

function EditField({ shop, field, label, onSaved }: {
  shop: MasterShop; field: keyof MasterShop; label: string; onSaved: (s: MasterShop) => void;
}) {
  const [v, setV] = useState(shop[field] == null ? "" : String(shop[field]));
  const area = field === "notes" || field === "call_notes" || field === "call_recap";
  async function commit() {
    const cur = shop[field] == null ? "" : String(shop[field]);
    if (v === cur) return;
    try { onSaved(await updateMasterShop(shop.id, { [field]: v } as Partial<MasterShop>)); } catch { /* ignore */ }
  }
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 11, color: "rgba(255,255,255,0.5)", fontWeight: 600 }}>{label}</span>
      {area
        ? <textarea rows={3} value={v} onChange={e => setV(e.target.value)} onBlur={commit} style={{ ...inputStyle, resize: "vertical" }} />
        : <input type="text" value={v} onChange={e => setV(e.target.value)} onBlur={commit} style={inputStyle} />}
    </label>
  );
}

function DetailModal({ shop, onClose, onSaved, onDeleted }: {
  shop: MasterShop; onClose: () => void; onSaved: (s: MasterShop) => void; onDeleted: (id: number) => void;
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 720 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h2 style={{ margin: 0 }}>{shop.name}</h2>
            <div style={{ fontSize: 12, color: "rgba(255,255,255,0.45)", marginTop: 2 }}>
              {shop.record_id ? `Record ${shop.record_id}` : "no record id yet"} · edits to the top fields sync to the Google Sheet · ← → to move between shops
            </div>
          </div>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div style={{ marginTop: 12 }}>
          <ContactCardButton card={{
            store: shop.name || "", owner: shop.owner_name, name: shop.contact_name,
            number: shop.contact_phone || shop.phone, state: shop.state, email: shop.email,
            ig: shop.instagram, website: shop.website, city: shop.city, address: shop.street_address,
            recap: shop.call_recap,
          }} />
        </div>

        <h3 style={{ fontSize: 13, margin: "16px 0 8px", color: "rgba(255,255,255,0.8)" }}>Shop info (syncs to sheet)</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 10 }}>
          {SHEET_FIELDS.map(f => <EditField key={String(f.key)} shop={shop} field={f.key} label={f.label} onSaved={onSaved} />)}
        </div>

        <h3 style={{ fontSize: 13, margin: "20px 0 8px", color: "rgba(255,255,255,0.8)" }}>Our contact tracking (site only)</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 10 }}>
          {SITE_FIELDS.map(f => <EditField key={String(f.key)} shop={shop} field={f.key} label={f.label} onSaved={onSaved} />)}
        </div>

        <CallRecapBox value={shop.call_recap || ""} onSave={async t => onSaved(await updateMasterShop(shop.id, { call_recap: t }))} />

        <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end" }}>
          <button className="btn btn-sm btn-danger" onClick={async () => {
            if (!confirm(`Remove "${shop.name}" from the site list? (The sheet row is kept.)`)) return;
            try { await deleteMasterShop(shop.id); onDeleted(shop.id); } catch { /* ignore */ }
          }}>Remove from site</button>
        </div>
      </div>
    </div>
  );
}

function AddModal({ onClose, onCreated }: { onClose: () => void; onCreated: (s: MasterShop) => void }) {
  const [form, setForm] = useState<Partial<MasterShop>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k: keyof MasterShop, v: string) => setForm(p => ({ ...p, [k]: v }));
  const fields: { key: keyof MasterShop; label: string }[] = [
    { key: "name", label: "Shop name *" }, { key: "owner_name", label: "Owner" },
    { key: "street_address", label: "Street address" }, { key: "city", label: "City" },
    { key: "state", label: "State" }, { key: "zip_code", label: "ZIP" },
    { key: "phone", label: "Phone" }, { key: "email", label: "Email" },
    { key: "website", label: "Website" }, { key: "instagram", label: "Instagram" },
    { key: "notes", label: "Notes" },
  ];
  async function submit() {
    if (!(form.name || "").trim()) { setErr("Shop name is required."); return; }
    setBusy(true); setErr("");
    try { onCreated(await createMasterShop(form)); }
    catch (e: any) { setErr(e?.response?.data?.detail || "Couldn't add the shop."); setBusy(false); }
  }
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 620 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <h2 style={{ margin: 0 }}>Add shop</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <p className="subtitle" style={{ marginTop: 6 }}>Added here and appended to the Google Sheet (a Record ID is assigned automatically).</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 10 }}>
          {fields.map(f => (
            <label key={String(f.key)} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: 11, color: "rgba(255,255,255,0.5)", fontWeight: 600 }}>{f.label}</span>
              <input type="text" value={(form[f.key] as string) || ""} onChange={e => set(f.key, e.target.value)} style={inputStyle} />
            </label>
          ))}
        </div>
        {err && <div className="error-msg" style={{ marginTop: 10 }}>{err}</div>}
        <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button className="btn btn-sm" onClick={onClose} style={{ background: "rgba(255,255,255,0.1)", boxShadow: "none" }}>Cancel</button>
          <button className="btn btn-sm" onClick={submit} disabled={busy}>{busy ? "Adding…" : "Add shop"}</button>
        </div>
      </div>
    </div>
  );
}
