// Compact sold-price history chart for a card, drawn as inline SVG (no deps).
// Fed the query-level eBay sold comps from /search. eBay's Browse API often
// returns sold comps without reliable dates, so when dates are missing we fall
// back to plotting the comps in returned order (most-recent-first → left→right
// oldest→newest). The current listing's price is drawn as a dashed reference
// line so the same comp set reads differently per card.
type Sold = { sold_price?: number; sold_at?: string | null; title?: string | null };

const W = 300;
const H = 90;
const PAD = { top: 10, right: 8, bottom: 4, left: 8 };

export default function SoldChart({ sold, price }: { sold?: Sold[]; price?: number | null }) {
  const pts = (sold || [])
    .map(s => ({ v: Number(s.sold_price) || 0, at: s.sold_at || "", title: s.title || "" }))
    .filter(p => p.v > 0);

  if (pts.length < 2) return null;

  // Order oldest → newest when dates are usable; otherwise reverse the API order
  // (it returns newest first) so the chart reads left=old, right=new.
  const hasDates = pts.every(p => p.at && !isNaN(Date.parse(p.at)));
  const ordered = hasDates
    ? [...pts].sort((a, b) => Date.parse(a.at) - Date.parse(b.at))
    : [...pts].reverse();

  const series = ordered.slice(-16); // cap points
  const vals = series.map(p => p.v);
  const lo = Math.min(...vals, price && price > 0 ? price : Infinity);
  const hi = Math.max(...vals, price && price > 0 ? price : -Infinity);
  const span = hi - lo || 1;

  const ix = W - PAD.left - PAD.right;
  const iy = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (series.length === 1 ? ix / 2 : (i / (series.length - 1)) * ix);
  const y = (v: number) => PAD.top + iy - ((v - lo) / span) * iy;

  const line = series.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(series.length - 1).toFixed(1)},${(H - PAD.bottom).toFixed(1)} L${x(0).toFixed(1)},${(H - PAD.bottom).toFixed(1)} Z`;

  const fmt = (n: number) => (n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${Math.round(n)}`);
  const priceY = price && price > 0 ? y(price) : null;
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;

  return (
    <div className="sold-chart">
      <div className="sold-chart-head">
        <span className="sold-chart-title">📈 Sold comps</span>
        <span className="sold-chart-meta">{series.length} sales · avg {fmt(avg)}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="sold-chart-svg" role="img"
        aria-label={`Sold price history: ${series.length} recent sales, average ${fmt(avg)}`}>
        <defs>
          <linearGradient id="soldFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(249,115,22,0.35)" />
            <stop offset="100%" stopColor="rgba(249,115,22,0)" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#soldFill)" />
        <path d={line} fill="none" stroke="#f97316" strokeWidth={2}
          strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
        {series.map((p, i) => (
          <circle key={i} cx={x(i)} cy={y(p.v)} r={2.2} fill="#f97316">
            <title>{`${fmt(p.v)}${p.at && !isNaN(Date.parse(p.at)) ? " · " + new Date(p.at).toLocaleDateString() : ""}`}</title>
          </circle>
        ))}
        {priceY !== null && (
          <line x1={PAD.left} y1={priceY} x2={W - PAD.right} y2={priceY}
            stroke="#fff" strokeWidth={1} strokeDasharray="4 3" opacity={0.55}
            vectorEffect="non-scaling-stroke" />
        )}
      </svg>
      <div className="sold-chart-axis">
        <span>{fmt(lo)}</span>
        {priceY !== null && <span className="sold-chart-this">this: {fmt(price as number)}</span>}
        <span>{fmt(hi)}</span>
      </div>
    </div>
  );
}
