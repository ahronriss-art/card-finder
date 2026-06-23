import { useMemo, useState } from "react";
import { sendBroadcast, type BroadcastResult } from "./api/client";

// Preset "text back to" contacts — recipients are told to reply to this person.
// Add more here as needed: { name, phone }.
const TEXT_BACK_CONTACTS = [
  { name: "Uriel", phone: "(818) 877-5077" },
];

// Line appended to the broadcast so recipients know who to text back.
function textBackLine(name: string): string {
  const c = TEXT_BACK_CONTACTS.find(c => c.name === name);
  return c ? `\n\nText back to: ${c.name} ${c.phone}` : "";
}

// Quick client-side parse for a live preview of how many valid phone numbers were pasted.
function parsePreview(raw: string) {
  let phones = 0, skipped = 0;
  for (let tok of (raw || "").split(/[\n\r,;\t]+/)) {
    tok = tok.trim();
    if (!tok) continue;
    const digits = tok.replace(/\D/g, "");
    if (digits.length >= 10) phones++;
    else skipped++;
  }
  return { phones, skipped };
}

export default function BroadcastPage() {
  const [recipients, setRecipients] = useState("");
  const [message, setMessage] = useState("");
  const [textBackTo, setTextBackTo] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<BroadcastResult | null>(null);
  const [error, setError] = useState("");

  const preview = useMemo(() => parsePreview(recipients), [recipients]);

  async function send() {
    setError("");
    setResult(null);
    if (!message.trim()) { setError("Write a message first."); return; }
    if (preview.phones === 0) { setError("Add at least one phone number."); return; }
    if (!confirm(`Send this text to ${preview.phones} number(s)?`)) return;
    setSending(true);
    try {
      const fullMessage = message.trim() + textBackLine(textBackTo);
      const r = await sendBroadcast(recipients, fullMessage);
      setResult(r);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to send.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "24px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>Broadcast (Text)</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Paste a list of phone numbers, write one text, and send it to everyone at once.
      </p>

      <div style={{ background: "#fef9c3", border: "1px solid #fde047", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#854d0e", margin: "12px 0" }}>
        ⚠️ Only text people who agreed to hear from you. The message sends exactly as written — Twilio still automatically honors “STOP” replies for opt-out.
      </div>

      <label style={{ fontWeight: 600, fontSize: 14 }}>Phone numbers</label>
      <textarea
        value={recipients}
        onChange={e => setRecipients(e.target.value)}
        placeholder={"Paste phone numbers — one per line or comma-separated.\n818-740-9787\n(212) 555-1234"}
        rows={6}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4 }}
      />
      <div style={{ fontSize: 13, color: "#475569", marginBottom: 12 }}>
        Detected: <strong>{preview.phones}</strong> number{preview.phones === 1 ? "" : "s"}
        {preview.skipped > 0 && <span style={{ color: "#b45309" }}> · {preview.skipped} skipped (unrecognized)</span>}
      </div>

      <label style={{ fontWeight: 600, fontSize: 14 }}>Message</label>
      <textarea
        value={message}
        onChange={e => setMessage(e.target.value)}
        placeholder="Your text message — sent exactly as written."
        rows={5}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4, marginBottom: 12 }}
      />

      <label style={{ fontWeight: 600, fontSize: 14 }}>Text back to</label>
      <select
        value={textBackTo}
        onChange={e => setTextBackTo(e.target.value)}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4 }}
      >
        <option value="">— none —</option>
        {TEXT_BACK_CONTACTS.map(c => (
          <option key={c.name} value={c.name}>{c.name} {c.phone}</option>
        ))}
      </select>
      <div style={{ fontSize: 13, color: "#475569", margin: "4px 0 12px" }}>
        {textBackTo
          ? <>Appended to the text: <em>"{textBackLine(textBackTo).trim()}"</em></>
          : "Optional — adds a \"Text back to: …\" line so recipients know who to reply to."}
      </div>

      <button
        onClick={send}
        disabled={sending}
        style={{ background: sending ? "#94a3b8" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "10px 22px", fontSize: 15, fontWeight: 600, cursor: sending ? "default" : "pointer" }}
      >
        {sending ? "Sending…" : `Send to ${preview.phones} number${preview.phones === 1 ? "" : "s"}`}
      </button>

      {error && <div style={{ color: "#dc2626", marginTop: 12, fontSize: 14 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16, background: "#f1f5f9", borderRadius: 8, padding: 14, fontSize: 14 }}>
          <strong>Done.</strong>
          <div style={{ marginTop: 6 }}>📱 Texts: {result.sms.sent} sent{result.sms.failed ? `, ${result.sms.failed} failed` : ""} (of {result.sms.total})</div>
          {result.skipped.length > 0 && (
            <div style={{ marginTop: 6, color: "#b45309" }}>Skipped {result.skipped.length}: {result.skipped.slice(0, 8).join(", ")}{result.skipped.length > 8 ? "…" : ""}</div>
          )}
        </div>
      )}
    </div>
  );
}
