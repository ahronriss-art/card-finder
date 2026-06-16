import { useState } from "react";
import { searchCards, searchMisspellings } from "./api/client";
import PopLinks from "./PopLinks";

const SPORTS = ["All", "NBA", "NFL", "MLB", "NHL", "Pokemon", "UFC", "Soccer"];

const COMPANIES: Record<string, string[]> = {
  All:     ["Topps", "Panini", "Upper Deck", "Bowman", "Fleer", "Donruss", "Score", "SkyBox"],
  NBA:     ["Panini", "Topps", "Upper Deck", "Fleer", "SkyBox", "Hoops", "Stadium Club"],
  NFL:     ["Panini", "Topps", "Upper Deck", "Donruss", "Fleer", "Score", "Playoff"],
  MLB:     ["Topps", "Panini", "Upper Deck", "Bowman", "Fleer", "Donruss", "Score"],
  NHL:     ["Upper Deck", "Topps", "O-Pee-Chee", "Parkhurst", "Fleer"],
  Pokemon: ["Pokemon Company", "Wizards of the Coast"],
  UFC:     ["Panini", "Topps", "Upper Deck"],
  Soccer:  ["Panini", "Topps", "Upper Deck", "Futera"],
};

const CARD_LINES: Record<string, string[]> = {
  Topps:          ["Topps Chrome", "Topps Gold", "Topps Finest", "Stadium Club", "Topps Heritage", "Allen & Ginter", "Topps Now", "Topps Update"],
  Panini:         ["Prizm", "Select", "Mosaic", "Optic", "Donruss", "Hoops", "Kaboom", "Flawless", "National Treasures", "Immaculate", "Crown Royale", "Contenders", "Absolute"],
  "Upper Deck":   ["SP Authentic", "SPx", "Exquisite", "Young Guns", "Black Diamond", "UD Series 1", "UD Series 2"],
  Bowman:         ["Bowman Chrome", "Bowman Draft", "Bowman Platinum", "Bowman Sterling", "Bowman's Best"],
  Fleer:          ["Fleer Ultra", "Fleer Metal", "Fleer Showcase", "Fleer Tradition"],
  Donruss:        ["Donruss Optic", "Donruss Elite", "Donruss Rated Rookie"],
  Score:          ["Score Select", "Score Traded"],
  SkyBox:         ["SkyBox Premium", "SkyBox Metal"],
  Hoops:          ["NBA Hoops", "Hoops Premium"],
  "Stadium Club": ["Stadium Club Chrome"],
  Playoff:        ["Playoff Contenders", "Playoff Prestige"],
  "O-Pee-Chee":  ["OPC Platinum", "O-Pee-Chee Premier"],
  "Pokemon Company": ["Base Set", "Jungle", "Fossil", "Team Rocket", "Neo", "Legendary Collection", "EX Series", "Diamond & Pearl", "Black & White", "XY", "Sun & Moon", "Sword & Shield", "Scarlet & Violet"],
  "Wizards of the Coast": ["Base Set", "Jungle", "Fossil", "Team Rocket", "Gym Heroes", "Neo Genesis"],
};

const INSERT_TYPES = [
  "Refractor", "Gold Refractor", "Color Refractor", "Prizm",
  "Auto", "Autograph", "RPA", "Patch", "Jersey",
  "Holo", "Parallel", "Short Print", "SSP", "1st Edition",
  "Rookie", "Variation", "Superfractor",
];

const GRADES = [
  "PSA 10", "PSA 9", "PSA 8", "PSA 7", "PSA 6", "PSA 5",
  "BGS 9.5", "BGS 9", "BGS 8.5",
  "SGC 10", "SGC 9",
  "Raw / Ungraded",
];

const VERDICT_COLORS: Record<string, string> = {
  great_deal: "#16a34a", good_deal: "#65a30d",
  fair: "#ca8a04", overpriced: "#dc2626", unknown: "#6b7280",
  suspicious: "#ea580c",
};
const VERDICT_LABELS: Record<string, string> = {
  great_deal: "GREAT DEAL", good_deal: "Good Deal",
  fair: "Fair Price", overpriced: "Overpriced", unknown: "No Data",
  suspicious: "⚠️ Verify",
};

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [sport, setSport] = useState("All");
  const [company, setCompany] = useState("");
  const [cardLine, setCardLine] = useState("");
  const [insertType, setInsertType] = useState("");
  const [grade, setGrade] = useState("");
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [findMisspellings, setFindMisspellings] = useState(false);
  const [misspellingsTried, setMisspellingsTried] = useState<string[]>([]);
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function handleSportChange(s: string) {
    setSport(s);
    setCompany("");
    setCardLine("");
  }

  function handleCompanyChange(c: string) {
    setCompany(c);
    setCardLine("");
  }

  function buildFullQuery() {
    const parts = [query.trim()];
    if (company) parts.push(company);
    if (cardLine) parts.push(cardLine);
    if (insertType) parts.push(insertType);
    if (grade) parts.push(grade);
    return parts.filter(Boolean).join(" ");
  }

  async function handleSearch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    setMisspellingsTried([]);
    try {
      const fullQuery = buildFullQuery();
      const sportParam = sport === "All" ? undefined : sport;

      const minP = minPrice ? parseFloat(minPrice) : undefined;
      const maxP = maxPrice ? parseFloat(maxPrice) : undefined;

      if (findMisspellings) {
        const data = await searchMisspellings(fullQuery, sportParam);
        setResults(data.listings || []);
        setMisspellingsTried(data.misspellings_tried || []);
        if ((data.listings || []).length === 0) setError("No misspelled listings found. The seller spelled it correctly!");
      } else {
        const data = await searchCards(fullQuery, sportParam, minP, maxP);
        setResults(data.listings || []);
        if ((data.listings || []).length === 0) setError("No listings found. Try adjusting your filters.");
      }
    } catch {
      setError("Search failed. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  }

  const activeFilterCount = [company, cardLine, insertType, grade].filter(Boolean).length;
  const availableLines = company ? (CARD_LINES[company] || []) : [];

  return (
    <div className="app" style={{ paddingTop: 32, paddingBottom: 48 }}>
      <h1>Card Finder</h1>
      <p className="subtitle">Search sports cards on eBay — with live price analysis and sold history.</p>

      <form onSubmit={handleSearch}>
        <div className="search-bar">
          <input
            type="text"
            placeholder="Player name, year, card number... (e.g. LeBron James 2003)"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <button className="btn" type="submit" disabled={loading}>
            {loading ? "Searching..." : "Search"}
          </button>
        </div>
      </form>

      {/* Sport filter */}
      <div className="sports-row">
        {SPORTS.map(s => (
          <button key={s} className={`chip${sport === s ? " active" : ""}`} onClick={() => handleSportChange(s)}>
            {s}
          </button>
        ))}
      </div>

      {/* Advanced filters toggle */}
      <button className="filter-toggle" onClick={() => setShowFilters(v => !v)}>
        <span>Advanced Filters</span>
        {activeFilterCount > 0 && <span className="filter-count">{activeFilterCount}</span>}
        <span style={{ marginLeft: "auto" }}>{showFilters ? "▲" : "▼"}</span>
      </button>

      {showFilters && (
        <div className="filters-panel">
          {/* Company */}
          <div className="filter-section">
            <div className="filter-label">Card Company</div>
            <div className="filter-chips">
              {COMPANIES[sport].map(c => (
                <button key={c} className={`chip${company === c ? " active" : ""}`}
                  onClick={() => handleCompanyChange(company === c ? "" : c)}>
                  {c}
                </button>
              ))}
            </div>
          </div>

          {/* Card Line (only shows when company is selected) */}
          {company && availableLines.length > 0 && (
            <div className="filter-section">
              <div className="filter-label">Card Line / Series</div>
              <div className="filter-chips">
                {availableLines.map(l => (
                  <button key={l} className={`chip${cardLine === l ? " active" : ""}`}
                    onClick={() => setCardLine(cardLine === l ? "" : l)}>
                    {l}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Insert Type */}
          <div className="filter-section">
            <div className="filter-label">Insert / Parallel Type</div>
            <div className="filter-chips">
              {INSERT_TYPES.map(t => (
                <button key={t} className={`chip${insertType === t ? " active" : ""}`}
                  onClick={() => setInsertType(insertType === t ? "" : t)}>
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Grade */}
          <div className="filter-section">
            <div className="filter-label">Grade</div>
            <div className="filter-chips">
              {GRADES.map(g => (
                <button key={g} className={`chip${grade === g ? " active" : ""}`}
                  onClick={() => setGrade(grade === g ? "" : g)}>
                  {g}
                </button>
              ))}
            </div>
          </div>

          {/* Price Range */}
          <div className="filter-section">
            <div className="filter-label">Price Range</div>
            <div className="price-range-row">
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
          </div>

          {/* Active filter summary + clear */}
          {(activeFilterCount > 0 || minPrice || maxPrice) && (
            <div className="filter-summary">
              <span>
                Searching: <strong>{buildFullQuery() || query}</strong>
                {(minPrice || maxPrice) && <strong> · ${minPrice || "0"}–${maxPrice || "∞"}</strong>}
              </span>
              <button className="clear-btn" onClick={() => { setCompany(""); setCardLine(""); setInsertType(""); setGrade(""); setMinPrice(""); setMaxPrice(""); }}>
                Clear filters
              </button>
            </div>
          )}
        </div>
      )}

      {/* Misspelling toggle */}
      <div className="misspelling-toggle" onClick={() => setFindMisspellings(v => !v)}>
        <div className={`toggle-switch${findMisspellings ? " on" : ""}`} />
        <div>
          <div className="toggle-label">Find Misspelled Listings</div>
          <div className="toggle-sub">AI searches for typos sellers make — fewer buyers find these, so prices are often lower</div>
        </div>
      </div>

      {misspellingsTried.length > 0 && (
        <div className="misspellings-tried">
          Searched for: {misspellingsTried.map(m => <span key={m} className="misspelling-tag">{m}</span>)}
        </div>
      )}

      {error && <div className="error-msg" style={{ marginTop: 16 }}>{error}</div>}

      {loading && (
        <div className="loading">
          <div className="spinner" />
          Searching listings...
        </div>
      )}

      {!loading && results.length > 0 && (
        <>
          <p className="results-count" style={{ marginTop: 20 }}>{results.length} listings found on eBay</p>
          <div className="cards-grid">
            {results.map((item, i) => {
              const verdict = item.analysis?.verdict || "unknown";
              const avg = item.analysis?.avg_sold_price;
              const recentSold = item.analysis?.most_recent_sold;
              const recentDate = item.analysis?.most_recent_date;
              const pct = item.analysis?.pct_vs_market;
              const hasRealUrl = item.listing_url && item.listing_url !== "https://ebay.com";

              const sellerProfileUrl = item.seller_name
                ? `https://www.ebay.com/usr/${item.seller_name}`
                : null;
              const contactSellerUrl = hasRealUrl
                ? `https://contact.ebay.com/ws/eBayISAPI.dll?ContactSeller&item=${item.external_id}`
                : null;

              return (
                <div className="card" key={item.external_id || i}>
                  {/* Card Image */}
                  <div className="card-image-wrap">
                    {item.image_url ? (
                      <img src={item.image_url} alt={item.title} className="card-image" />
                    ) : (
                      <div className="card-image-placeholder">🃏</div>
                    )}
                    <div className="card-badges">
                      {item.misspelled && (
                        <span className="verdict-badge" style={{ background: "linear-gradient(135deg,#7c3aed,#db2777)" }}>
                          MISSPELLED
                        </span>
                      )}
                      <span className="verdict-badge" style={{ background: VERDICT_COLORS[verdict] }}>
                        {VERDICT_LABELS[verdict]}
                      </span>
                    </div>
                  </div>

                  {item.misspelling_used && (
                    <div className="misspelling-note">Found via: "{item.misspelling_used}"</div>
                  )}

                  <span className="card-title" style={{ display: "block", marginBottom: 8 }}>{item.title}</span>

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
                        <div className="price-box-label">Market</div>
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

                  <PopLinks card={item.title} />

                  {/* Seller info */}
                  {item.seller_name && (
                    <div className="seller-info">
                      <div className="seller-label">Seller</div>
                      <div className="seller-row">
                        <span className="seller-name">@{item.seller_name}</span>
                        <div className="seller-links">
                          {sellerProfileUrl && (
                            <a href={sellerProfileUrl} target="_blank" rel="noreferrer" className="seller-link">
                              View Profile
                            </a>
                          )}
                          {contactSellerUrl && (
                            <a href={contactSellerUrl} target="_blank" rel="noreferrer" className="seller-link contact">
                              Contact Seller
                            </a>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  <div className="card-footer">
                    <span className="source-label">eBay</span>
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
