import { useState, useEffect } from "react";
import PopLinks from "./PopLinks";
import { createPopWatch, getPopWatches, deletePopWatch, popLookup, type PopWatch, type PopLookup } from "./api/client";

// Standalone population-report lookup + Pop Watch. The links cross-reference a
// card's graded population by hand; the Pop Watch tracks a specific PSA cert and
// alerts you when its population increases (another copy of that card+grade gets
// graded) — handy for a 'pop 1' card while it's in a live auction.
export default function PopReportsPage() {
  const [query, setQuery] = useState("");
  const [card, setCard] = useState("");
  const [pop, setPop] = useState<PopLookup | null>(null);
  const [popLoading, setPopLoading] = useState(false);
  const [popErr, setPopErr] = useState("");

  // Pop Watch state
  const userId = Number(localStorage.getItem("userId")) || null;
  const [watches, setWatches] = useState<PopWatch[]>([]);
  const [cert, setCert] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (userId) getPopWatches(userId).then(setWatches).catch(() => {});
  }, [userId]);

  const isCert = (s: string) => /^\d{6,9}$/.test(s.trim());

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    setPopErr("");
    if (isCert(q)) {
      // A PSA cert number → fetch the real population from PSA.
      setCard("");
      setPopLoading(true);
      setPop(null);
      try {
        setPop(await popLookup(q));
      } catch (err: any) {
        setPopErr(err?.response?.data?.detail || "Couldn't look up that cert number.");
      } finally {
        setPopLoading(false);
      }
    } else {
      // A card name → no free name→pop source, show cross-reference links.
      setPop(null);
      setCard(q);
    }
  }

  async function watchThisCert(certNumber: string) {
    if (!userId) return;
    try {
      const w = await createPopWatch({ userId, certNumber });
      setWatches(prev => [w, ...prev.filter(x => x.id !== w.id)]);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "Couldn't create the pop watch.");
    }
  }

  async function addWatch(e?: React.FormEvent) {
    e?.preventDefault();
    if (!userId || !cert.trim()) return;
    setAdding(true);
    setErr("");
    try {
      const w = await createPopWatch({
        userId, certNumber: cert.trim(),
        auctionEndsAt: endsAt || undefined,
      });
      setWatches(prev => [w, ...prev]);
      setCert("");
      setEndsAt("");
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "Couldn't create the pop watch. Check the cert number.");
    } finally {
      setAdding(false);
    }
  }

  async function removeWatch(id: number) {
    await deletePopWatch(id).catch(() => {});
    setWatches(prev => prev.filter(w => w.id !== id));
  }

  return (
    <div className="app" style={{ paddingTop: 32, paddingBottom: 48 }}>
      <h1>Pop Reports</h1>
      <p className="subtitle">
        Enter a <strong>PSA cert number</strong> to see the live PSA population, or a
        card name to cross-reference its pop on PSA, GemRate, SGC and CGC.
      </p>

      <form onSubmit={submit}>
        <div className="search-bar">
          <input
            type="text"
            placeholder="PSA cert number (e.g. 84012345) or card name..."
            value={query}
            onChange={e => setQuery(e.target.value)}
          />
          <button className="btn" type="submit" disabled={!query.trim() || popLoading}>
            {popLoading ? "Looking up..." : "Look up"}
          </button>
        </div>
      </form>

      {popErr && <div className="error-msg" style={{ marginTop: 16 }}>{popErr}</div>}

      {pop ? (
        <div className="card poplookup" style={{ marginTop: 24, maxWidth: 560 }}>
          <span className="card-title" style={{ display: "block", marginBottom: 4 }}>
            {pop.label || `PSA cert ${pop.cert}`}
          </span>
          <div className="poplookup-grade">{pop.grade || "Graded"}</div>
          <div className="poplookup-stats">
            <div className="poplookup-stat hl">
              <div className="poplookup-num">{pop.population ?? "—"}</div>
              <div className="poplookup-lbl">Pop at this grade</div>
            </div>
            <div className="poplookup-stat">
              <div className="poplookup-num">{pop.population_higher ?? "—"}</div>
              <div className="poplookup-lbl">Graded higher</div>
            </div>
            <div className="poplookup-stat">
              <div className="poplookup-num">{pop.total_population ?? "—"}</div>
              <div className="poplookup-lbl">Total graded</div>
            </div>
          </div>
          <div className="poplookup-actions">
            <a href={pop.url} target="_blank" rel="noreferrer" className="seller-link">View PSA cert →</a>
            {userId
              ? <button className="btn btn-sm" onClick={() => watchThisCert(pop.cert)}>📈 Watch this pop</button>
              : <span className="poplookup-hint">Sign in on the Alerts tab to watch this pop</span>}
          </div>
          <p className="summary" style={{ marginTop: 12 }}>
            Live from PSA. "Pop at this grade" is how many of this exact card PSA has graded at {pop.grade || "this grade"}.
          </p>
        </div>
      ) : card ? (
        <div className="card" style={{ marginTop: 24, maxWidth: 560 }}>
          <span className="card-title" style={{ display: "block", marginBottom: 12 }}>{card}</span>
          <PopLinks card={card} />
          <p className="summary" style={{ marginTop: 4 }}>
            No free data source returns pop numbers from a card-name search, so these
            open a scoped web search that lands on each grader's population report.
            For live numbers, search by a <strong>PSA cert number</strong>.
          </p>
        </div>
      ) : (
        <div className="empty">
          <div style={{ fontSize: 48, marginBottom: 12 }}>📊</div>
          <p>Enter a PSA cert number for live population, or a card name for pop-report links.</p>
        </div>
      )}

      {/* ---- Pop Watch ---- */}
      <div className="popwatch">
        <h2 className="popwatch-h">📈 Pop Watch</h2>
        <p className="popwatch-sub">
          Track a specific PSA cert and get an email/text the moment its population
          ticks up — e.g. you're bidding on a <strong>pop 1</strong> and want to know
          if a second copy gets graded before the auction ends.
        </p>

        {!userId ? (
          <div className="popwatch-note">
            Set up your email/phone in the <strong>Alerts</strong> tab first, then come
            back here to add a pop watch.
          </div>
        ) : (
          <>
            <form onSubmit={addWatch} className="popwatch-form">
              <input
                type="text"
                placeholder="PSA cert number (on the slab label, e.g. 84012345)"
                value={cert}
                onChange={e => setCert(e.target.value)}
              />
              <label className="popwatch-ends">
                <span>Auction ends (optional)</span>
                <input type="datetime-local" value={endsAt} onChange={e => setEndsAt(e.target.value)} />
              </label>
              <button className="btn" type="submit" disabled={adding || !cert.trim()}>
                {adding ? "Adding..." : "Watch pop"}
              </button>
            </form>
            <p className="popwatch-hint">
              Find the cert number printed on the PSA slab label, or in the cert URL
              (psacard.com/cert/<em>NUMBER</em>).
            </p>
            {err && <div className="error-msg" style={{ marginTop: 8 }}>{err}</div>}

            {watches.length > 0 && (
              <div className="popwatch-list">
                {watches.map(w => (
                  <div className="popwatch-item" key={w.id}>
                    <div className="popwatch-item-main">
                      <div className="popwatch-item-label">{w.label || `PSA cert ${w.cert_number}`}</div>
                      <div className="popwatch-item-meta">
                        Pop now: <strong>{w.population ?? "—"}</strong>
                        {w.population_higher != null && <> · {w.population_higher} graded higher</>}
                        {w.auction_ends_at && <> · watching until {new Date(w.auction_ends_at).toLocaleString()}</>}
                      </div>
                    </div>
                    <div className="popwatch-item-actions">
                      <a href={w.cert_url} target="_blank" rel="noreferrer" className="seller-link">PSA cert</a>
                      <button className="clear-btn" onClick={() => removeWatch(w.id)}>Remove</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
