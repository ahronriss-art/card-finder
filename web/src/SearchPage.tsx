import { useState } from "react";
import { searchCards } from "./api/client";

const SPORTS = ["All", "NBA", "NFL", "MLB", "NHL", "Pokemon", "UFC", "Soccer"];

const VERDICT_COLORS: Record<string, string> = {
  great_deal: "#16a34a", good_deal: "#65a30d",
  fair: "#ca8a04", overpriced: "#dc2626", unknown: "#6b7280",
};
const VERDICT_LABELS: Record<string, string> = {
  great_deal: "GREAT DEAL", good_deal: "Good Deal",
  fair: "Fair Price", overpriced: "Overpriced", unknown: "No Data",
};
const SOURCE_LABELS: Record<string, string> = {
  ebay: "eBay", cardladder: "CardLadder", alt: "ALT",
};

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [sport, setSport] = useState("All");
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    try {
      const data = await searchCards(query, sport === "All" ? undefined : sport);
      setResults(data.listings || []);
      if ((data.listings || []).length === 0) setError("No listings found. Try a different search.");
    } catch {
      setError("Search failed. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app" style={{ paddingTop: 32, paddingBottom: 48 }}>
      <h1>Card Finder</h1>
      <p className="subtitle">Search sports cards across eBay, CardLadder, and ALT — with live price analysis.</p>

      <form className="search-bar" onSubmit={handleSearch}>
        <input
          type="text"
          placeholder="Search cards (e.g. LeBron James 2003 Rookie PSA 9)"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
        <button className="btn" type="submit" disabled={loading}>
          {loading ? "Searching..." : "Search"}
        </button>
      </form>

      <div className="sports-row">
        {SPORTS.map(s => (
          <button key={s} className={`chip${sport === s ? " active" : ""}`} onClick={() => setSport(s)}>
            {s}
          </button>
        ))}
      </div>

      {error && <div className="error-msg">{error}</div>}

      {loading && (
        <div className="loading">
          <div className="spinner" />
          Searching listings...
        </div>
      )}

      {!loading && results.length > 0 && (
        <>
          <p className="results-count">{results.length} listings found across eBay, CardLadder & ALT</p>
          <div className="cards-grid">
            {results.map((item, i) => {
              const verdict = item.analysis?.verdict || "unknown";
              const avg = item.analysis?.avg_sold_price;
              const recentSold = item.analysis?.most_recent_sold;
              const recentDate = item.analysis?.most_recent_date;
              const pct = item.analysis?.pct_vs_market;
              const hasRealUrl = item.listing_url && item.listing_url !== "https://ebay.com";

              return (
                <div className="card" key={item.external_id || i}>
                  <div className="card-header">
                    <span className="card-title">{item.title}</span>
                    <span className="verdict-badge" style={{ background: VERDICT_COLORS[verdict] }}>
                      {VERDICT_LABELS[verdict]}
                    </span>
                  </div>

                  <div className="price">${item.price?.toFixed(2)}</div>

                  <div className="price-row">
                    {recentSold && (
                      <div className="price-box">
                        <div className="price-box-label">Last Sold</div>
                        <div className="price-box-value">${recentSold.toFixed(2)}</div>
                        {recentDate && <div className="price-box-date">{recentDate}</div>}
                      </div>
                    )}
                    {avg && (
                      <div className="price-box">
                        <div className="price-box-label">Avg Sold</div>
                        <div className="price-box-value">${avg}</div>
                        {pct !== undefined && (
                          <div className={pct > 0 ? "pct-up" : "pct-down"}>
                            {pct > 0 ? "+" : ""}{pct}% vs market
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {item.analysis?.summary && (
                    <p className="summary">{item.analysis.summary}</p>
                  )}

                  <div className="card-footer">
                    <span className="source-label">
                      {SOURCE_LABELS[item.source] || item.source?.toUpperCase()} · {item.seller_name || "Unknown"}
                    </span>
                    {hasRealUrl ? (
                      <a className="view-btn" href={item.listing_url} target="_blank" rel="noreferrer">
                        View Listing →
                      </a>
                    ) : (
                      <span className="view-btn disabled">Pending eBay key</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {!loading && results.length === 0 && !error && (
        <div className="empty">
          <div style={{ fontSize: 48, marginBottom: 12 }}>🔍</div>
          <p>Search for any sports card to see listings and price analysis.</p>
        </div>
      )}
    </div>
  );
}
