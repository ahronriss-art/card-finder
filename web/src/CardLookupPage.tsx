import { useState, useEffect } from "react";
import { cardLookup, cardLookupUrl, cardChat, getPopLookups, savePopLookup, deletePopLookup, clearPopLookups,
  listMyFinds, type Find, type CardLookupResult, type PopLookupRow as SavedLookup } from "./api/client";

// Downscale a data URL to a small JPEG thumbnail so saved screenshots stay tiny in localStorage.
function makeThumb(dataUrl: string, max = 240): Promise<string> {
  return new Promise(resolve => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, max / Math.max(img.width, img.height));
      const w = Math.round(img.width * scale), h = Math.round(img.height * scale);
      const canvas = document.createElement("canvas");
      canvas.width = w; canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) { resolve(dataUrl); return; }
      ctx.drawImage(img, 0, 0, w, h);
      try { resolve(canvas.toDataURL("image/jpeg", 0.6)); } catch { resolve(dataUrl); }
    };
    img.onerror = () => resolve(dataUrl);
    img.src = dataUrl;
  });
}

// Snap, upload, paste, or drag a card photo -> Claude IDs it -> eBay comps -> price + buy rec.
export default function CardLookupPage() {
  const [preview, setPreview] = useState<string>("");        // data URL for <img>
  const [b64, setB64] = useState<string>("");                // bare base64
  const [mediaType, setMediaType] = useState<string>("image/jpeg");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<CardLookupResult | null>(null);
  const [dragging, setDragging] = useState(false);
  const [aiMsgs, setAiMsgs] = useState<{ role: string; content: string }[]>([]);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiInput, setAiInput] = useState("");
  const [history, setHistory] = useState<SavedLookup[]>([]);
  const [finds, setFinds] = useState<Find[]>([]);

  const aiContext = () => ({ card: result?.card, pricing: result?.pricing, pop: result?.pop, query: result?.query });

  // Load saved lookups (synced to your account, across devices).
  useEffect(() => {
    getPopLookups().then(setHistory).catch(() => {});
  }, []);

  // Recent finds (with photos) — one-tap to run a pop lookup on that card.
  useEffect(() => {
    listMyFinds(24).then(rows => setFinds(rows.filter(f => f.image_url))).catch(() => {});
  }, []);

  // Run the lookup on a recent find's photo (server fetches the image URL).
  async function analyzeFind(f: Find) {
    if (loading || !f.image_url) return;
    setPreview(f.image_url); setB64(""); setResult(null); setError(""); setLoading(true);
    try {
      const res = await cardLookupUrl(f.image_url);
      setResult(res);
      if (res?.identified) saveToHistory(res, f.image_url);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't analyze that find. Try uploading the photo instead.");
    } finally {
      setLoading(false);
    }
  }

  async function saveToHistory(res: CardLookupResult, srcDataUrl: string) {
    if (!res?.identified) return;
    const thumb = await makeThumb(srcDataUrl);
    try {
      const { id } = await savePopLookup(thumb, res);
      setHistory(prev => [{ id, thumb, result: res, ts: Date.now() }, ...prev].slice(0, 24));
    } catch { /* ignore save failures — the lookup still shows */ }
  }

  function openSaved(item: SavedLookup) {
    setResult(item.result); setPreview(item.thumb); setB64(""); setError("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function deleteSaved(id: number) {
    setHistory(prev => prev.filter(x => x.id !== id));
    deletePopLookup(id).catch(() => {});
  }
  function clearHistory() {
    setHistory([]);
    clearPopLookups().catch(() => {});
  }

  // Auto-generate the AI verdict when a new card is identified.
  useEffect(() => {
    if (!result?.identified) { setAiMsgs([]); return; }
    let cancelled = false;
    setAiMsgs([]); setAiLoading(true);
    cardChat({ card: result.card, pricing: result.pricing, pop: result.pop, query: result.query }, [])
      .then(r => { if (!cancelled) setAiMsgs([{ role: "assistant", content: r.answer }]); })
      .catch(() => { if (!cancelled) setAiMsgs([{ role: "assistant", content: "(AI summary unavailable right now — try again.)" }]); })
      .finally(() => { if (!cancelled) setAiLoading(false); });
    return () => { cancelled = true; };
  }, [result]);

  async function askAi() {
    const q = aiInput.trim();
    if (!q || aiLoading) return;
    const next = [...aiMsgs, { role: "user", content: q }];
    setAiMsgs(next); setAiInput(""); setAiLoading(true);
    try {
      const r = await cardChat(aiContext(), next);
      setAiMsgs([...next, { role: "assistant", content: r.answer }]);
    } catch {
      setAiMsgs([...next, { role: "assistant", content: "(Couldn't answer — try again.)" }]);
    } finally { setAiLoading(false); }
  }

  function loadFile(file: File | null | undefined) {
    if (!file || !file.type.startsWith("image/")) return;
    setResult(null); setError("");
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      setPreview(dataUrl);
      setMediaType(file.type || "image/jpeg");
      setB64(dataUrl.includes(",") ? dataUrl.split(",")[1] : dataUrl);
    };
    reader.readAsDataURL(file);
  }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    loadFile(e.target.files?.[0]);
  }

  // Paste a screenshot from the clipboard (Cmd/Ctrl+V) anywhere on the page.
  useEffect(() => {
    function onPaste(e: ClipboardEvent) {
      const img = Array.from(e.clipboardData?.items || []).find(i => i.type.startsWith("image/"));
      if (img) { e.preventDefault(); loadFile(img.getAsFile()); }
    }
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, []);

  async function analyze() {
    if (!b64 || loading) return;
    setLoading(true); setError(""); setResult(null);
    try {
      const res = await cardLookup(b64, mediaType);
      setResult(res);
      if (res?.identified) saveToHistory(res, preview);  // archive the screenshot + result
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't analyze that card. Try a clearer photo.");
    } finally {
      setLoading(false);
    }
  }

  const card = result?.card;
  const p = result?.pricing;
  const money = (n?: number | null) => (n == null ? "—" : `$${n.toLocaleString()}`);
  const profitColor = (pp?: number) => (pp == null ? "#475569" : pp >= 60 ? "#15803d" : pp >= 35 ? "#b45309" : "#b91c1c");

  return (
    <div style={{ maxWidth: 760, margin: "24px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>Pop Report</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Snap, upload, <strong>paste a screenshot</strong>, or drag in a photo of a card. We identify it, pull eBay sold comps, and tell you the market value, a buy price, and the odds it flips for profit.
      </p>

      {/* Paste / drag drop zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); loadFile(e.dataTransfer.files?.[0]); }}
        style={{
          border: `2px dashed ${dragging ? "#2563eb" : "#cbd5e1"}`,
          background: dragging ? "rgba(37,99,235,0.06)" : "#f8fafc",
          borderRadius: 12, padding: "20px 16px", textAlign: "center", color: "#64748b",
          margin: "14px 0",
        }}
      >
        📋 <strong>Paste a screenshot</strong> here (Cmd/Ctrl+V) or drag an image in
      </div>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start", margin: "8px 0 16px" }}>
        <label style={{ display: "inline-block", cursor: "pointer", background: "#2563eb", color: "#fff", borderRadius: 8, padding: "10px 18px", fontWeight: 600, fontSize: 14 }}>
          📷 Choose / take photo
          <input type="file" accept="image/*" capture="environment" onChange={onFile} style={{ display: "none" }} />
        </label>
        {preview && (
          <button onClick={analyze} disabled={loading}
            style={{ background: loading ? "#94a3b8" : "#16a34a", color: "#fff", border: "none", borderRadius: 8, padding: "10px 22px", fontWeight: 700, fontSize: 14, cursor: loading ? "default" : "pointer" }}>
            {loading ? "Analyzing…" : "🔍 Analyze card"}
          </button>
        )}
      </div>

      {/* Recent finds — tap one to run a pop lookup on that card's photo (no re-upload) */}
      {finds.length > 0 && (
        <div style={{ margin: "4px 0 16px" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#475569", marginBottom: 8 }}>
            🃏 Recent finds — tap to look up
          </div>
          <div style={{ display: "flex", gap: 10, overflowX: "auto", paddingBottom: 6 }}>
            {finds.map((f, i) => (
              <button key={i} type="button" onClick={() => analyzeFind(f)} disabled={loading} title={f.title || ""}
                style={{ flex: "0 0 auto", width: 96, background: "#fff", border: "1px solid #e2e8f0",
                  borderRadius: 10, padding: 6, cursor: loading ? "default" : "pointer", textAlign: "left" }}>
                <img src={f.image_url || ""} alt={f.title || "find"}
                  style={{ width: "100%", height: 96, objectFit: "cover", borderRadius: 6, background: "#f1f5f9" }} />
                <div style={{ fontSize: 10, lineHeight: 1.25, color: "#475569", marginTop: 4,
                  display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                  {f.title || "—"}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {preview && (
        <img src={preview} alt="card" style={{ maxWidth: 220, maxHeight: 300, borderRadius: 10, border: "1px solid #e2e8f0", marginBottom: 12 }} />
      )}

      {error && <div style={{ color: "#dc2626", marginTop: 8 }}>{error}</div>}

      {result && !result.identified && (
        <div style={{ marginTop: 12, background: "#fef9c3", border: "1px solid #fde047", borderRadius: 8, padding: 14, color: "#854d0e" }}>
          Couldn't confidently identify a card in that photo{card?.notes ? ` — ${card.notes}` : ""}. Try a clearer, well-lit, straight-on shot.
        </div>
      )}

      {result?.identified && (
        <div style={{ marginTop: 8 }}>
          {/* Identity */}
          <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 12, padding: 16 }}>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#0f172a" }}>
              {[card.year, card.brand, card.player].filter(Boolean).join(" ") || "Card"}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
              {card.parallel && <span style={chip}>{card.parallel}</span>}
              {card.card_number && <span style={chip}>#{card.card_number}</span>}
              {card.is_graded && <span style={{ ...chip, background: "rgba(124,58,237,0.12)", color: "#7c3aed" }}>{[card.grader, card.grade].filter(Boolean).join(" ")}{card.cert_number ? ` · cert ${card.cert_number}` : ""}</span>}
              <span style={{ ...chip, background: "rgba(100,116,139,0.12)", color: "#475569" }}>confidence: {card.confidence}</span>
            </div>
            {card.notes && <div style={{ color: "#64748b", fontSize: 13, marginTop: 8 }}>{card.notes}</div>}
            {(() => {
              const q = [card.year, card.brand, card.player, card.parallel].filter(Boolean).join(" ");
              if (!q) return null;
              const grUrl = `https://www.google.com/search?q=${encodeURIComponent("site:gemrate.com " + q)}`;
              const psaUrl = `https://www.google.com/search?q=${encodeURIComponent("psacard.com pop report " + q)}`;
              const soldUrl = `https://www.ebay.com/sch/i.html?_nkw=${encodeURIComponent(q + (card.is_graded && card.grade ? ` ${card.grader || "PSA"} ${card.grade}` : ""))}&LH_Sold=1&LH_Complete=1&_sop=13`;
              return (
                <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 12 }}>
                  <a href={soldUrl} target="_blank" rel="noreferrer" style={{ fontSize: 13, fontWeight: 700, color: "#16a34a", textDecoration: "none" }}>
                    💰 Real sold prices on eBay ↗
                  </a>
                  <a href={grUrl} target="_blank" rel="noreferrer" style={{ fontSize: 13, fontWeight: 700, color: "#7c3aed", textDecoration: "none" }}>
                    🔎 Pop / gem rate on GemRate ↗
                  </a>
                  <a href={psaUrl} target="_blank" rel="noreferrer" style={{ fontSize: 13, fontWeight: 700, color: "#0369a1", textDecoration: "none" }}>
                    📊 PSA Pop Report ↗
                  </a>
                </div>
              );
            })()}
          </div>

          {/* Pricing */}
          {p && p.count ? (
            <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
              <Stat label="Market value" value={money(p.market)} hint={`${p.count} sold comps`} color="#15803d" big />
              <Stat label="Last sold" value={money(p.last_sold)} color="#0369a1" />
              <Stat label="Recommended buy" value={money(p.recommended_buy)} color="#1d4ed8" hint="≈70% of market" />
              <Stat label="Profit probability" value={p.profit_probability != null ? `${p.profit_probability}%` : "—"} color={profitColor(p.profit_probability)} hint={`net ≈ ${money(p.expected_profit)} after ${p.fees_pct}% fees`} />
              <Stat label="Comp range" value={`${money(p.low)} – ${money(p.high)}`} color="#7e22ce" />
            </div>
          ) : (
            <div style={{ marginTop: 14, color: "#64748b" }}>
              No eBay sold comps found for this card yet — can't price it. (Searched: <em>{result.query}</em>)
            </div>
          )}

          {/* AI advisor */}
          <div style={{ marginTop: 14, background: "#0f172a", border: "1px solid #1e293b", borderRadius: 12, padding: 16 }}>
            <div style={{ fontWeight: 700, color: "#e2e8f0", marginBottom: 10 }}>🤖 AI verdict</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {aiMsgs.map((m, i) => (
                <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "92%",
                  background: m.role === "user" ? "#2563eb" : "#1e293b", color: m.role === "user" ? "#fff" : "#e2e8f0",
                  padding: "9px 13px", borderRadius: 10, fontSize: 14, lineHeight: 1.45, whiteSpace: "pre-wrap" }}>
                  {m.content}
                </div>
              ))}
              {aiLoading && <div style={{ color: "#94a3b8", fontSize: 13 }}>Thinking…</div>}
            </div>
            <form onSubmit={e => { e.preventDefault(); askAi(); }} style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <input
                value={aiInput}
                onChange={e => setAiInput(e.target.value)}
                placeholder="Ask a follow-up… (e.g. is it a buy at $80?)"
                style={{ flex: 1, padding: 10, borderRadius: 8, border: "1px solid #334155", background: "#1e293b", color: "#e2e8f0", fontSize: 14 }}
              />
              <button type="submit" disabled={aiLoading || !aiInput.trim()}
                style={{ background: aiLoading || !aiInput.trim() ? "#475569" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "0 16px", fontWeight: 600, cursor: aiLoading || !aiInput.trim() ? "default" : "pointer" }}>
                Ask
              </button>
            </form>
          </div>

          {/* Comps */}
          {result.comps && result.comps.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>
                Recent sold comps{" "}
                <span style={{ fontSize: 12, fontWeight: 500, color: result.exact_comps ? "#16a34a" : "#b45309" }}>
                  {result.exact_comps ? "· exact card" : "· broader (no exact-match comps found)"}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {result.comps.map((c, i) => (
                  <a key={i} href={c.url || "#"} target="_blank" rel="noreferrer"
                    style={{ display: "flex", gap: 12, alignItems: "center", padding: 8, border: "1px solid #e2e8f0", borderRadius: 8, textDecoration: "none", color: "#0f172a", background: "#fff" }}>
                    {c.image_url
                      ? <img src={c.image_url} alt="" style={{ width: 48, height: 48, objectFit: "cover", borderRadius: 6, border: "1px solid #e2e8f0" }} />
                      : <div style={{ width: 48, height: 48, borderRadius: 6, background: "#f1f5f9" }} />}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13, lineHeight: 1.3 }}>{c.title}</div>
                    </div>
                    <span style={{ fontWeight: 700, color: "#16a34a" }}>{money(c.price)}</span>
                  </a>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Saved lookups — thumbnails of past screenshots, click to revisit */}
      {history.length > 0 && (
        <div style={{ marginTop: 26, borderTop: "1px solid #e2e8f0", paddingTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <div style={{ fontWeight: 800, color: "#0f172a", fontSize: 16 }}>🗂️ Saved lookups ({history.length})</div>
            <button onClick={clearHistory} style={{ background: "none", border: "none", color: "#94a3b8", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>Clear all</button>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))", gap: 10 }}>
            {history.map(item => (
              <div key={item.id} onClick={() => openSaved(item)} title="Click to reopen"
                style={{ position: "relative", border: "1px solid #e2e8f0", borderRadius: 10, overflow: "hidden", background: "#fff", cursor: "pointer" }}>
                <button onClick={e => { e.stopPropagation(); deleteSaved(item.id); }} aria-label="Delete"
                  style={{ position: "absolute", top: 4, right: 4, background: "rgba(15,23,42,0.65)", color: "#fff", border: "none", borderRadius: 12, width: 20, height: 20, fontSize: 13, lineHeight: 1, cursor: "pointer" }}>×</button>
                <img src={item.thumb} alt="" style={{ width: "100%", height: 108, objectFit: "cover", display: "block" }} />
                <div style={{ padding: "6px 8px" }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "#0f172a", lineHeight: 1.25, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {[item.result.card?.player, item.result.card?.parallel].filter(Boolean).join(" ") || "Card"}
                  </div>
                  <div style={{ fontSize: 11, fontWeight: 800, color: "#15803d", marginTop: 2 }}>
                    {item.result.pricing?.market != null ? `$${item.result.pricing.market.toLocaleString()}` : "—"}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const chip: React.CSSProperties = { fontSize: 12, fontWeight: 600, padding: "3px 9px", borderRadius: 6, background: "rgba(37,99,235,0.1)", color: "#2563eb" };

function Stat({ label, value, hint, color, big }: { label: string; value: string; hint?: string; color?: string; big?: boolean }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #cbd5e1", borderRadius: 10, padding: 12 }}>
      <div style={{ fontSize: 12, color: "#475569", fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.3 }}>{label}</div>
      <div style={{ fontSize: big ? 28 : 22, fontWeight: 900, color: color || "#0f172a", marginTop: 3, lineHeight: 1.1 }}>{value}</div>
      {hint && <div style={{ fontSize: 11, color: "#64748b", marginTop: 3 }}>{hint}</div>}
    </div>
  );
}
