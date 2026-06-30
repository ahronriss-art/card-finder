import { useMemo, useState } from "react";
import { sendBroadcast, type BroadcastResult } from "./api/client";

// Preset "text back to" contacts — recipients are told to reply to this person.
// Add more here as needed: { name, phone }.
const TEXT_BACK_CONTACTS = [
  { name: "Uriel", phone: "(818) 877-5077" },
];

// Line(s) appended to the broadcast so recipients know who to text/call back.
// `raw` holds one contact per line; supports multiple.
function textBackLine(raw: string): string {
  const contacts = (raw || "").split(/[\n\r]+/).map(s => s.trim()).filter(Boolean);
  if (!contacts.length) return "";
  if (contacts.length === 1) return `\n\nText or call back to: ${contacts[0]}`;
  return `\n\nText or call back to:\n${contacts.map(c => `• ${c}`).join("\n")}`;
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
  const [followUpName, setFollowUpName] = useState("");
  const [followUpPhone, setFollowUpPhone] = useState("");
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
      const r = await sendBroadcast(recipients, fullMessage, followUpName.trim() || undefined, followUpPhone.trim() || undefined);
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

      <label style={{ fontWeight: 600, fontSize: 14 }}>Text or Call back to</label>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "6px 0" }}>
        {TEXT_BACK_CONTACTS.map(c => {
          const entry = `${c.name} ${c.phone}`;
          const already = textBackTo.split(/[\n\r]+/).map(s => s.trim()).includes(entry);
          return (
            <button key={c.name} type="button" disabled={already}
              onClick={() => setTextBackTo(t => (t.trim() ? t.trim() + "\n" : "") + entry)}
              style={{ fontSize: 13, fontWeight: 600, padding: "5px 11px", borderRadius: 999, cursor: already ? "default" : "pointer",
                border: "1px solid #cbd5e1", background: already ? "#e2e8f0" : "#fff", color: "#334155" }}>
              {already ? "✓ " : "+ "}{c.name} {c.phone}
            </button>
          );
        })}
      </div>
      <textarea
        value={textBackTo}
        onChange={e => setTextBackTo(e.target.value)}
        placeholder={"One contact per line — name and/or number.\nUriel (818) 877-5077\nAvi 212-555-1234"}
        rows={3}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4 }}
      />
      <div style={{ fontSize: 13, color: "#475569", margin: "4px 0 12px" }}>
        {textBackTo.trim()
          ? <>Appended to the text: <em style={{ whiteSpace: "pre-wrap" }}>"{textBackLine(textBackTo).trim()}"</em></>
          : "Optional — add one or more people (one per line) so recipients know who to text or call back."}
      </div>

      <label style={{ fontWeight: 600, fontSize: 14 }}>Assign follow-up teammate (optional)</label>
      <div style={{ fontSize: 13, color: "#475569", margin: "2px 0 6px" }}>
        When recipients reply, those replies route to this teammate — they'll get a text heads-up and can answer
        right from the <strong>Inbox</strong> tab (replies go back out through the 877, so the customer sees one conversation).
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <input value={followUpName} onChange={e => setFollowUpName(e.target.value)} placeholder="Teammate name (e.g. Uriel)"
          style={{ flex: 1, minWidth: 160, padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
        <input value={followUpPhone} onChange={e => setFollowUpPhone(e.target.value)} placeholder="Their phone (for reply alerts)"
          style={{ flex: 1, minWidth: 160, padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 }} />
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
