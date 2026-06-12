import { useEffect, useState } from "react";
import {
  checkShopPassword, askAuctions,
  type Sale, type AuctionSource, type Market, type TrendPoint, type Deal,
} from "./api/client";

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
  market?: Market | null;
  trend?: TrendPoint[];
  deals?: Deal[];
  error?: string;
};

function statusTone(status: string): string {
  if (status === "ok") return "src-ok";
  if (status.startsWith("blocked")) return "src-blocked";
  return "src-none";
}

function money(n: number): string {
  if (Math.abs(n) >= 1000) return "$" + Math.round(n).toLocaleString();
  return "$" + n.toFixed(0);
}

// Compact inline SVG price-history chart (no chart lib).
function TrendChart({ points }: { points: TrendPoint[] }) {
  const W = 600, H = 150, padX = 8, padTop = 12, padBot = 22;
  const pts = points
    .map(p => ({ t: new Date(p.date).getTime(), price: p.price }))
    .filter(p => !isNaN(p.t) && p.price > 0)
    .sort((a, b) => a.t - b.t);
  if (pts.length < 2) return null;

  const tMin = pts[0].t, tMax = pts[pts.length - 1].t;
  const pMin = Math.min(...pts.map(p => p.price));
  const pMax = Math.max(...pts.map(p => p.price));
  const x = (t: number) => padX + (tMax === tMin ? 0.5 : (t - tMin) / (tMax - tMin)) * (W - 2 * padX);
  const y = (p: number) => padTop + (1 - (pMax === pMin ? 0.5 : (p - pMin) / (pMax - pMin))) * (H - padTop - padBot);

  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)} ${y(p.price).toFixed(1)}`).join(" ");
  const area = `${line} L${x(tMax).toFixed(1)} ${H - padBot} L${x(tMin).toFixed(1)} ${H - padBot} Z`;
  const yr = (t: number) => new Date(t).getFullYear();

  return (
    <svg className="trend-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id="trendfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(124,58,237,0.35)" />
          <stop offset="100%" stopColor="rgba(124,58,237,0)" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#trendfill)" />
      <path d={line} fill="none" stroke="#a78bfa" strokeWidth="2" />
      {pts.map((p, i) => <circle key={i} cx={x(p.t)} cy={y(p.price)} r="2.5" fill="#c4b5fd" />)}
      <text x={padX} y={10} className="trend-axis">{money(pMax)}</text>
      <text x={padX} y={H - 6} className="trend-axis">{money(pMin)}</text>
      <text x={W - padX} y={H - 6} className="trend-axis" textAnchor="end">{yr(tMin)}–{yr(tMax)}</text>
    </svg>
  );
}

const SCORE_META: Record<string, { label: string; cls: string }> = {
  great: { label: "🔥 Great deal", cls: "deal-great" },
  good:  { label: "✅ Good deal", cls: "deal-good" },
  fair:  { label: "⚖️ Fair", cls: "deal-fair" },
  high:  { label: "⚠️ Above market", cls: "deal-high" },
};

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
        ? { ...t, answer: res.answer, cardQuery: res.card_query, sales: res.sales, sources: res.sources,
            market: res.market, trend: res.trend, deals: res.deals }
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

                  {/* Market value + trend */}
                  {t.market && (
                    <div className="market-box">
                      <div className="market-head">
                        <div>
                          <div className="market-label">
                            Market value{t.market.grade ? ` · ${t.market.grade}` : ""}
                          </div>
                          <div className="market-median">{money(t.market.median)}</div>
                          <div className="market-sub">
                            {money(t.market.low)}–{money(t.market.high)} · {t.market.count} sale{t.market.count !== 1 ? "s" : ""}
                            {t.market.trend_pct != null && (
                              <span className={`market-trend ${t.market.trend_pct >= 0 ? "up" : "down"}`}>
                                {t.market.trend_pct >= 0 ? "▲" : "▼"} {Math.abs(t.market.trend_pct)}% over time
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      {t.trend && t.trend.length >= 2 && <TrendChart points={t.trend} />}
                    </div>
                  )}

                  {/* Deal Score on current listings */}
                  {t.deals && t.deals.length > 0 && (
                    <div className="deals-box">
                      <div className="deals-label">💸 Deals right now (vs market)</div>
                      {t.deals.map((d, di) => {
                        const m = SCORE_META[d.score] || SCORE_META.fair;
                        return (
                          <a key={di} className="deal-row" href={d.listing_url || "#"} target="_blank" rel="noreferrer">
                            {d.image_url
                              ? <img className="auction-sale-img" src={d.image_url} alt="" />
                              : <div className="auction-sale-img placeholder">🃏</div>}
                            <div className="auction-sale-main">
                              <div className="auction-sale-title">
                                {d.grade ? <span className="auction-grade-badge">{d.grade}</span> : null}
                                {d.title || "Listing"}
                              </div>
                              <div className="auction-sale-meta">eBay · current listing</div>
                            </div>
                            <div className="deal-right">
                              <div className="deal-price">{money(d.price)}</div>
                              <span className={`deal-badge ${m.cls}`}>{m.label} {d.pct > 0 ? "+" : ""}{d.pct}%</span>
                            </div>
                          </a>
                        );
                      })}
                    </div>
                  )}

                  <div className="auction-sources">
                    {t.cardQuery && <span className="auction-cardq">Searched: <strong>{t.cardQuery}</strong></span>}
                    {t.sources?.filter(Boolean).map(s => {
                      let label = s.status;
                      if (s.status === "ok") {
                        if (s.name === "Goldin") {
                          const parts = [];
                          if (s.sold) parts.push(`${s.sold} sold`);
                          if (s.live) parts.push(`${s.live} live`);
                          label = parts.join(" · ") || `${s.count} results`;
                        } else {
                          label = `${s.count} sale${s.count !== 1 ? "s" : ""}`;
                        }
                      }
                      return (
                        <span key={s.name} className={`auction-src-pill ${statusTone(s.status)}`}>
                          {s.name}: {label}
                        </span>
                      );
                    })}
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
                            <div className="auction-sale-title">
                              {s.grade ? <span className="auction-grade-badge">{s.grade}</span> : null}
                              {s.title || "Card"}
                            </div>
                            <div className="auction-sale-meta">
                              {s.auction_house || s.source}
                              {s.status === "live auction" ? " · 🔴 live" : ""}
                              {s.sold_at ? ` · ${s.status === "live auction" ? "ends " : ""}${s.sold_at}` : ""}
                              {s.bids != null ? ` · ${s.bids} bids` : ""}
                              {s.pop_10 != null ? ` · PSA 10 pop ${s.pop_10.toLocaleString()}` : ""}
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
