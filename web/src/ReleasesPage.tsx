import { useEffect, useMemo, useRef, useState } from "react";
import {
  checkShopPassword, getShopsPassword, clearShopsPassword,
  listReleases, createRelease, autoFetchChecklist, getRelease, setCardTargeted, deleteRelease, deleteAllReleases,
  parseReleaseCalendar, saveReleaseCalendar, getReleaseCalendar, deleteReleaseCalendarItem, clearReleaseCalendar, setReleaseReminder, setReleaseWax, autoImportReleases, getSoldHistory, searchCards,
  type ReleaseProduct, type ReleaseCard, type ParsedCalendarRow, type CalendarItem,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";

// Build the eBay search text for a card, to paste into the Alerts tab.
function searchText(productName: string, c: ReleaseCard) {
  return [productName, c.parallel, c.player, c.card_number ? `#${String(c.card_number).replace(/^#/, "")}` : "",
    c.numbered_to ? `/${c.numbered_to}` : ""].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
}

function Board() {
  const [products, setProducts] = useState<ReleaseProduct[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [product, setProduct] = useState<ReleaseProduct | null>(null);
  const [cards, setCards] = useState<ReleaseCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // add form
  const [name, setName] = useState("");
  const [date, setDate] = useState("");
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const parseFormRef = useRef<HTMLDivElement | null>(null);

  // release calendar (screenshot → product + date)
  const [calendar, setCalendar] = useState<CalendarItem[]>([]);
  const [calParsed, setCalParsed] = useState<ParsedCalendarRow[] | null>(null);
  const [calBusy, setCalBusy] = useState(false);
  const [calMsg, setCalMsg] = useState("");

  // card view controls
  const [pfilter, setPfilter] = useState("");
  const [onlyTargets, setOnlyTargets] = useState(false);
  const [copied, setCopied] = useState("");

  async function load() {
    try { setProducts(await listReleases()); }
    catch { setError("Couldn't load releases."); }
    finally { setLoading(false); }
  }
  async function loadCalendar() {
    try { setCalendar(await getReleaseCalendar()); } catch { /* non-fatal */ }
  }
  useEffect(() => { load(); loadCalendar(); }, []);

  const [importing, setImporting] = useState(false);
  const [notifyNew, setNotifyNew] = useState(true);
  async function handleAutoImport() {
    setImporting(true); setError(""); setCalMsg("");
    try {
      const uid = Number(localStorage.getItem("userId")) || null;
      const { added, fetched } = await autoImportReleases(notifyNew ? uid : null);
      setCalMsg(added
        ? `Imported ${added} new release${added === 1 ? "" : "s"} (checked ${fetched} upcoming).${notifyNew && uid ? " You'll be notified when new ones are announced." : ""}`
        : `Already up to date — no new releases (checked ${fetched} upcoming).`);
      await loadCalendar();
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't auto-import right now. Try again shortly.");
    } finally { setImporting(false); }
  }

  async function handleCalImage(file: File | null | undefined) {
    if (!file) return;
    setError(""); setCalMsg("");
    if (file.size > 4 * 1024 * 1024) { setError("That image is over 4MB — crop or screenshot a smaller section."); return; }
    setCalBusy(true); setCalParsed(null);
    try {
      const dataUrl: string = await new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res(r.result as string); r.onerror = rej;
        r.readAsDataURL(file);
      });
      const out = await parseReleaseCalendar(dataUrl);
      if (!out.releases.length) setError("Couldn't find any release rows in that image. Try a clearer screenshot.");
      setCalParsed(out.releases);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't read that screenshot. Try again.");
    } finally { setCalBusy(false); }
  }
  function onCalPaste(e: React.ClipboardEvent) {
    const item = Array.from(e.clipboardData.items).find(i => i.type.startsWith("image/"));
    if (item) { e.preventDefault(); handleCalImage(item.getAsFile()); }
  }
  function editCalRow(i: number, field: keyof ParsedCalendarRow, value: string) {
    setCalParsed(prev => prev ? prev.map((r, idx) => idx === i ? { ...r, [field]: value } : r) : prev);
  }
  function dropCalRow(i: number) {
    setCalParsed(prev => prev ? prev.filter((_, idx) => idx !== i) : prev);
  }
  async function saveCalParsed() {
    if (!calParsed?.length) return;
    setCalBusy(true); setError("");
    try {
      const { added } = await saveReleaseCalendar(calParsed);
      setCalMsg(added ? `Added ${added} release${added === 1 ? "" : "s"} to the calendar.` : "Those were already on the calendar.");
      setCalParsed(null);
      await loadCalendar();
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't save those releases.");
    } finally { setCalBusy(false); }
  }
  async function removeCalItem(id: number) {
    await deleteReleaseCalendarItem(id).catch(() => {});
    setCalendar(prev => prev.filter(r => r.id !== id));
  }

  const userId = Number(localStorage.getItem("userId")) || null;
  async function changeReminder(item: CalendarItem, daysBefore: number | null) {
    if (daysBefore && !userId) {
      setError("Set up your email/phone in the Alerts tab first, then come back to add a reminder.");
      return;
    }
    // optimistic
    setCalendar(prev => prev.map(r => r.id === item.id ? { ...r, notify_days_before: daysBefore, notified_at: null } : r));
    try { await setReleaseReminder(item.id, userId, daysBefore); }
    catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't set the reminder.");
      loadCalendar();
    }
  }
  function fmtCalDate(r: CalendarItem) {
    if (r.release_date) {
      const d = new Date(r.release_date + "T00:00:00");
      return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    }
    return r.date_text || "TBD";
  }
  function calDaysUntil(r: CalendarItem): number | null {
    if (!r.release_date) return null;
    const d = new Date(r.release_date + "T00:00:00");
    return Math.ceil((d.getTime() - Date.now()) / 86400000);
  }
  function seedChecklist(r: CalendarItem) {
    setName(r.product);
    setDate(r.date_text || (r.release_date || ""));
    parseFormRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // One-click eBay search for presale/preorder listings of a product, newest first.
  function presaleUrl(product: string) {
    const kw = encodeURIComponent(`${product} (presale,pre-sale,preorder,pre-order)`);
    return `https://www.ebay.com/sch/i.html?_nkw=${kw}&_sop=10`;
  }

  // Wax allocation + our price (optimistic).
  async function toggleAllocated(r: CalendarItem, allocated: boolean) {
    setCalendar(prev => prev.map(x => x.id === r.id ? { ...x, allocated } : x));
    try { await setReleaseWax(r.id, { allocated }); } catch { loadCalendar(); }
  }
  async function saveWaxPrice(r: CalendarItem, raw: string) {
    const price = raw.trim() ? parseFloat(raw) : 0;
    setCalendar(prev => prev.map(x => x.id === r.id ? { ...x, price: price || null } : x));
    try { await setReleaseWax(r.id, { price }); } catch { loadCalendar(); }
  }
  async function saveWaxQty(r: CalendarItem, raw: string) {
    const alloc_qty = raw.trim() ? parseInt(raw, 10) : 0;
    setCalendar(prev => prev.map(x => x.id === r.id ? { ...x, alloc_qty: alloc_qty || null } : x));
    try { await setReleaseWax(r.id, { alloc_qty }); } catch { loadCalendar(); }
  }

  // Box price comp from eBay sealed-box sales, on demand.
  const [boxComp, setBoxComp] = useState<Record<number, { avg: number; count: number } | "loading" | "none">>({});
  async function loadBoxComp(r: CalendarItem) {
    if (boxComp[r.id]) return;
    setBoxComp(p => ({ ...p, [r.id]: "loading" }));
    try {
      const data = await getSoldHistory(`${r.product} hobby box`);
      const prices: number[] = (data.sold || []).map((s: any) => s.sold_price).filter((n: any) => n > 0).sort((a: number, b: number) => a - b);
      if (prices.length < 2) { setBoxComp(p => ({ ...p, [r.id]: "none" })); return; }
      const avg = prices[Math.floor(prices.length / 2)]; // median
      setBoxComp(p => ({ ...p, [r.id]: { avg, count: prices.length } }));
    } catch { setBoxComp(p => ({ ...p, [r.id]: "none" })); }
  }
  const scUrl = (p: string) => `https://www.steelcitycollectibles.com/search?q=${encodeURIComponent(p + " hobby box")}`;
  const dcwUrl = (p: string) => `https://www.dacardworld.com/catalogsearch/result/?q=${encodeURIComponent(p + " hobby box")}`;

  // What the presale HOBBY BOX is going for on eBay (active listings). Narrowed to
  // boxes so single-card presales don't skew it; shown as the median (typical) price.
  const [presale, setPresale] = useState<Record<number, { med: number; count: number } | "loading" | "none">>({});
  async function loadPresale(r: CalendarItem) {
    if (presale[r.id] === "loading") return;
    setPresale(p => ({ ...p, [r.id]: "loading" }));
    try {
      const data = await searchCards(`${r.product} hobby box presale`);
      const prices: number[] = (data.listings || []).map((l: any) => l.price)
        .filter((n: any) => n >= 20)  // drop single-card noise; a box isn't $1
        .sort((a: number, b: number) => a - b);
      if (prices.length < 1) { setPresale(p => ({ ...p, [r.id]: "none" })); return; }
      setPresale(p => ({ ...p, [r.id]: { med: prices[Math.floor(prices.length / 2)], count: prices.length } }));
    } catch { setPresale(p => ({ ...p, [r.id]: "none" })); }
  }

  const [autoFetchId, setAutoFetchId] = useState<number | null>(null);
  async function autoChecklist(r: CalendarItem) {
    if (!r.source_url) return;
    setAutoFetchId(r.id); setError(""); setCalMsg("");
    try {
      const res = await autoFetchChecklist(r.product, r.source_url, r.date_text || r.release_date);
      await load();
      openProduct(res.product.id);
      setCalMsg(`Pulled ${res.cards.length} cards for ${r.product} — review the target sheet below.`);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't auto-build that checklist. Try the paste box.");
    } finally { setAutoFetchId(null); }
  }

  async function openProduct(id: number) {
    setOpenId(id); setPfilter(""); setOnlyTargets(false);
    try { const r = await getRelease(id); setProduct(r.product); setCards(r.cards); }
    catch { setError("Couldn't open that product."); }
  }

  async function parse(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !text.trim()) { setError("Add a product name and paste a checklist."); return; }
    setParsing(true); setError("");
    try {
      const r = await createRelease(name.trim(), date.trim(), text.trim());
      setName(""); setDate(""); setText("");
      await load();
      openProduct(r.product.id);
    } catch { setError("Couldn't parse that checklist — try a smaller chunk."); }
    finally { setParsing(false); }
  }

  async function toggleTarget(c: ReleaseCard) {
    setCards(prev => prev.map(x => x.id === c.id ? { ...x, targeted: !x.targeted } : x));
    try { await setCardTargeted(c.id, !c.targeted); } catch { setError("Couldn't update target."); load(); }
  }

  async function removeProduct(id: number) {
    if (!confirm("Delete this product and its parsed cards?")) return;
    try { await deleteRelease(id); if (openId === id) { setOpenId(null); setProduct(null); setCards([]); } load(); }
    catch { setError("Couldn't delete."); }
  }

  async function removeAllProducts() {
    if (!products.length) return;
    if (!confirm(`Delete ALL ${products.length} products and their parsed cards? This can't be undone.`)) return;
    try { await deleteAllReleases(); setOpenId(null); setProduct(null); setCards([]); load(); }
    catch { setError("Couldn't delete all."); }
  }

  async function removeAllCalendar() {
    if (!calendar.length) return;
    if (!confirm(`Delete ALL ${calendar.length} calendar releases? This can't be undone.`)) return;
    try { await clearReleaseCalendar(); setCalendar([]); }
    catch { setError("Couldn't clear the calendar."); }
  }

  function copy(t: string, label: string) {
    navigator.clipboard?.writeText(t); setCopied(label); setTimeout(() => setCopied(""), 1500);
  }

  const players = useMemo(() =>
    Array.from(new Set(cards.map(c => (c.player || "").trim()).filter(Boolean))).sort(), [cards]);

  const visible = useMemo(() => {
    const t = pfilter.trim().toLowerCase();
    return cards.filter(c =>
      (!onlyTargets || c.targeted) &&
      (!t || (c.player || "").toLowerCase().includes(t) || (c.parallel || "").toLowerCase().includes(t)
        || (c.subset || "").toLowerCase().includes(t)));
  }, [cards, pfilter, onlyTargets]);

  const targets = useMemo(() => cards.filter(c => c.targeted), [cards]);

  function copySheet() {
    if (!product) return;
    const lines = targets.map(c =>
      `${c.player || ""}\t${c.parallel || ""}\t${c.card_number || ""}\t${c.numbered_to ? "/" + c.numbered_to : ""}\t${searchText(product.name, c)}`);
    copy(["PLAYER\tPARALLEL\tCARD#\t/N\tSEARCH", ...lines].join("\n"), "sheet");
  }

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 920 }}>
      <h1>New Releases</h1>
      <p className="subtitle">Track what's dropping (paste a calendar screenshot), then parse a product's checklist → filter by player → build a target sheet → send to your alerts.</p>

      {/* Release calendar (screenshot → product + date) */}
      <div className="add-alert-box" style={{ marginTop: 18 }} onPaste={onCalPaste} tabIndex={0}>
        <div className="add-alert-title">🗓️ Release calendar</div>

        {/* Auto-import from the web */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
          <button className="btn btn-sm" type="button" onClick={handleAutoImport} disabled={importing}>
            {importing ? "Importing…" : "⤓ Auto-import upcoming releases"}
          </button>
          <label style={{ fontSize: 13, display: "inline-flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
            <input type="checkbox" checked={notifyNew} onChange={e => setNotifyNew(e.target.checked)} />
            🔔 Notify me when new releases are announced
          </label>
        </div>
        <div className="subtitle" style={{ margin: "0 0 12px", fontSize: 12 }}>
          Pulls the upcoming release calendar from the web automatically (refreshes daily). No screenshot needed.
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <label className="btn btn-sm" style={{ cursor: "pointer", background: "rgba(255,255,255,0.1)" }}>
            {calBusy ? "Reading…" : "Upload screenshot"}
            <input type="file" accept="image/*" hidden disabled={calBusy}
              onChange={e => handleCalImage(e.target.files?.[0])} />
          </label>
          <span className="subtitle" style={{ margin: 0, fontSize: 13 }}>
            …or paste a screenshot (⌘/Ctrl-V) to add releases manually
          </span>
        </div>
        {calMsg && <div className="success-msg" style={{ marginTop: 10 }}>{calMsg}</div>}

        {/* Review parsed calendar rows before saving */}
        {calParsed && calParsed.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontWeight: 700, fontSize: 14, marginBottom: 6 }}>Review — {calParsed.length} found</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {calParsed.map((r, i) => (
                <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input className="add-alert-input" value={r.product} placeholder="Product"
                    onChange={e => editCalRow(i, "product", e.target.value)} style={{ flex: 3, fontSize: 13, padding: "6px 9px" }} />
                  <input className="add-alert-input" value={r.date || ""} placeholder="Date"
                    onChange={e => editCalRow(i, "date", e.target.value)} style={{ flex: 1, minWidth: 90, fontSize: 13, padding: "6px 9px" }} />
                  <input className="add-alert-input" value={r.sport || ""} placeholder="Sport"
                    onChange={e => editCalRow(i, "sport", e.target.value)} style={{ flex: 1, minWidth: 80, fontSize: 13, padding: "6px 9px" }} />
                  <button className="btn btn-sm" type="button" onClick={() => dropCalRow(i)} style={{ fontSize: 11, padding: "4px 8px" }}>✕</button>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
              <button className="btn btn-sm" type="button" onClick={saveCalParsed} disabled={calBusy}>
                {calBusy ? "Saving…" : `Save ${calParsed.length} to calendar`}
              </button>
              <button className="btn btn-sm" type="button" onClick={() => setCalParsed(null)}
                style={{ background: "#e2e8f0", color: "#334155" }}>Discard</button>
            </div>
          </div>
        )}

        {/* Saved calendar */}
        {calendar.length > 0 && (
          <div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span className="subtitle" style={{ margin: 0, fontSize: 12 }}>{calendar.length} release{calendar.length === 1 ? "" : "s"} on the calendar</span>
              <button type="button" onClick={removeAllCalendar}
                style={{ background: "none", border: "1px solid rgba(220,38,38,0.5)", color: "#f87171", borderRadius: 8, padding: "4px 10px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                🗑 Clear calendar
              </button>
            </div>
            {calendar.map(r => {
              const du = calDaysUntil(r);
              return (
                <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 12px",
                  border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, background: "#211d3f" }}>
                  <div style={{ minWidth: 92 }}>
                    <div style={{ fontWeight: 700, fontSize: 13, color: "#818cf8" }}>{fmtCalDate(r)}</div>
                    {du != null && du >= 0 && <div style={{ fontSize: 11, color: "#34d399", fontWeight: 600 }}>{du === 0 ? "today" : `in ${du}d`}</div>}
                    {du != null && du < 0 && <div style={{ fontSize: 11, color: "#94a3b8" }}>released</div>}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14, color: "#f1f5f9" }}>
                      {r.product}
                      {r.sport && <span style={{ margin: 0, fontSize: 12, fontWeight: 400, color: "#94a3b8" }}> · {r.sport}</span>}
                    </div>
                    {/* Wax: allocation + our price + box comp */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 5, flexWrap: "wrap", fontSize: 12 }}>
                      <label style={{ display: "inline-flex", alignItems: "center", gap: 4, cursor: "pointer", color: "#cbd5e1", fontWeight: 600 }}>
                        <input type="checkbox" checked={!!r.allocated} onChange={e => toggleAllocated(r, e.target.checked)} />
                        📦 Allocated
                      </label>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 3, color: "#94a3b8" }}>
                        $<input type="number" min="0" defaultValue={r.price ?? ""} placeholder="price/box"
                          onBlur={e => saveWaxPrice(r, e.target.value)}
                          style={{ width: 78, padding: "3px 6px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(0,0,0,0.25)", color: "#fff", fontSize: 12 }} />
                      </span>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 3, color: "#94a3b8" }}>
                        <input type="number" min="0" defaultValue={r.alloc_qty ?? ""} placeholder="qty"
                          title="How many boxes/units allocated"
                          onBlur={e => saveWaxQty(r, e.target.value)}
                          style={{ width: 54, padding: "3px 6px", borderRadius: 6, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(0,0,0,0.25)", color: "#fff", fontSize: 12 }} />
                        <span style={{ fontSize: 11 }}>boxes</span>
                      </span>
                      {boxComp[r.id] === "loading" ? <span style={{ color: "#94a3b8" }}>comp…</span>
                        : typeof boxComp[r.id] === "object" ? <span style={{ color: "#34d399", fontWeight: 700 }}>eBay box ~${(boxComp[r.id] as any).avg.toLocaleString()} <span style={{ color: "#94a3b8", fontWeight: 400 }}>({(boxComp[r.id] as any).count})</span></span>
                        : boxComp[r.id] === "none" ? <span style={{ color: "#94a3b8" }}>no box comps</span>
                        : <button type="button" onClick={() => loadBoxComp(r)} style={{ background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 6, padding: "2px 8px", cursor: "pointer", fontSize: 12, color: "#e2e8f0" }}>💰 Box comp</button>}
                      <a href={scUrl(r.product)} target="_blank" rel="noreferrer" style={{ color: "#60a5fa", textDecoration: "none" }}>SteelCity ↗</a>
                      <a href={dcwUrl(r.product)} target="_blank" rel="noreferrer" style={{ color: "#60a5fa", textDecoration: "none" }}>DACW ↗</a>
                    </div>
                  </div>
                  <select
                    title={r.release_date ? "Remind me before this drops" : "Add a date to enable reminders"}
                    disabled={!r.release_date}
                    value={r.notify_days_before ?? 0}
                    onChange={e => changeReminder(r, Number(e.target.value) || null)}
                    style={{ fontSize: 12, padding: "4px 6px", borderRadius: 8, cursor: r.release_date ? "pointer" : "not-allowed",
                      background: r.notify_days_before ? "rgba(124,58,237,0.18)" : "rgba(255,255,255,0.06)",
                      color: "#e2e8f0", border: "1px solid rgba(255,255,255,0.15)" }}>
                    <option value={0}>🔔 Off</option>
                    <option value={1}>1 day before</option>
                    <option value={3}>3 days before</option>
                    <option value={7}>7 days before</option>
                    <option value={14}>14 days before</option>
                  </select>
                  {presale[r.id] === "loading"
                    ? <span style={{ fontSize: 11, color: "#94a3b8", padding: "4px 6px" }}>presale…</span>
                    : typeof presale[r.id] === "object"
                      ? <a href={presaleUrl(r.product)} target="_blank" rel="noreferrer" title="Median presale hobby-box price on eBay — tap to browse"
                          style={{ fontSize: 11, padding: "4px 10px", textDecoration: "none", borderRadius: 8, fontWeight: 700, background: "rgba(34,197,94,0.18)", color: "#bbf7d0" }}>
                          💵 Presale box ~${(presale[r.id] as any).med.toLocaleString()} <span style={{ opacity: 0.7, fontWeight: 400 }}>({(presale[r.id] as any).count}) ↗</span>
                        </a>
                      : presale[r.id] === "none"
                        ? <a href={presaleUrl(r.product)} target="_blank" rel="noreferrer" style={{ fontSize: 11, padding: "4px 10px", textDecoration: "none", borderRadius: 8, background: "rgba(255,255,255,0.08)", color: "#94a3b8" }}>no presales yet ↗</a>
                        : <button className="btn btn-sm" type="button" onClick={() => loadPresale(r)}
                            title="Check what this product's presale is going for on eBay"
                            style={{ fontSize: 11, padding: "4px 10px", background: "rgba(34,197,94,0.18)", color: "#bbf7d0" }}>
                            🔎 Presale $
                          </button>}
                  {r.source_url && (
                    <button className="btn btn-sm" type="button" onClick={() => autoChecklist(r)}
                      disabled={autoFetchId === r.id} title="Auto-build a starter checklist (key players + parallels + print runs) from the web"
                      style={{ fontSize: 11, padding: "4px 10px" }}>
                      {autoFetchId === r.id ? "Building…" : "🃏 Auto checklist"}
                    </button>
                  )}
                  <button className="btn btn-sm" type="button" onClick={() => seedChecklist(r)}
                    style={{ fontSize: 11, padding: "4px 10px", background: "rgba(255,255,255,0.1)" }}>
                    Paste checklist ↓
                  </button>
                  <button title="Remove" onClick={() => removeCalItem(r.id)}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", fontSize: 14 }}>✕</button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Parse a checklist */}
      <div className="add-alert-box" style={{ marginTop: 18 }} ref={parseFormRef}>
        <div className="add-alert-title">+ Parse a checklist</div>
        <form onSubmit={parse}>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
            <input className="add-alert-input" placeholder="Product (e.g. 2025-26 Bowman Chrome Basketball)"
              value={name} onChange={e => setName(e.target.value)} style={{ flex: 2, minWidth: 220 }} />
            <input className="add-alert-input" placeholder="Release date (optional)"
              value={date} onChange={e => setDate(e.target.value)} style={{ flex: 1, minWidth: 140 }} />
          </div>
          <textarea className="add-alert-input" rows={5}
            placeholder="Paste the checklist here (from Topps / ChecklistInfo). Big lists: paste one set/parallel section at a time."
            value={text} onChange={e => setText(e.target.value)} style={{ width: "100%", resize: "vertical", lineHeight: 1.5 }} />
          {error && <div className="error-msg" style={{ marginTop: 8 }}>{error}</div>}
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }}>
            <button className="btn btn-sm" type="submit" disabled={parsing}>{parsing ? "Parsing…" : "Parse checklist"}</button>
          </div>
        </form>
      </div>

      {/* Products */}
      {loading ? <p className="subtitle" style={{ marginTop: 20 }}>Loading…</p> : (
        <div style={{ marginTop: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {products.map(p => (
            <span key={p.id} style={{ display: "inline-flex", alignItems: "center", gap: 6, border: "1px solid",
              borderColor: openId === p.id ? "#2563eb" : "#cbd5e1", background: openId === p.id ? "#2563eb" : "#fff",
              color: openId === p.id ? "#fff" : "#334155", borderRadius: 999, padding: "5px 8px 5px 12px" }}>
              <button onClick={() => openProduct(p.id)} style={{ background: "none", border: "none", cursor: "pointer",
                color: "inherit", fontSize: 13, fontWeight: 600 }}>
                {p.name} <span style={{ opacity: 0.7, fontWeight: 400 }}>· {p.card_count}{p.release_date ? ` · ${p.release_date}` : ""}</span>
              </button>
              <button onClick={() => removeProduct(p.id)} title="Delete" style={{ background: "none", border: "none",
                cursor: "pointer", color: openId === p.id ? "#fff" : "#94a3b8", fontSize: 13 }}>✕</button>
            </span>
          ))}
          {products.length === 0 && <span className="subtitle">No products yet — parse a checklist above.</span>}
          {products.length > 0 && (
            <button type="button" onClick={removeAllProducts}
              style={{ background: "none", border: "1px solid rgba(220,38,38,0.5)", color: "#f87171", borderRadius: 999, padding: "5px 12px", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
              🗑 Delete all
            </button>
          )}
        </div>
      )}

      {/* Open product: cards table */}
      {product && (
        <div style={{ marginTop: 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 10 }}>
            <h2 style={{ margin: 0, fontSize: 18 }}>{product.name}{product.release_date ? ` — ${product.release_date}` : ""}</h2>
            <span className="subtitle" style={{ margin: 0 }}>{cards.length} cards · {targets.length} targeted</span>
          </div>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
            <input className="add-alert-input" list="release-players" placeholder="Filter by player / parallel…"
              value={pfilter} onChange={e => setPfilter(e.target.value)} style={{ flex: 1, minWidth: 180, fontSize: 13, padding: "6px 9px" }} />
            <datalist id="release-players">{players.map(p => <option key={p} value={p} />)}</datalist>
            <label style={{ fontSize: 13, fontWeight: 600, display: "inline-flex", gap: 5, alignItems: "center", cursor: "pointer" }}>
              <input type="checkbox" checked={onlyTargets} onChange={e => setOnlyTargets(e.target.checked)} /> 🎯 only targets
            </label>
            <button className="btn btn-sm" type="button" onClick={copySheet} disabled={!targets.length}>
              {copied === "sheet" ? "Copied!" : "📋 Copy target sheet"}
            </button>
          </div>

          <div style={{ overflowX: "auto", border: "1px solid #e2e8f0", borderRadius: 10 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, background: "#fff", color: "#0f172a" }}>
              <thead>
                <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                  <th style={{ padding: "8px 10px" }}>🎯</th>
                  <th style={{ padding: "8px 10px" }}>Player</th>
                  <th style={{ padding: "8px 10px" }}>Card #</th>
                  <th style={{ padding: "8px 10px" }}>Parallel</th>
                  <th style={{ padding: "8px 10px" }}>/N</th>
                  <th style={{ padding: "8px 10px" }}>Subset</th>
                  <th style={{ padding: "8px 10px" }}>Search</th>
                </tr>
              </thead>
              <tbody>
                {visible.map(c => (
                  <tr key={c.id} style={{ borderTop: "1px solid #e2e8f0", background: c.targeted ? "#eff6ff" : "#fff" }}>
                    <td style={{ padding: "6px 10px" }}>
                      <input type="checkbox" checked={c.targeted} onChange={() => toggleTarget(c)} style={{ cursor: "pointer" }} />
                    </td>
                    <td style={{ padding: "6px 10px", fontWeight: 600 }}>{c.player || "—"}</td>
                    <td style={{ padding: "6px 10px" }}>{c.card_number || "—"}</td>
                    <td style={{ padding: "6px 10px" }}>{c.parallel || "Base"}</td>
                    <td style={{ padding: "6px 10px" }}>{c.numbered_to ? `/${c.numbered_to}` : "—"}</td>
                    <td style={{ padding: "6px 10px" }}>{c.subset || "—"}</td>
                    <td style={{ padding: "6px 10px" }}>
                      <button className="btn btn-sm" type="button" style={{ fontSize: 11, padding: "3px 8px" }}
                        onClick={() => copy(searchText(product.name, c), `c${c.id}`)}>
                        {copied === `c${c.id}` ? "Copied!" : "Copy"}
                      </button>
                    </td>
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr><td colSpan={7} style={{ padding: 16, textAlign: "center", color: "#64748b" }}>No cards match.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 8 }}>
            Tip: check the 🎯 boxes to build your sheet, "Copy" a card's search text, then paste it into the <strong>Alerts</strong> tab's "Add a card" box.
          </div>
        </div>
      )}
    </div>
  );
}

export default function ReleasesPage() {
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
  if (!unlocked) return <ShopPasswordForm title="New Releases" onUnlocked={() => setUnlocked(true)} />;
  return <Board />;
}
