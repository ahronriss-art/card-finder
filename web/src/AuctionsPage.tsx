import { useEffect, useState } from "react";
import { checkShopPassword, askAuctions, type Sale, type AuctionSource } from "./api/client";

const EXAMPLES = [
  "What did a 2003 Topps Chrome LeBron James PSA 10 last sell for?",
  "Recent sales of a Charizard Base Set PSA 9?",
  "How much is a 1986 Fleer Jordan rookie PSA 8 worth?",
  "Latest prices on a Luka Doncic Prizm Silver rookie?",
];

type Turn = {
  question: string;
  answer?: string;
  cardQuery?: string;
  sales?: Sale[];
  sources?: AuctionSource[];
  error?: string;
};

function statusTone(status: string): string {
  if (status === "ok") return "src-ok";
  if (status.startsWith("blocked")) return "src-blocked";
  return "src-none";
}

export default function AuctionsPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);
  const [pw, setPw] = useState("");
  const [pwError, setPwError] = useState("");

  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);

  // Same gate as the Shops tab — one password unlocks both.
  useEffect(() => {
    const stored = localStorage.getItem("shopsPassword");
    const url = new URL(window.location.href);
    const key = url.searchParams.get("key");
    const candidate = key || stored;
    if (key) { url.searchParams.delete("key"); window.history.replaceState({}, "", url.toString()); }
    if (!candidate) { setChecking(false); return; }
    localStorage.setItem("shopsPassword", candidate);
    setUnlocked(true);
    setChecking(false);
    checkShopPassword(candidate).catch((err) => {
      if (err?.response?.status === 401) {
        localStorage.removeItem("shopsPassword");
        setUnlocked(false);
      }
    });
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

  async function ask(q: string) {
    const text = q.trim();
    if (!text || loading) return;
    setQuestion("");
    const idx = turns.length;
    setTurns(prev => [...prev, { question: text }]);
    setLoading(true);
    try {
      const res = await askAuctions(text);
      setTurns(prev => prev.map((t, i) => i === idx
        ? { ...t, answer: res.answer, cardQuery: res.card_query, sales: res.sales, sources: res.sources }
        : t));
    } catch (err: any) {
      const msg = err?.response?.status === 401
        ? "Session expired — refresh and re-enter the password."
        : "Couldn't reach the data sources. Try again in a moment.";
      setTurns(prev => prev.map((t, i) => i === idx ? { ...t, error: msg } : t));
    } finally {
      setLoading(false);
    }
  }

  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;

  if (!unlocked) {
    return (
      <div className="app" style={{ paddingTop: 60, maxWidth: 440 }}>
        <h1>🔒 Auctions</h1>
        <p className="subtitle">This tool is private. Enter the password to continue.</p>
        <form onSubmit={submitPw} style={{ marginTop: 24 }}>
          <div className="form-group">
            <input type="password" placeholder="Password" value={pw} onChange={e => setPw(e.target.value)} autoFocus />
          </div>
          {pwError && <div className="error-msg">{pwError}</div>}
          <button className="btn" type="submit" style={{ width: "100%", marginTop: 8 }}>Unlock →</button>
        </form>
      </div>
    );
  }

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60 }}>
      <h1>Auctions</h1>
      <p className="subtitle">
        Ask about any card's value — recent sales and what's up for auction now. We pull
        eBay sold listings and live Goldin auction lots (plus PSA when reachable), then
        answer from the real data.
      </p>

      {/* Ask box */}
      <form onSubmit={e => { e.preventDefault(); ask(question); }} className="auction-ask-form">
        <input
          className="auction-ask-input"
          type="text"
          placeholder="e.g. What did a 2003 Topps Chrome LeBron PSA 10 last sell for?"
          value={question}
          onChange={e => setQuestion(e.target.value)}
        />
        <button className="btn btn-sm" type="submit" disabled={loading || !question.trim()}>
          {loading ? "Searching…" : "Ask"}
        </button>
      </form>

      {turns.length === 0 && (
        <div className="auction-examples">
          <div className="auction-examples-label">Try asking</div>
          {EXAMPLES.map(ex => (
            <button key={ex} type="button" className="auction-example-chip" onClick={() => ask(ex)} disabled={loading}>
              {ex}
            </button>
          ))}
        </div>
      )}

      {/* Conversation (newest first) */}
      <div style={{ marginTop: 24 }}>
        {[...turns].reverse().map((t, ri) => {
          const i = turns.length - 1 - ri;
          const pending = loading && i === turns.length - 1 && !t.answer && !t.error;
          return (
            <div className="auction-turn" key={i}>
              <div className="auction-question">🔎 {t.question}</div>

              {pending && <div className="auction-pending">Pulling sales data…</div>}
              {t.error && <div className="error-msg" style={{ marginTop: 8 }}>{t.error}</div>}

              {t.answer && (
                <>
                  <div className="auction-answer">{t.answer}</div>

                  <div className="auction-sources">
                    {t.cardQuery && <span className="auction-cardq">Searched: <strong>{t.cardQuery}</strong></span>}
                    {t.sources?.filter(Boolean).map(s => (
                      <span key={s.name} className={`auction-src-pill ${statusTone(s.status)}`}>
                        {s.name}: {s.status === "ok" ? `${s.count} ${s.name === "Goldin" ? "live lot" : "result"}${s.count !== 1 ? "s" : ""}` : s.status}
                      </span>
                    ))}
                  </div>

                  {t.sales && t.sales.length > 0 && (
                    <div className="auction-sales">
                      {t.sales.map((s, si) => (
                        <a
                          key={si}
                          className="auction-sale-row"
                          href={s.listing_url || "#"}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {s.image_url
                            ? <img className="auction-sale-img" src={s.image_url} alt="" />
                            : <div className="auction-sale-img placeholder">🃏</div>}
                          <div className="auction-sale-main">
                            <div className="auction-sale-title">{s.title || "Card"}</div>
                            <div className="auction-sale-meta">
                              {s.auction_house || s.source}
                              {s.status === "live auction" ? " · 🔴 live" : ""}
                              {s.sold_at ? ` · ${s.status === "live auction" ? "ends " : ""}${s.sold_at}` : ""}
                              {s.bids != null ? ` · ${s.bids} bids` : ""}
                            </div>
                          </div>
                          <div className="auction-sale-price">
                            {s.sold_price != null ? `$${s.sold_price.toLocaleString()}` : "—"}
                            {s.status === "live auction" && <div className="auction-sale-sub">current bid</div>}
                          </div>
                        </a>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
