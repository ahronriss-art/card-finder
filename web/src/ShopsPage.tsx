import { useEffect, useState, useCallback } from "react";
import {
  listShops, getShopStates, aiUpdateShop, createShop, askShops,
  syncShopsFromSheet, getSyncStatus, getEbayUsage, checkShopPassword, updateShop, deleteShop, type Shop,
  getShopsPassword, saveShopsPassword, clearShopsPassword,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";

// label + which fields show in the detail grid (order matters)
const FIELDS: { key: keyof Shop; label: string; type?: "url" | "tel" | "email" }[] = [
  { key: "website", label: "Website", type: "url" },
  { key: "phone", label: "Phone", type: "tel" },
  { key: "email", label: "Email", type: "email" },
  { key: "full_address", label: "Address" },
  { key: "city", label: "City" },
  { key: "state", label: "State" },
  { key: "rating", label: "Rating" },
  { key: "reviews", label: "Reviews" },
  { key: "instagram", label: "Instagram" },
  { key: "tiktok", label: "TikTok" },
  { key: "whatnot", label: "Whatnot" },
  { key: "contacted", label: "Contacted?" },
  { key: "contact_way", label: "Contact method" },
  { key: "topps_fanatics", label: "Topps/Fanatics account" },
  { key: "tcg_account", label: "TCG account" },
  { key: "buys_wholesale", label: "Buys from wholesalers" },
  { key: "willing_to_wholesale", label: "Willing to wholesale w/ us" },
  { key: "collectors", label: "Collectors / sellers" },
];

const PAGE_SIZE = 30;

function timeAgo(iso: string): string {
  const secs = Math.max(0, (Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export default function ShopsPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);

  // gate
  useEffect(() => {
    const stored = getShopsPassword();
    const url = new URL(window.location.href);
    const key = url.searchParams.get("key");
    const candidate = key || stored;
    if (key) { url.searchParams.delete("key"); window.history.replaceState({}, "", url.toString()); }
    if (!candidate) { setChecking(false); return; }

    // Already saved before? Unlock instantly — never block the user on a slow/cold backend.
    saveShopsPassword(candidate, true);
    setUnlocked(true);
    setChecking(false);

    // Validate quietly in the background; only forget on an actual wrong-password (401).
    checkShopPassword(candidate).catch((err) => {
      if (err?.response?.status === 401) {
        clearShopsPassword();
        setUnlocked(false);
      }
    });
  }, []);

  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;

  if (!unlocked) {
    return <ShopPasswordForm title="Card Shops" subtitle="This directory is private. Enter the password to continue." onUnlocked={() => setUnlocked(true)} />;
  }

  return <ShopDirectory />;
}

function ShopDirectory() {
  const [shops, setShops] = useState<Shop[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const [contacted, setContacted] = useState("");
  const [shopType, setShopType] = useState("");
  const [minRating, setMinRating] = useState("");
  const [minReviews, setMinReviews] = useState("");
  const [sort, setSort] = useState("name");
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [page, setPage] = useState(0);
  const [states, setStates] = useState<{ state: string; count: number }[]>([]);
  const [selected, setSelected] = useState<Shop | null>(null);
  const [adding, setAdding] = useState(false);

  // Google Sheet sync
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");
  const [lastSync, setLastSync] = useState<string | null>(null);
  const [ebayUsage, setEbayUsage] = useState<{ calls: number; cap: number; remaining: number } | null>(null);

  useEffect(() => { getSyncStatus().then(s => setLastSync(s.at)).catch(() => {}); }, []);

  // eBay API usage today — refresh on mount and every 60s.
  useEffect(() => {
    const pull = () => getEbayUsage().then(setEbayUsage).catch(() => {});
    pull();
    const id = setInterval(pull, 60000);
    return () => clearInterval(id);
  }, []);

  async function runSync() {
    setSyncing(true); setSyncMsg("");
    try {
      const r = await syncShopsFromSheet();
      if (r.error) { setSyncMsg("Sync failed."); }
      else {
        setSyncMsg(`Synced: ${r.updated} updated, ${r.added} added`);
        setLastSync(new Date().toISOString());
        load();
      }
    } catch {
      setSyncMsg("Sync failed.");
    } finally {
      setSyncing(false);
      setTimeout(() => setSyncMsg(""), 5000);
    }
  }

  // AI ask
  const [aiQuestion, setAiQuestion] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiResult, setAiResult] = useState<{ answer: string; shops: Shop[]; total: number } | null>(null);
  const [aiError, setAiError] = useState("");

  async function runAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!aiQuestion.trim()) return;
    setAiBusy(true); setAiError("");
    try {
      const r = await askShops(aiQuestion.trim());
      setAiResult({ answer: r.answer, shops: r.shops, total: r.total });
    } catch {
      setAiError("Couldn't answer that. Try rephrasing.");
    } finally { setAiBusy(false); }
  }
  function clearAi() { setAiResult(null); setAiQuestion(""); setAiError(""); }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listShops({
        q: q || undefined, state: state || undefined,
        contacted: contacted || undefined,
        shop_type: shopType || undefined,
        min_rating: minRating ? Number(minRating) : undefined,
        min_reviews: minReviews ? Number(minReviews) : undefined,
        sort,
        has_website: flags.has_website || undefined,
        has_email: flags.has_email || undefined,
        has_phone: flags.has_phone || undefined,
        has_instagram: flags.has_instagram || undefined,
        topps_fanatics: flags.topps_fanatics || undefined,
        willing_to_wholesale: flags.willing_to_wholesale || undefined,
        limit: PAGE_SIZE, offset: page * PAGE_SIZE,
      });
      setShops(data.shops);
      setTotal(data.total);
    } finally { setLoading(false); }
  }, [q, state, contacted, shopType, minRating, minReviews, sort, flags, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { getShopStates().then(setStates).catch(() => {}); }, []);
  useEffect(() => { setPage(0); }, [q, state, contacted, shopType, minRating, minReviews, sort, flags]);

  function onSaved(updated: Shop) {
    setShops(prev => prev.map(s => (s.id === updated.id ? updated : s)));
    setSelected(updated);
  }
  // Inline row edits — update the list(s) but don't open the detail modal.
  function onRowSaved(updated: Shop) {
    setShops(prev => prev.map(s => (s.id === updated.id ? updated : s)));
    setAiResult(prev => prev ? { ...prev, shops: prev.shops.map(s => s.id === updated.id ? updated : s) } : prev);
  }
  function onDeleted(id: number) {
    setShops(prev => prev.filter(s => s.id !== id));
    setAiResult(prev => prev ? { ...prev, shops: prev.shops.filter(s => s.id !== id) } : prev);
  }
  function onCreated(created: Shop) {
    setAdding(false);
    setSelected(created);
    load();
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="app" style={{ paddingTop: 32, paddingBottom: 60 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1>Card Shops</h1>
          <p className="subtitle">{total.toLocaleString()} shops. Search, filter, and add info — updates are parsed by AI into the right fields.</p>
        </div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn btn-sm" onClick={runSync} disabled={syncing}
              style={{ background: "rgba(255,255,255,0.1)" }}>
              {syncing ? "Syncing…" : "⟳ Sync sheet"}
            </button>
            <button className="btn btn-sm" onClick={() => setAdding(true)}>+ Add shop</button>
          </div>
          <div className="subtitle" style={{ margin: 0, fontSize: 12 }}>
            {syncMsg || (lastSync ? `Sheet synced ${timeAgo(lastSync)}` : "Not synced yet")}
          </div>
          {ebayUsage && (
            <div className="subtitle" style={{ margin: 0, fontSize: 12 }} title="eBay Browse API searches used today (resets midnight Pacific)">
              🛒 eBay searches today:{" "}
              <strong style={{ color: ebayUsage.remaining < 500 ? "#f87171" : ebayUsage.remaining < 1500 ? "#fbbf24" : "#6ee7b7" }}>
                {ebayUsage.calls.toLocaleString()}
              </strong>
              {" "}/ {ebayUsage.cap.toLocaleString()}
            </div>
          )}
        </div>
      </div>

      {/* AI ask box */}
      <form onSubmit={runAsk} style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <input
          style={{ flex: 1 }}
          placeholder="✨ Ask anything: 'top rated shops in Texas I haven't contacted'"
          value={aiQuestion}
          onChange={e => setAiQuestion(e.target.value)}
        />
        <button className="btn btn-sm" type="submit" disabled={aiBusy || !aiQuestion.trim()}>
          {aiBusy ? "Thinking…" : "Ask AI"}
        </button>
      </form>
      {aiError && <div className="error-msg" style={{ marginTop: 10 }}>{aiError}</div>}
      {aiResult && (
        <div className="ai-answer">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
            <div style={{ whiteSpace: "pre-wrap" }}>{aiResult.answer}</div>
            <button className="modal-close" style={{ flexShrink: 0 }} onClick={clearAi} title="Clear">✕</button>
          </div>
          <div className="subtitle" style={{ margin: "8px 0 0" }}>
            Showing {aiResult.shops.length} of {aiResult.total} matching · click any to open
          </div>
        </div>
      )}

      {/* Filters (hidden while showing an AI answer) */}
      {!aiResult && <>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "18px 0 10px" }}>
        <input
          style={{ flex: "1 1 240px" }}
          placeholder="Search name, city, address, email…"
          value={q} onChange={e => setQ(e.target.value)}
        />
        <select value={state} onChange={e => setState(e.target.value)}>
          <option value="">All states</option>
          {states.map(s => <option key={s.state} value={s.state}>{s.state} ({s.count})</option>)}
        </select>
        <select value={shopType} onChange={e => setShopType(e.target.value)}>
          <option value="">All types</option>
          <option value="shop">🏪 Shops</option>
          <option value="whatnot_breaker">📦 Whatnot breakers</option>
          <option value="seller">🤝 Sellers</option>
        </select>
        <select value={contacted} onChange={e => setContacted(e.target.value)}>
          <option value="">Contacted: any</option>
          <option value="yes">Contacted</option>
          <option value="no">Not contacted</option>
        </select>
        <select value={minRating} onChange={e => setMinRating(e.target.value)}>
          <option value="">Any rating</option>
          <option value="4.5">⭐ 4.5+</option>
          <option value="4">⭐ 4.0+</option>
          <option value="3.5">⭐ 3.5+</option>
          <option value="3">⭐ 3.0+</option>
        </select>
        <select value={minReviews} onChange={e => setMinReviews(e.target.value)}>
          <option value="">Any # reviews</option>
          <option value="10">10+ reviews</option>
          <option value="50">50+ reviews</option>
          <option value="100">100+ reviews</option>
          <option value="250">250+ reviews</option>
        </select>
        <select value={sort} onChange={e => setSort(e.target.value)}>
          <option value="name">Sort: Name</option>
          <option value="rating">Sort: Top rated</option>
          <option value="reviews">Sort: Most reviews</option>
        </select>
      </div>

      {/* Toggle filters */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
        {([
          { key: "has_website", label: "Has website" },
          { key: "has_email", label: "Has email" },
          { key: "has_phone", label: "Has phone" },
          { key: "has_instagram", label: "Has Instagram" },
          { key: "topps_fanatics", label: "Topps/Fanatics acct" },
          { key: "willing_to_wholesale", label: "Wants to wholesale" },
        ] as const).map(f => (
          <button
            key={f.key} type="button"
            className={`chip${flags[f.key] ? " active" : ""}`}
            style={{ fontSize: 12, padding: "5px 12px" }}
            onClick={() => setFlags(prev => ({ ...prev, [f.key]: !prev[f.key] }))}
          >
            {f.label}
          </button>
        ))}
        {(q || state || contacted || shopType || minRating || minReviews || sort !== "name" || Object.values(flags).some(Boolean)) && (
          <button
            type="button" className="chip" style={{ fontSize: 12, padding: "5px 12px" }}
            onClick={() => { setQ(""); setState(""); setContacted(""); setShopType(""); setMinRating(""); setMinReviews(""); setSort("name"); setFlags({}); }}
          >
            ✕ Clear all
          </button>
        )}
      </div>
      </>}

      {loading && !aiResult ? (
        <p className="subtitle">Loading shops…</p>
      ) : (aiResult ? aiResult.shops : shops).length === 0 ? (
        <div className="empty" style={{ marginTop: 40 }}><p>No shops match{aiResult ? " that question." : " your filters."}</p></div>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {(aiResult ? aiResult.shops : shops).map(s => (
            <ShopRow key={s.id} shop={s} onOpen={() => setSelected(s)} onRowSaved={onRowSaved} onDeleted={onDeleted} />
          ))}
        </div>
      )}

      {/* Pagination (browse mode only) */}
      {!aiResult && totalPages > 1 && (
        <div style={{ display: "flex", gap: 12, justifyContent: "center", alignItems: "center", marginTop: 24 }}>
          <button className="btn btn-sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>← Prev</button>
          <span className="subtitle" style={{ margin: 0 }}>Page {page + 1} of {totalPages}</span>
          <button className="btn btn-sm" disabled={page + 1 >= totalPages} onClick={() => setPage(p => p + 1)}>Next →</button>
        </div>
      )}

      {selected && <ShopDetail shop={selected} onClose={() => setSelected(null)} onSaved={onSaved} />}
      {adding && <AddShopModal onClose={() => setAdding(false)} onCreated={onCreated} />}
    </div>
  );
}

function ShopRow({ shop, onOpen, onRowSaved, onDeleted }: {
  shop: Shop; onOpen: () => void; onRowSaved: (s: Shop) => void; onDeleted: (id: number) => void;
}) {
  const breaker = shop.shop_type === "whatnot_breaker";
  const seller = shop.shop_type === "seller";
  const contacted = !!shop.contacted;
  const [by, setBy] = useState(shop.contacted_by || "");
  const [callNotes, setCallNotes] = useState(shop.call_notes || "");
  const [busy, setBusy] = useState(false);
  const stop = (e: React.SyntheticEvent) => e.stopPropagation();

  async function save(patch: Partial<Shop>) {
    setBusy(true);
    try { onRowSaved(await updateShop(shop.id, patch)); }
    catch { /* ignore */ }
    finally { setBusy(false); }
  }

  async function toggleContacted(e: React.MouseEvent) {
    stop(e);
    await save({ contacted: contacted ? "" : "yes" });
  }

  async function remove(e: React.MouseEvent) {
    stop(e);
    if (!confirm(`Delete "${shop.name}" from the shops list?`)) return;
    setBusy(true);
    try { await deleteShop(shop.id); onDeleted(shop.id); }
    catch { setBusy(false); }
  }

  return (
    <div className="alert-item" style={{ display: "block" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div className="alert-item-left" style={{ cursor: "pointer" }} onClick={onOpen}>
          <div className="alert-item-icon">{seller ? "🤝" : breaker ? "📦" : "🏪"}</div>
          <div>
            <div className="alert-item-query">
              {shop.name}
              {breaker && <span style={{ fontSize: 11, marginLeft: 8, padding: "2px 7px", borderRadius: 6, background: "rgba(124,58,237,0.25)", color: "#c4b5fd", verticalAlign: "middle" }}>Whatnot breaker</span>}
              {seller && <span style={{ fontSize: 11, marginLeft: 8, padding: "2px 7px", borderRadius: 6, background: "rgba(16,185,129,0.25)", color: "#6ee7b7", verticalAlign: "middle" }}>Seller</span>}
            </div>
            <div className="alert-item-meta">
              {[shop.city, shop.state].filter(Boolean).join(", ")}
              {shop.rating ? ` · ⭐ ${shop.rating} (${shop.reviews ?? 0})` : ""}
            </div>
          </div>
        </div>
        <button className="alert-remove-btn" onClick={remove} disabled={busy} title="Delete shop">🗑</button>
      </div>

      {/* Inline contact tracking */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
        <button
          type="button" onClick={toggleContacted} disabled={busy}
          style={{
            display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 13, fontWeight: 600,
            padding: "4px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)",
            background: contacted ? "rgba(52,211,153,0.18)" : "rgba(255,255,255,0.05)",
            color: contacted ? "#34d399" : "#f87171",
          }}
        >
          {contacted ? "✓ Contacted" : "✗ Not contacted"}
        </button>
        <input
          type="text" placeholder="Contacted by (who)" value={by}
          onClick={stop} onChange={e => setBy(e.target.value)}
          onBlur={() => { if (by !== (shop.contacted_by || "")) save({ contacted_by: by }); }}
          style={{ flex: 1, minWidth: 150, padding: "6px 10px", borderRadius: 8,
                   border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit" }}
        />
      </div>
      <textarea
        rows={2} placeholder="Call notes…" value={callNotes}
        onClick={stop} onChange={e => setCallNotes(e.target.value)}
        onBlur={() => { if (callNotes !== (shop.call_notes || "")) save({ call_notes: callNotes }); }}
        style={{ width: "100%", marginTop: 8, resize: "vertical", lineHeight: 1.5, padding: "8px 10px",
                 borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit" }}
      />
    </div>
  );
}

function fmtVal(val: any, type?: string) {
  if (val === null || val === undefined || val === "") return <span style={{ opacity: 0.4 }}>—</span>;
  if (type === "url") {
    const href = String(val).startsWith("http") ? String(val) : `https://${val}`;
    return <a href={href} target="_blank" rel="noreferrer">{val}</a>;
  }
  if (type === "tel") return <a href={`tel:${val}`}>{val}</a>;
  if (type === "email") return <a href={`mailto:${val}`}>{val}</a>;
  return String(val);
}

function ShopDetail({ shop, onClose, onSaved }: { shop: Shop; onClose: () => void; onSaved: (s: Shop) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ summary: string; changed: Record<string, any> } | null>(null);
  const [error, setError] = useState("");

  async function applyNote() {
    if (!note.trim()) return;
    setBusy(true); setError(""); setResult(null);
    try {
      const r = await aiUpdateShop(shop.id, note.trim());
      onSaved(r.shop);
      setResult({ summary: r.summary, changed: r.changed });
      setNote("");
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Update failed.");
    } finally { setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <h2 style={{ margin: 0 }}>{shop.name}</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="shop-fields">
          {FIELDS.map(f => (
            <div key={String(f.key)} className="shop-field">
              <div className="shop-field-label">{f.label}</div>
              <div className="shop-field-value">{fmtVal(shop[f.key], f.type)}</div>
            </div>
          ))}
        </div>

        {/* AI update box */}
        <div className="add-alert-box" style={{ marginTop: 20 }}>
          <div className="add-alert-title">✨ Add info (AI fills the fields)</div>
          <p className="subtitle" style={{ marginTop: 0 }}>
            Type anything you learned — "talked to owner Mike, has Topps account, IG @theshop". AI sorts it into the right fields.
          </p>
          <textarea
            className="add-alert-input"
            style={{ minHeight: 90, resize: "vertical", fontFamily: "inherit" }}
            placeholder="What did you learn about this shop?"
            value={note}
            onChange={e => setNote(e.target.value)}
          />
          {error && <div className="error-msg">{error}</div>}
          {result && (
            <div className="success-msg">
              {result.summary || "Updated."}
              {Object.keys(result.changed).length > 0 && (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                  {Object.entries(result.changed).map(([k, v]: any) => (
                    <li key={k}><strong>{k}</strong>: {String(v.to)}</li>
                  ))}
                </ul>
              )}
              {result && Object.keys(result.changed).length === 0 && (
                <div style={{ marginTop: 4, opacity: 0.8 }}>Saved to notes (no structured fields changed).</div>
              )}
            </div>
          )}
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
            <button className="btn btn-sm" onClick={applyNote} disabled={busy || !note.trim()}>
              {busy ? "Thinking…" : "Apply update"}
            </button>
          </div>
        </div>

        {/* Notes log */}
        {shop.notes && (
          <div style={{ marginTop: 18 }}>
            <div className="add-alert-title">Notes log</div>
            <pre className="shop-notes">{shop.notes}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

// Every field you can fill when adding a shop. `row` groups two onto one line.
const ADD_FIELDS: { key: keyof Shop; label: string; type?: "number" | "area"; row?: boolean }[] = [
  { key: "full_address", label: "Address" },
  { key: "city", label: "City", row: true },
  { key: "state", label: "State", row: true },
  { key: "phone", label: "Phone", row: true },
  { key: "email", label: "Email", row: true },
  { key: "website", label: "Website" },
  { key: "instagram", label: "Instagram", row: true },
  { key: "tiktok", label: "TikTok", row: true },
  { key: "whatnot", label: "Whatnot" },
  { key: "rating", label: "Rating", type: "number", row: true },
  { key: "reviews", label: "Reviews", type: "number", row: true },
  { key: "contacted", label: "Contacted? (who)", row: true },
  { key: "contact_way", label: "Contact method", row: true },
  { key: "topps_fanatics", label: "Topps/Fanatics account", row: true },
  { key: "tcg_account", label: "TCG account", row: true },
  { key: "buys_wholesale", label: "Buys from wholesalers", row: true },
  { key: "willing_to_wholesale", label: "Willing to wholesale w/ us", row: true },
  { key: "collectors", label: "Collectors / sellers" },
  { key: "notes", label: "Notes", type: "area" },
];

function AddShopModal({ onClose, onCreated }: { onClose: () => void; onCreated: (s: Shop) => void }) {
  const [name, setName] = useState("");
  const [shopType, setShopType] = useState("shop");
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const set = (k: string, v: string) => setVals(prev => ({ ...prev, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) { setError("Name required."); return; }
    setBusy(true); setError("");
    const payload: Partial<Shop> = { name: name.trim(), shop_type: shopType };
    for (const f of ADD_FIELDS) {
      const raw = (vals[f.key as string] || "").trim();
      if (!raw) continue;
      if (f.type === "number") {
        const n = Number(raw);
        if (!Number.isNaN(n)) (payload as any)[f.key] = n;
      } else {
        (payload as any)[f.key] = raw;
      }
    }
    try {
      const created = await createShop(payload);
      onCreated(created);
    } catch {
      setError("Could not add shop.");
    } finally { setBusy(false); }
  }

  // walk fields, pairing consecutive `row` items two-up
  const rendered: React.ReactNode[] = [];
  for (let i = 0; i < ADD_FIELDS.length; i++) {
    const f = ADD_FIELDS[i];
    const next = ADD_FIELDS[i + 1];
    const field = (ff: typeof f) => (
      <div className="form-group" style={{ flex: 1 }} key={String(ff.key)}>
        <label>{ff.label}</label>
        {ff.type === "area"
          ? <textarea className="add-alert-input" style={{ minHeight: 70, fontFamily: "inherit" }} value={vals[ff.key as string] || ""} onChange={e => set(ff.key as string, e.target.value)} />
          : <input type={ff.type === "number" ? "number" : "text"} value={vals[ff.key as string] || ""} onChange={e => set(ff.key as string, e.target.value)} />}
      </div>
    );
    if (f.row && next?.row) {
      rendered.push(<div style={{ display: "flex", gap: 10 }} key={i}>{field(f)}{field(next)}</div>);
      i++;
    } else {
      rendered.push(field(f));
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 560 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <h2 style={{ margin: 0 }}>Add a shop</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={submit} style={{ marginTop: 16 }}>
          <div style={{ display: "flex", gap: 10 }}>
            <div className="form-group" style={{ flex: 2 }}><label>Name *</label><input value={name} onChange={e => setName(e.target.value)} autoFocus /></div>
            <div className="form-group" style={{ flex: 1 }}>
              <label>Type</label>
              <select style={{ width: "100%" }} value={shopType} onChange={e => setShopType(e.target.value)}>
                <option value="shop">🏪 Shop</option>
                <option value="whatnot_breaker">📦 Whatnot breaker</option>
                <option value="seller">🤝 Seller</option>
              </select>
            </div>
          </div>
          {rendered}
          {error && <div className="error-msg">{error}</div>}
          <button className="btn" type="submit" disabled={busy} style={{ width: "100%", marginTop: 8 }}>
            {busy ? "Adding…" : "Add shop"}
          </button>
        </form>
      </div>
    </div>
  );
}
