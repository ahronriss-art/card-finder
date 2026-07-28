// Per-shop contact card. Builds a vCard (.vcf) you can open on your phone to save
// the shop straight into Contacts, plus a copyable text version. Shared by the
// Shops and New Shops List tabs (each maps its shop into ContactCardData).
import { useState } from "react";
import { textContactCard } from "./api/client";

const MY_PHONE_KEY = "myContactPhone";

export type ContactCardData = {
  store: string;
  owner?: string | null;
  name?: string | null;      // person contacted at the shop
  number?: string | null;
  state?: string | null;
  email?: string | null;
  ig?: string | null;
  website?: string | null;
  city?: string | null;
  address?: string | null;
};

function igHandle(ig?: string | null): string {
  if (!ig) return "";
  const h = String(ig).trim()
    .replace(/^https?:\/\/(www\.)?instagram\.com\//i, "")
    .replace(/\/+$/, "").replace(/^@/, "");
  return h ? "@" + h : "";
}
function igUrl(ig?: string | null): string {
  const h = igHandle(ig).replace(/^@/, "");
  return h ? `https://instagram.com/${h}` : "";
}
const esc = (s: string) => String(s).replace(/([,;\\])/g, "\\$1").replace(/\n/g, "\\n");

export function buildVCard(c: ContactCardData): string {
  const fn = c.name || c.owner || c.store;
  const note = [
    c.store && `Card store: ${c.store}`,
    c.owner && `Owner: ${c.owner}`,
    c.name && `Contact: ${c.name}`,
    c.state && `State: ${c.state}`,
    igHandle(c.ig) && `IG: ${igHandle(c.ig)}`,
  ].filter(Boolean).join(" | ");
  return [
    "BEGIN:VCARD", "VERSION:3.0",
    `FN:${esc(fn)}`,
    `N:;${esc(fn)};;;`,
    c.store && `ORG:${esc(c.store)}`,
    c.number && `TEL;TYPE=CELL:${esc(c.number)}`,
    c.email && `EMAIL;TYPE=INTERNET:${esc(c.email)}`,
    c.website && `URL:${esc(c.website)}`,
    igUrl(c.ig) && `X-SOCIALPROFILE;TYPE=instagram:${igUrl(c.ig)}`,
    (c.address || c.city || c.state) && `ADR;TYPE=WORK:;;${esc(c.address || "")};${esc(c.city || "")};${esc(c.state || "")};;`,
    note && `NOTE:${esc(note)}`,
    "END:VCARD",
  ].filter(Boolean).join("\r\n");
}

function textVersion(c: ContactCardData): string {
  return [
    `📇 ${c.store}`,
    c.owner && `Owner: ${c.owner}`,
    c.name && `Contact: ${c.name}`,
    c.number && `Number: ${c.number}`,
    c.state && `State: ${c.state}`,
    c.email && `Email: ${c.email}`,
    igHandle(c.ig) && `IG: ${igHandle(c.ig)}`,
  ].filter(Boolean).join("\n");
}

export function ContactCardButton({ card }: { card: ContactCardData }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.12)", boxShadow: "none" }}
        onClick={e => { e.stopPropagation(); setOpen(true); }}>📇 Contact card</button>
      {open && <ContactCardModal card={card} onClose={() => setOpen(false)} />}
    </>
  );
}

function Row({ label, value }: { label: string; value?: string | null }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "7px 0", borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
      <span style={{ fontSize: 12, color: "rgba(255,255,255,0.5)", fontWeight: 600 }}>{label}</span>
      <span style={{ fontSize: 14, textAlign: "right" }}>{value || <span style={{ opacity: 0.35 }}>—</span>}</span>
    </div>
  );
}

function ContactCardModal({ card, onClose }: { card: ContactCardData; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const [phone, setPhone] = useState(localStorage.getItem(MY_PHONE_KEY) || "");
  const [sending, setSending] = useState(false);
  const [sendMsg, setSendMsg] = useState("");
  async function textToPhone() {
    const to = phone.trim();
    if (!to) { setSendMsg("Enter your phone number first."); return; }
    setSending(true); setSendMsg("");
    localStorage.setItem(MY_PHONE_KEY, to);
    try {
      await textContactCard({
        phone: to, store: card.store || "", owner: card.owner || "", name: card.name || "",
        number: card.number || "", email: card.email || "", state: card.state || "",
        ig: card.ig || "", website: card.website || "", city: card.city || "", address: card.address || "",
      });
      setSendMsg("Sent ✓ — check your phone and tap the card to save it.");
    } catch (e: any) {
      setSendMsg(e?.response?.data?.detail || "Couldn't send the text.");
    } finally { setSending(false); }
  }
  function download() {
    const blob = new Blob([buildVCard(card)], { type: "text/vcard;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(card.store || "contact").replace(/[^\w]+/g, "_").slice(0, 40)}.vcf`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function copy() {
    try { await navigator.clipboard.writeText(textVersion(card)); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  }
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <h2 style={{ margin: 0, fontSize: 20 }}>📇 Contact card</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>
        <div style={{ margin: "14px 0" }}>
          <Row label="Card store" value={card.store} />
          <Row label="Owner" value={card.owner} />
          <Row label="Contact name" value={card.name} />
          <Row label="Number" value={card.number} />
          <Row label="State" value={card.state} />
          <Row label="Email" value={card.email} />
          <Row label="Instagram" value={igHandle(card.ig)} />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-sm" onClick={download}>⬇ Save to contacts (.vcf)</button>
          <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.12)", boxShadow: "none" }} onClick={copy}>{copied ? "Copied ✓" : "Copy text"}</button>
        </div>

        <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid rgba(255,255,255,0.1)" }}>
          <div className="shop-field-label" style={{ marginBottom: 6 }}>📲 Text this card to my phone</div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input type="tel" placeholder="Your phone number" value={phone}
              onChange={e => setPhone(e.target.value)}
              style={{ flex: 1, minWidth: 160, padding: "8px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit" }} />
            <button className="btn btn-sm" onClick={textToPhone} disabled={sending || !phone.trim()}>
              {sending ? "Sending…" : "Text me"}
            </button>
          </div>
          {sendMsg && <div style={{ fontSize: 12, marginTop: 6, color: sendMsg.startsWith("Sent") ? "#34d399" : "#fbbf24" }}>{sendMsg}</div>}
        </div>

        <p className="subtitle" style={{ fontSize: 12, marginTop: 10, marginBottom: 0 }}>
          Tap the texted card (or open the downloaded .vcf) on your phone to save it to Contacts. Your number is remembered for next time.
        </p>
      </div>
    </div>
  );
}
