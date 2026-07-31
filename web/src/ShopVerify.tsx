// "Is this shop still open?" UI, shared by the Shops, TCG Shops, and New Shops
// lists. The backend checks Google Places first and falls back to an AI web
// search; a confirmed closure also marks the shop not-active, so the badge is
// how you see *why* a shop went inactive.
import { useState } from "react";
import {
  verifyShop, verifyMasterShop, verifyBatchShops, verifyBatchMasterShops,
  getVerifyReport, type Shop, type MasterShop, type VerifyReport, type VerifyReportRow,
} from "./api/client";

export type VerifyKind = "card" | "master";

type Tone = { color: string; bg: string };

const TONES: Record<string, Tone> = {
  open: { color: "#34d399", bg: "rgba(52,211,153,0.18)" },
  closed: { color: "#f87171", bg: "rgba(248,113,113,0.18)" },
  warn: { color: "#fbbf24", bg: "rgba(251,191,36,0.18)" },
  unknown: { color: "#9ca3af", bg: "rgba(255,255,255,0.07)" },
};

function tone(status: string): Tone {
  if (status.startsWith("Verified")) return TONES.open;
  if (status.startsWith("Confirmed Closed")) return TONES.closed;
  if (status.startsWith("Temporarily Closed")) return TONES.warn;
  return TONES.unknown;   // "Not found (…)" / "Uncertain match (…)" — needs a human
}

/** Short badge showing the last closure-check result. Renders nothing if unchecked. */
export function VerifyBadge({ status, checkedAt }: { status?: string | null; checkedAt?: string | null }) {
  if (!status) return null;
  const t = tone(status);
  return (
    <span
      title={checkedAt ? `Last checked ${checkedAt}` : undefined}
      style={{
        fontSize: 11, marginLeft: 8, padding: "2px 7px", borderRadius: 6,
        background: t.bg, color: t.color, verticalAlign: "middle", whiteSpace: "nowrap",
      }}
    >
      {status}
    </span>
  );
}

/** "Sells sports cards?" badge — only shown when the answer is no or unknown, since
 *  a yes is the expected case and would just be noise on every row. */
export function SportsBadge({ sells, products }: { sells?: string | null; products?: string | null }) {
  if (sells !== "no" && sells !== "unknown") return null;
  const t = sells === "no" ? TONES.closed : TONES.unknown;
  return (
    <span title={products || undefined}
      style={{ fontSize: 11, marginLeft: 8, padding: "2px 7px", borderRadius: 6,
               background: t.bg, color: t.color, verticalAlign: "middle", whiteSpace: "nowrap" }}>
      {sells === "no" ? "No sports cards" : "Sports cards?"}
    </span>
  );
}

/** Button that re-checks one shop and hands the updated row back to the caller. */
export function VerifyButton({ id, kind, onUpdated }: {
  id: number; kind: VerifyKind; onUpdated: (shop: any) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function run(e: React.MouseEvent) {
    e.stopPropagation();
    setBusy(true);
    setErr("");
    try {
      const res = kind === "master" ? await verifyMasterShop(id) : await verifyShop(id);
      onUpdated(res.shop as Shop | MasterShop);
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "Check failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button className="btn btn-sm" onClick={run} disabled={busy}
      style={{ background: "rgba(255,255,255,0.1)", fontSize: 11 }}
      title={err || "Check whether this shop is still open"}>
      {busy ? "Checking…" : err ? "⚠ Retry check" : "Still open?"}
    </button>
  );
}

/** Toolbar button that works through a whole list a batch at a time. */
export function VerifyListButton({ kind, list, onDone }: {
  kind: VerifyKind; list?: string; onDone?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function run() {
    if (busy) return;
    setBusy(true);
    setMsg("Checking…");
    try {
      let checked = 0;
      let closed = 0;
      // One batch per call so a sleeping backend can't time the whole list out;
      // keep going until nothing is left stale, capped so a huge list can't run away.
      for (let i = 0; i < 20; i++) {
        const r = kind === "master"
          ? await verifyBatchMasterShops(40)
          : await verifyBatchShops(list || "main", 40);
        checked += r.checked;
        closed += r.counts?.closed || 0;
        setMsg(`Checked ${checked}${r.remaining ? `, ${r.remaining} to go…` : ""}`);
        if (!r.remaining || !r.checked) break;
      }
      setMsg(`Checked ${checked} · ${closed} closed`);
      onDone?.();
    } catch (e: any) {
      setMsg(e?.response?.data?.detail || "Check failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button className="btn btn-sm" onClick={run} disabled={busy}
        title="Check every unchecked or out-of-date shop on this list">
        {busy ? "Checking…" : "Check still open"}
      </button>
      {msg && <span style={{ fontSize: 12, opacity: 0.7 }}>{msg}</span>}
    </>
  );
}

function ReportTable({ rows }: { rows: VerifyReportRow[] }) {
  const LISTS: Record<string, string> = { main: "Shops", tcg: "TCG", new: "New Shops" };
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <tbody>
          {rows.map(r => (
            <tr key={`${r.list}-${r.id}`} style={{ borderTop: "1px solid rgba(255,255,255,0.08)" }}>
              <td style={{ padding: "6px 8px", fontWeight: 600 }}>
                {r.maps_url ? <a href={r.maps_url} target="_blank" rel="noreferrer">{r.name}</a> : r.name}
              </td>
              <td style={{ padding: "6px 8px", opacity: 0.75, whiteSpace: "nowrap" }}>
                {[r.city, r.state].filter(Boolean).join(", ")}
              </td>
              <td style={{ padding: "6px 8px", opacity: 0.6, whiteSpace: "nowrap" }}>{LISTS[r.list] || r.list}</td>
              <td style={{ padding: "6px 8px", opacity: 0.75 }}>{r.products || r.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The "which shops are closed or don't sell sports cards" list, across all three lists. */
export function VerifyReportPanel() {
  const [open, setOpen] = useState(false);
  const [rep, setRep] = useState<VerifyReport | null>(null);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    try { setRep(await getVerifyReport()); }
    catch (e: any) { setErr(e?.response?.data?.detail || "Could not load the report"); }
  }

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !rep) load();
  }

  const SECTIONS: [string, VerifyReportRow[] | undefined][] = [
    ["Confirmed closed", rep?.closed],
    ["Open, but no sports cards", rep?.no_sports_cards],
    ["Couldn’t tell — needs a human", rep?.needs_human],
  ];

  return (
    <div style={{ marginTop: 12 }}>
      <button className="btn btn-sm" onClick={toggle}>
        {open ? "Hide problem shops" : "Problem shops"}
      </button>
      {open && (
        <div className="card" style={{ marginTop: 10, padding: 12 }}>
          {err && <div style={{ color: "#f87171" }}>{err}</div>}
          {!rep && !err && <div style={{ opacity: 0.7 }}>Loading…</div>}
          {rep && (
            <>
              <div className="subtitle" style={{ margin: "0 0 10px", fontSize: 12 }}>
                {rep.total_shops.toLocaleString()} shops across all three lists ·{" "}
                {rep.unchecked.toLocaleString()} not checked yet
                {rep.unchecked > 0 && " (the hourly sweep is still working through them)"}
              </div>
              {SECTIONS.map(([title, rows]) => (
                <div key={title} style={{ marginBottom: 14 }}>
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>
                    {title} <span style={{ opacity: 0.6 }}>({rows?.length ?? 0})</span>
                  </div>
                  {rows?.length
                    ? <ReportTable rows={rows} />
                    : <div style={{ opacity: 0.6, fontSize: 13 }}>None.</div>}
                </div>
              ))}
              <button className="btn btn-sm" onClick={load}>Refresh</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
