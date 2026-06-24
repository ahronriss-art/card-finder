import { useState } from "react";
import { cardLookup, type CardLookupResult } from "./api/client";

// Snap or upload a card photo -> Claude IDs it -> eBay comps -> price + buy rec.
export default function CardLookupPage() {
  const [preview, setPreview] = useState<string>("");        // data URL for <img>
  const [b64, setB64] = useState<string>("");                // bare base64
  const [mediaType, setMediaType] = useState<string>("image/jpeg");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<CardLookupResult | null>(null);

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
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

  async function analyze() {
    if (!b64 || loading) return;
    setLoading(true); setError(""); setResult(null);
    try {
      setResult(await cardLookup(b64, mediaType));
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't analyze that card. Try a clearer photo.");
    } finally {
      setLoading(false);
    }
  }

  const card = result?.card;
  const p = result?.pricing;
  const money = (n?: number | null) => (n == null ? "—" : `$${n.toLocaleString()}`);
  const profitColor = (pp?: number) => (pp == null ? "#64748b" : pp >= 60 ? "#16a34a" : pp >= 35 ? "#d97706" : "#dc2626");

  return (
    <div style={{ maxWidth: 760, margin: "24px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>Card Lookup</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Snap or upload a photo of a card. We identify it, pull eBay sold comps, and tell you the market value, a buy price, and the odds it flips for profit.
      </p>

      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start", margin: "16px 0" }}>
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
            <div style={{ fontSize: 18, fontWeight: 700 }}>
              {[card.year, card.brand, card.player].filter(Boolean).join(" ") || "Card"}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
              {card.parallel && <span style={chip}>{card.parallel}</span>}
              {card.card_number && <span style={chip}>#{card.card_number}</span>}
              {card.is_graded && <span style={{ ...chip, background: "rgba(124,58,237,0.12)", color: "#7c3aed" }}>{[card.grader, card.grade].filter(Boolean).join(" ")}{card.cert_number ? ` · cert ${card.cert_number}` : ""}</span>}
              <span style={{ ...chip, background: "rgba(100,116,139,0.12)", color: "#475569" }}>confidence: {card.confidence}</span>
            </div>
            {card.notes && <div style={{ color: "#64748b", fontSize: 13, marginTop: 8 }}>{card.notes}</div>}
          </div>

          {/* Pricing */}
          {p && p.count ? (
            <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
              <Stat label="Market value" value={money(p.market)} hint={`${p.count} sold comps`} big />
              <Stat label="Last sold" value={money(p.last_sold)} />
              <Stat label="Recommended buy" value={money(p.recommended_buy)} hint="≈70% of market" />
              <Stat label="Profit probability" value={p.profit_probability != null ? `${p.profit_probability}%` : "—"} color={profitColor(p.profit_probability)} hint={`net ≈ ${money(p.expected_profit)} after ${p.fees_pct}% fees`} />
              <Stat label="Comp range" value={`${money(p.low)} – ${money(p.high)}`} />
            </div>
          ) : (
            <div style={{ marginTop: 14, color: "#64748b" }}>
              No eBay sold comps found for this card yet — can't price it. (Searched: <em>{result.query}</em>)
            </div>
          )}

          {/* Pop report placeholder (Phase 2) */}
          <div style={{ marginTop: 14, background: "#f1f5f9", border: "1px dashed #cbd5e1", borderRadius: 10, padding: "10px 14px", fontSize: 13, color: "#64748b" }}>
            📊 Pop report (total graded, # of PSA 10s, gem rate) — coming once the PSA API token is added.
          </div>

          {/* Comps */}
          {result.comps && result.comps.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>Recent sold comps</div>
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
    </div>
  );
}

const chip: React.CSSProperties = { fontSize: 12, fontWeight: 600, padding: "3px 9px", borderRadius: 6, background: "rgba(37,99,235,0.1)", color: "#2563eb" };

function Stat({ label, value, hint, color, big }: { label: string; value: string; hint?: string; color?: string; big?: boolean }) {
  return (
    <div style={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, padding: 12 }}>
      <div style={{ fontSize: 12, color: "#64748b", fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: big ? 24 : 20, fontWeight: 800, color: color || "#0f172a", marginTop: 2 }}>{value}</div>
      {hint && <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>{hint}</div>}
    </div>
  );
}
