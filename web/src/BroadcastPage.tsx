import { useMemo, useState } from "react";
import { sendBroadcast, type BroadcastResult } from "./api/client";

// Quick client-side parse for a live preview of how many emails vs phones were pasted.
function parsePreview(raw: string) {
  let emails = 0, phones = 0, skipped = 0;
  for (let tok of (raw || "").split(/[\n\r,;\t]+/)) {
    tok = tok.trim();
    if (!tok) continue;
    if (tok.includes("@") && tok.split("@").pop()!.includes(".")) { emails++; continue; }
    const digits = tok.replace(/\D/g, "");
    if (digits.length >= 10) phones++;
    else skipped++;
  }
  return { emails, phones, skipped };
}

export default function BroadcastPage() {
  const [recipients, setRecipients] = useState("");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<BroadcastResult | null>(null);
  const [error, setError] = useState("");

  const preview = useMemo(() => parsePreview(recipients), [recipients]);
  const totalTargets = preview.emails + preview.phones;

  async function send() {
    setError("");
    setResult(null);
    if (!message.trim()) { setError("Write a message first."); return; }
    if (totalTargets === 0) { setError("Add at least one email or phone number."); return; }
    if (!confirm(`Send this message to ${preview.emails} email(s) and ${preview.phones} phone(s)?`)) return;
    setSending(true);
    try {
      const r = await sendBroadcast(recipients, message, subject);
      setResult(r);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "Failed to send.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div style={{ maxWidth: 720, margin: "24px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>Broadcast</h1>
      <p style={{ color: "#64748b", marginTop: 0 }}>
        Paste a list of emails and/or phone numbers, write one message, and send it to everyone at once.
      </p>

      <div style={{ background: "#fef9c3", border: "1px solid #fde047", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#854d0e", margin: "12px 0" }}>
        ⚠️ Only message people who agreed to hear from you. Emails include an unsubscribe line. Texts send exactly as written — Twilio still automatically honors “STOP” replies for opt-out.
      </div>

      <label style={{ fontWeight: 600, fontSize: 14 }}>Recipients</label>
      <textarea
        value={recipients}
        onChange={e => setRecipients(e.target.value)}
        placeholder={"Paste emails and phone numbers — one per line or comma-separated.\njohn@example.com\n818-740-9787\n(212) 555-1234"}
        rows={6}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4 }}
      />
      <div style={{ fontSize: 13, color: "#475569", marginBottom: 12 }}>
        Detected: <strong>{preview.emails}</strong> email{preview.emails === 1 ? "" : "s"} ·{" "}
        <strong>{preview.phones}</strong> phone{preview.phones === 1 ? "" : "s"}
        {preview.skipped > 0 && <span style={{ color: "#b45309" }}> · {preview.skipped} skipped (unrecognized)</span>}
      </div>

      <label style={{ fontWeight: 600, fontSize: 14 }}>Email subject <span style={{ color: "#94a3b8", fontWeight: 400 }}>(email only)</span></label>
      <input
        value={subject}
        onChange={e => setSubject(e.target.value)}
        placeholder="Subject line for emails"
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14, marginTop: 4, marginBottom: 12 }}
      />

      <label style={{ fontWeight: 600, fontSize: 14 }}>Message</label>
      <textarea
        value={message}
        onChange={e => setMessage(e.target.value)}
        placeholder="Your message — sent as the email body and the text message."
        rows={6}
        style={{ width: "100%", padding: 10, borderRadius: 8, border: "1px solid #cbd5e1", fontFamily: "inherit", fontSize: 14, marginTop: 4, marginBottom: 12 }}
      />

      <button
        onClick={send}
        disabled={sending}
        style={{ background: sending ? "#94a3b8" : "#2563eb", color: "#fff", border: "none", borderRadius: 8, padding: "10px 22px", fontSize: 15, fontWeight: 600, cursor: sending ? "default" : "pointer" }}
      >
        {sending ? "Sending…" : `Send to ${totalTargets} recipient${totalTargets === 1 ? "" : "s"}`}
      </button>

      {error && <div style={{ color: "#dc2626", marginTop: 12, fontSize: 14 }}>{error}</div>}

      {result && (
        <div style={{ marginTop: 16, background: "#f1f5f9", borderRadius: 8, padding: 14, fontSize: 14 }}>
          <strong>Done.</strong>
          <div style={{ marginTop: 6 }}>📧 Emails: {result.emails.sent} sent{result.emails.failed ? `, ${result.emails.failed} failed` : ""} (of {result.emails.total})</div>
          <div>📱 Texts: {result.sms.sent} sent{result.sms.failed ? `, ${result.sms.failed} failed` : ""} (of {result.sms.total})</div>
          {result.skipped.length > 0 && (
            <div style={{ marginTop: 6, color: "#b45309" }}>Skipped {result.skipped.length}: {result.skipped.slice(0, 8).join(", ")}{result.skipped.length > 8 ? "…" : ""}</div>
          )}
        </div>
      )}
    </div>
  );
}
