import { useState } from "react";
import PopLinks from "./PopLinks";

// Standalone population-report lookup. Type any card and get one-click links
// into each grading company's pop report (via scoped Google search), without
// having to run an eBay search first.
export default function PopReportsPage() {
  const [query, setQuery] = useState("");
  const [card, setCard] = useState("");

  function submit(e?: React.FormEvent) {
    e?.preventDefault();
    setCard(query.trim());
  }

  return (
    <div className="app" style={{ paddingTop: 32, paddingBottom: 48 }}>
      <h1>Pop Reports</h1>
      <p className="subtitle">
        Cross-reference a card's graded population on PSA, GemRate, SGC and CGC.
      </p>

      <form onSubmit={submit}>
        <div className="search-bar">
          <input
            type="text"
            placeholder="Card to look up... (e.g. 2003 Topps Chrome LeBron James #111)"
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <button className="btn" type="submit" disabled={!query.trim()}>
            Look up
          </button>
        </div>
      </form>

      {card ? (
        <div className="card" style={{ marginTop: 24, maxWidth: 560 }}>
          <span className="card-title" style={{ display: "block", marginBottom: 12 }}>{card}</span>
          <PopLinks card={card} />
          <p className="summary" style={{ marginTop: 4 }}>
            These open a scoped web search that lands on each grader's population
            report — the pop sites are bot-protected and don't expose clean
            search URLs, so this works from your browser.
          </p>
        </div>
      ) : (
        <div className="empty">
          <div style={{ fontSize: 48, marginBottom: 12 }}>📊</div>
          <p>Enter a card to pull up its population reports across grading companies.</p>
        </div>
      )}
    </div>
  );
}
