import { useEffect, useMemo, useState } from "react";
import { getNews, type NewsItem } from "./api/client";

// One spot for card-world news — cards, auctions, pulls, releases, grading.
// Aggregated from Google News (server-side), refreshed on load.
const CATS: { key: string; label: string }[] = [
  { key: "all", label: "All" },
  { key: "news", label: "📰 General" },
  { key: "auctions", label: "🔨 Auctions" },
  { key: "pulls", label: "🎣 Pulls" },
  { key: "releases", label: "📦 Releases" },
  { key: "grading", label: "🏅 Grading" },
];
const CAT_TAG: Record<string, string> = {
  news: "📰", auctions: "🔨", pulls: "🎣", releases: "📦", grading: "🏅",
};

export default function NewsPage() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [cat, setCat] = useState("all");

  async function load() {
    setLoading(true); setError("");
    try { setItems((await getNews()).items); }
    catch { setError("Couldn't load news right now — try again in a moment."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  const shown = useMemo(
    () => cat === "all" ? items : items.filter(i => i.category === cat),
    [items, cat]);

  function ago(iso: string | null) {
    if (!iso) return "";
    const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 60) return `${Math.max(1, mins)}m ago`;
    if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
    return `${Math.round(mins / 1440)}d ago`;
  }

  return (
    <div className="app" style={{ paddingTop: 32, paddingBottom: 48, maxWidth: 760 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
        <h1 style={{ marginBottom: 4 }}>📰 News</h1>
        <button className="btn btn-sm" type="button" onClick={load} disabled={loading}
          style={{ background: "rgba(255,255,255,0.1)" }}>{loading ? "Loading…" : "↻ Refresh"}</button>
      </div>
      <p className="subtitle">Everything happening in the card world — cards, auctions, pulls, new releases, grading — in one feed.</p>

      {/* Category filter */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "12px 0 6px" }}>
        {CATS.map(c => (
          <button key={c.key} type="button" onClick={() => setCat(c.key)}
            style={{ fontSize: 13, fontWeight: 700, padding: "5px 12px", borderRadius: 999, cursor: "pointer",
              border: cat === c.key ? "1px solid #7c3aed" : "1px solid rgba(255,255,255,0.15)",
              background: cat === c.key ? "rgba(124,58,237,0.25)" : "rgba(255,255,255,0.05)", color: "#e2e8f0" }}>
            {c.label}
          </button>
        ))}
      </div>

      {error && <div className="error-msg" style={{ marginTop: 12 }}>{error}</div>}
      {loading && items.length === 0 && <p className="subtitle" style={{ marginTop: 16 }}>Loading the latest…</p>}
      {!loading && shown.length === 0 && !error && <p className="subtitle" style={{ marginTop: 16 }}>No stories in this category right now.</p>}

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
        {shown.map((it, i) => (
          <a key={i} href={it.url} target="_blank" rel="noreferrer"
            style={{ display: "block", padding: "12px 14px", borderRadius: 12, textDecoration: "none",
              background: "#211d3f", border: "1px solid rgba(255,255,255,0.1)", color: "#f1f5f9" }}>
            <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.35 }}>
              {CAT_TAG[it.category] ? `${CAT_TAG[it.category]} ` : ""}{it.title}
            </div>
            <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 5 }}>
              {it.source}{it.source && it.published ? " · " : ""}{ago(it.published)}
            </div>
          </a>
        ))}
      </div>
    </div>
  );
}
