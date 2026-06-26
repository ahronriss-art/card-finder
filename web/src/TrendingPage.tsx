import { useEffect, useState } from "react";
import { getTrendingCards, type TrendingCard } from "./api/client";

// Most-watched trading cards on eBay right now, with filters by type/sport/etc.
const TYPES = [
  { key: "all", label: "All" },
  { key: "singles", label: "Singles" },
  { key: "boxes", label: "Sealed boxes" },
  { key: "packs", label: "Packs" },
  { key: "lots", label: "Lots" },
  { key: "breaks", label: "Breaks" },
  { key: "pokemon", label: "Pokémon/TCG" },
];
const SPORTS = [
  { key: "all", label: "All sports" },
  { key: "Basketball", label: "🏀 Basketball" },
  { key: "Football", label: "🏈 Football" },
  { key: "Baseball", label: "⚾ Baseball" },
  { key: "Soccer", label: "⚽ Soccer" },
  { key: "Hockey", label: "🏒 Hockey" },
  { key: "UFC/MMA", label: "🥊 UFC/MMA" },
  { key: "Pokémon/TCG", label: "🃏 Pokémon/TCG" },
  { key: "Mixed/Lot", label: "📦 Mixed/Lot" },
  { key: "Other", label: "Other" },
];

export default function TrendingPage() {
  const [cards, setCards] = useState<TrendingCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [type, setType] = useState("all");
  const [sport, setSport] = useState("all");
  const [gradedOnly, setGradedOnly] = useState(false);
  const [autosOnly, setAutosOnly] = useState(false);
  const [maxPrice, setMaxPrice] = useState("");

  async function load(cat = type) {
    setLoading(true); setError("");
    try { setCards((await getTrendingCards(cat)).cards || []); }
    catch { setError("Couldn't load trending cards right now. Try again in a moment."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(type); /* eslint-disable-next-line */ }, [type]);

  const max = parseFloat(maxPrice);
  const shown = cards.filter(c =>
    (sport === "all" || c.sport === sport) &&
    (!gradedOnly || c.graded) &&
    (!autosOnly || c.auto) &&
    (!maxPrice || isNaN(max) || (c.price != null && c.price <= max))
  );

  const pill = (active: boolean): React.CSSProperties => ({
    fontSize: 13, fontWeight: 600, padding: "6px 12px", borderRadius: 999, cursor: "pointer",
    border: active ? "1px solid #2563eb" : "1px solid #cbd5e1",
    background: active ? "#2563eb" : "#fff", color: active ? "#fff" : "#334155", whiteSpace: "nowrap",
  });

  return (
    <div style={{ maxWidth: 860, margin: "24px auto", padding: "0 16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ fontSize: 24, marginBottom: 4 }}>Trending</h1>
          <p style={{ color: "#94a3b8", marginTop: 0, fontSize: 14 }}>
            The most-watched cards on eBay right now. Filter by type, sport, and more.
          </p>
        </div>
        <button onClick={() => load(type)} disabled={loading}
          style={{ background: loading ? "#475569" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "8px 16px", fontWeight: 600, fontSize: 13, cursor: loading ? "default" : "pointer" }}>
          {loading ? "Loading…" : "↻ Refresh"}
        </button>
      </div>

      {/* Filters */}
      <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 10 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", marginBottom: 6 }}>Type</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {TYPES.map(t => <button key={t.key} style={pill(type === t.key)} onClick={() => setType(t.key)}>{t.label}</button>)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", textTransform: "uppercase", marginBottom: 6 }}>Sport <span style={{ textTransform: "none", fontWeight: 500 }}>(best-effort — eBay omits sport from many titles)</span></div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {SPORTS.map(s => <button key={s.key} style={pill(sport === s.key)} onClick={() => setSport(s.key)}>{s.label}</button>)}
          </div>
        </div>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center", marginTop: 2 }}>
          <label style={{ fontSize: 13, color: "#334155", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={gradedOnly} onChange={e => setGradedOnly(e.target.checked)} /> Graded only
          </label>
          <label style={{ fontSize: 13, color: "#334155", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={autosOnly} onChange={e => setAutosOnly(e.target.checked)} /> Autos only
          </label>
          <label style={{ fontSize: 13, color: "#334155", display: "flex", alignItems: "center", gap: 6 }}>
            Max $<input type="number" value={maxPrice} onChange={e => setMaxPrice(e.target.value)} placeholder="any"
              style={{ width: 90, padding: "5px 8px", borderRadius: 6, border: "1px solid #cbd5e1", fontSize: 13 }} />
          </label>
          {shown.length !== cards.length && (
            <button onClick={() => { setSport("all"); setGradedOnly(false); setAutosOnly(false); setMaxPrice(""); }}
              style={{ fontSize: 12, color: "#64748b", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>clear filters</button>
          )}
        </div>
      </div>

      {error && <div style={{ color: "#f87171", marginTop: 12 }}>{error}</div>}
      {!loading && !error && (
        <div style={{ color: "#94a3b8", fontSize: 13, marginTop: 14 }}>
          {shown.length} of {cards.length} shown
        </div>
      )}
      {loading && cards.length === 0 && <div style={{ color: "#94a3b8", marginTop: 16 }}>Loading the hottest cards…</div>}

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 10 }}>
        {shown.map((c, i) => (
          <a key={i} href={c.url || "#"} target="_blank" rel="noreferrer"
            style={{ display: "flex", gap: 14, alignItems: "center", padding: 12, borderRadius: 12, textDecoration: "none",
              background: "#fff", border: "1px solid #e2e8f0", color: "#0f172a" }}>
            <div style={{ fontSize: 20, fontWeight: 900, color: "#94a3b8", width: 30, textAlign: "center", flexShrink: 0 }}>{i + 1}</div>
            {c.image_url
              ? <img src={c.image_url} alt="" style={{ width: 64, height: 64, objectFit: "cover", borderRadius: 8, border: "1px solid #e2e8f0", flexShrink: 0 }} />
              : <div style={{ width: 64, height: 64, borderRadius: 8, background: "#f1f5f9", flexShrink: 0 }} />}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 14, lineHeight: 1.35 }}>{c.title}</div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 5, flexWrap: "wrap" }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: "#dc2626", background: "rgba(220,38,38,0.1)", padding: "2px 8px", borderRadius: 6 }}>
                  👀 {c.watch_count.toLocaleString()}
                </span>
                {c.sport && c.sport !== "Other" && <span style={{ fontSize: 11, fontWeight: 600, color: "#475569", background: "rgba(100,116,139,0.12)", padding: "2px 8px", borderRadius: 6 }}>{c.sport}</span>}
                {c.graded && <span style={{ fontSize: 11, fontWeight: 600, color: "#7c3aed", background: "rgba(124,58,237,0.12)", padding: "2px 8px", borderRadius: 6 }}>graded</span>}
                {c.price != null && <span style={{ fontSize: 15, fontWeight: 800, color: "#16a34a" }}>${c.price.toLocaleString()}</span>}
              </div>
            </div>
          </a>
        ))}
        {!loading && shown.length === 0 && cards.length > 0 && (
          <div style={{ color: "#94a3b8", marginTop: 8 }}>No cards match these filters — try widening them.</div>
        )}
      </div>
    </div>
  );
}
