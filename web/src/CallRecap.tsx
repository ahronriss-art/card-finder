// Intro-call recap box with an AI "Summarize" button. Shared by the Shops and
// New Shops List tabs — each passes an onSave that persists to its own shop type.
import { useState } from "react";
import { summarizeCall } from "./api/client";

export function CallRecapBox({ value, onSave }: {
  value: string;
  onSave: (text: string) => Promise<void> | void;
}) {
  const [v, setV] = useState(value);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function commit() {
    if (v !== value) await onSave(v);
  }
  async function summarize() {
    if (!v.trim() || busy) return;
    setBusy(true); setErr("");
    try {
      const { summary } = await summarizeCall(v);
      if (summary) { setV(summary); await onSave(summary); }
    } catch {
      setErr("Couldn't summarize — try again.");
    } finally { setBusy(false); }
  }

  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div className="shop-field-label">📞 Intro call recap</div>
        <button className="btn btn-sm" style={{ background: "rgba(124,58,237,0.25)", boxShadow: "none" }}
          onClick={summarize} disabled={busy || !v.trim()}>
          {busy ? "Summarizing…" : "✨ Summarize"}
        </button>
      </div>
      <textarea rows={3} value={v}
        placeholder="Summarize what your intro call was about — or dump rough notes and hit ✨ Summarize"
        onChange={e => setV(e.target.value)} onBlur={commit}
        style={{ width: "100%", resize: "vertical", lineHeight: 1.5, padding: "8px 10px", borderRadius: 8,
          border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit" }} />
      {err && <div style={{ fontSize: 12, marginTop: 4, color: "#fbbf24" }}>{err}</div>}
    </div>
  );
}
