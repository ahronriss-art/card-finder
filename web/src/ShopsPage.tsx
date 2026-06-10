import { useEffect, useState, useCallback } from "react";
import {
  listShops, getShopStates, aiUpdateShop, createShop,
  checkShopPassword, type Shop,
} from "./api/client";

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

export default function ShopsPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);

  // gate
  const [pw, setPw] = useState("");
  const [pwError, setPwError] = useState("");

  useEffect(() => {
    const stored = localStorage.getItem("shopsPassword");
    const url = new URL(window.location.href);
    const key = url.searchParams.get("key");
    const candidate = key || stored;
    if (!candidate) { setChecking(false); return; }
    checkShopPassword(candidate)
      .then(() => {
        localStorage.setItem("shopsPassword", candidate);
        if (key) { url.searchParams.delete("key"); window.history.replaceState({}, "", url.toString()); }
        setUnlocked(true);
      })
      .catch(() => { localStorage.removeItem("shopsPassword"); })
      .finally(() => setChecking(false));
  }, []);

  async function submitPw(e: React.FormEvent) {
    e.preventDefault();
    setPwError("");
    try {
      await checkShopPassword(pw.trim());
      localStorage.setItem("shopsPassword", pw.trim());
      setUnlocked(true);
    } catch {
      setPwError("Wrong password.");
    }
  }

  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;

  if (!unlocked) {
    return (
      <div className="app" style={{ paddingTop: 60, maxWidth: 440 }}>
        <h1>🔒 Card Shops</h1>
        <p className="subtitle">This directory is private. Enter the password to continue.</p>
        <form onSubmit={submitPw} style={{ marginTop: 24 }}>
          <div className="form-group">
            <input type="password" placeholder="Password" value={pw} onChange={e => setPw(e.target.value)} autoFocus />
          </div>
          {pwError && <div className="error-msg">{pwError}</div>}
          <button className="btn" type="submit" style={{ width: "100%", marginTop: 8 }}>Enter →</button>
        </form>
      </div>
    );
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
  const [page, setPage] = useState(0);
  const [states, setStates] = useState<{ state: string; count: number }[]>([]);
  const [selected, setSelected] = useState<Shop | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listShops({
        q: q || undefined, state: state || undefined,
        contacted: contacted || undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE,
      });
      setShops(data.shops);
      setTotal(data.total);
    } finally { setLoading(false); }
  }, [q, state, contacted, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { getShopStates().then(setStates).catch(() => {}); }, []);
  useEffect(() => { setPage(0); }, [q, state, contacted]);

  function onSaved(updated: Shop) {
    setShops(prev => prev.map(s => (s.id === updated.id ? updated : s)));
    setSelected(updated);
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
        <button className="btn btn-sm" onClick={() => setAdding(true)}>+ Add shop</button>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "18px 0" }}>
        <input
          style={{ flex: "1 1 240px" }}
          placeholder="Search name, city, address, email…"
          value={q} onChange={e => setQ(e.target.value)}
        />
        <select value={state} onChange={e => setState(e.target.value)}>
          <option value="">All states</option>
          {states.map(s => <option key={s.state} value={s.state}>{s.state} ({s.count})</option>)}
        </select>
        <select value={contacted} onChange={e => setContacted(e.target.value)}>
          <option value="">Contacted: any</option>
          <option value="yes">Contacted</option>
          <option value="no">Not contacted</option>
        </select>
      </div>

      {loading ? (
        <p className="subtitle">Loading shops…</p>
      ) : shops.length === 0 ? (
        <div className="empty" style={{ marginTop: 40 }}><p>No shops match your filters.</p></div>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {shops.map(s => (
            <ShopRow key={s.id} shop={s} onClick={() => setSelected(s)} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
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

function ShopRow({ shop, onClick }: { shop: Shop; onClick: () => void }) {
  return (
    <div className="alert-item" style={{ cursor: "pointer" }} onClick={onClick}>
      <div className="alert-item-left">
        <div className="alert-item-icon">🏪</div>
        <div>
          <div className="alert-item-query">{shop.name}</div>
          <div className="alert-item-meta">
            {[shop.city, shop.state].filter(Boolean).join(", ")}
            {shop.rating ? ` · ⭐ ${shop.rating} (${shop.reviews ?? 0})` : ""}
            {shop.contacted ? ` · ✅ ${shop.contacted}` : ""}
          </div>
        </div>
      </div>
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

function AddShopModal({ onClose, onCreated }: { onClose: () => void; onCreated: (s: Shop) => void }) {
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [stateV, setStateV] = useState("");
  const [phone, setPhone] = useState("");
  const [website, setWebsite] = useState("");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) { setError("Name required."); return; }
    setBusy(true); setError("");
    try {
      const created = await createShop({
        name: name.trim(), city: city || undefined, state: stateV || undefined,
        phone: phone || undefined, website: website || undefined, email: email || undefined,
      });
      onCreated(created);
    } catch {
      setError("Could not add shop.");
    } finally { setBusy(false); }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 480 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <h2 style={{ margin: 0 }}>Add a shop</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={submit} style={{ marginTop: 16 }}>
          <div className="form-group"><label>Name *</label><input value={name} onChange={e => setName(e.target.value)} autoFocus /></div>
          <div style={{ display: "flex", gap: 10 }}>
            <div className="form-group" style={{ flex: 1 }}><label>City</label><input value={city} onChange={e => setCity(e.target.value)} /></div>
            <div className="form-group" style={{ flex: 1 }}><label>State</label><input value={stateV} onChange={e => setStateV(e.target.value)} /></div>
          </div>
          <div className="form-group"><label>Phone</label><input value={phone} onChange={e => setPhone(e.target.value)} /></div>
          <div className="form-group"><label>Website</label><input value={website} onChange={e => setWebsite(e.target.value)} /></div>
          <div className="form-group"><label>Email</label><input value={email} onChange={e => setEmail(e.target.value)} /></div>
          {error && <div className="error-msg">{error}</div>}
          <button className="btn" type="submit" disabled={busy} style={{ width: "100%", marginTop: 8 }}>
            {busy ? "Adding…" : "Add shop"}
          </button>
        </form>
      </div>
    </div>
  );
}
