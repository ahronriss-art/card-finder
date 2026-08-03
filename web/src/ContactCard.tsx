// Per-shop contact card. Builds a vCard (.vcf) you can open on your phone to save
// the shop straight into Contacts, plus a copyable text version. Shared by the
// Shops and New Shops List tabs (each maps its shop into ContactCardData).
import { useState } from "react";
import { textContactCard, addToVFile, aiFillContactCard } from "./api/client";

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
  recap?: string | null;     // intro-call recap (rides along in the card's notes)
  // Which list this shop came from, so the V File can tell one shop's card from
  // another's and refuse to file the same shop twice in a day.
  source?: "main" | "tcg" | "master" | null;
  shopId?: number | null;
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

// How the shop lands in your phone's Contacts: "Mark - Cool Collectors - PA".
// Owner first (falling back to whoever was actually spoken to), then the shop,
// then the state — so a contact list sorted by name groups by person but still
// says which shop and where. Any missing piece is just left out.
export function contactDisplayName(c: ContactCardData): string {
  const person = (c.owner || c.name || "").trim();
  const parts = [person, (c.store || "").trim(), (c.state || "").trim()].filter(Boolean);
  return parts.join(" - ") || (c.store || "").trim();
}

export function buildVCard(c: ContactCardData): string {
  const fn = contactDisplayName(c);
  const note = [
    c.store && `Card store: ${c.store}`,
    c.owner && `Owner: ${c.owner}`,
    c.name && `Contact: ${c.name}`,
    c.state && `State: ${c.state}`,
    igHandle(c.ig) && `IG: ${igHandle(c.ig)}`,
    c.recap && `Call recap: ${c.recap}`,
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
    c.recap && `Call recap: ${c.recap}`,
  ].filter(Boolean).join("\n");
}

export function ContactCardButton({ card }: { card: ContactCardData }) {
  const [open, setOpen] = useState(false);
  const [quick, setQuick] = useState<"" | "saving" | "done" | "already" | "error">("");
  // Straight-to-file shortcut, for working down a list without opening each card.
  async function quickFile(e: React.MouseEvent) {
    e.stopPropagation();
    setQuick("saving");
    try {
      const r = await addToVFile({
        source: card.source || undefined, shop_id: card.shopId ?? undefined,
        store: card.store || "", owner: card.owner || "", name: card.name || "",
        number: card.number || "", email: card.email || "", state: card.state || "",
        ig: card.ig || "", website: card.website || "", city: card.city || "",
        address: card.address || "", recap: card.recap || "",
      });
      setQuick(r.already ? "already" : "done");
    } catch { setQuick("error"); }
    setTimeout(() => setQuick(""), 2200);
  }
  const quickLabel = { "": "📁 V File", saving: "Filing…", done: "Filed ✓",
                       already: "Already filed", error: "Failed" }[quick];
  return (
    <>
      <span style={{ display: "inline-flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.12)", boxShadow: "none" }}
          onClick={e => { e.stopPropagation(); setOpen(true); }}>📇 Contact card</button>
        <button className="btn btn-sm" title="Add this card to today's V File"
          style={{ background: "rgba(255,255,255,0.12)", boxShadow: "none",
                   color: quick === "done" ? "#34d399" : quick === "error" ? "#f87171" : undefined }}
          onClick={quickFile} disabled={quick === "saving"}>{quickLabel}</button>
      </span>
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

function ContactCardModal({ card: initial, onClose }: { card: ContactCardData; onClose: () => void }) {
  // The card is editable here: AI fill writes into it, and what you see is what
  // gets downloaded, texted, or filed. The shop record itself is left alone.
  const [card, setCard] = useState<ContactCardData>(initial);
  const [copied, setCopied] = useState(false);
  const [phone, setPhone] = useState(localStorage.getItem(MY_PHONE_KEY) || "");
  const [sending, setSending] = useState(false);
  const [sendMsg, setSendMsg] = useState("");
  const [filing, setFiling] = useState(false);
  const [fileMsg, setFileMsg] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [aiText, setAiText] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiMsg, setAiMsg] = useState("");

  async function fileToVFile() {
    setFiling(true); setFileMsg("");
    try {
      const r = await addToVFile({
        source: card.source || undefined, shop_id: card.shopId ?? undefined,
        store: card.store || "", owner: card.owner || "", name: card.name || "",
        number: card.number || "", email: card.email || "", state: card.state || "",
        ig: card.ig || "", website: card.website || "", city: card.city || "",
        address: card.address || "", recap: card.recap || "",
      });
      setFileMsg(r.already ? "Already in today's V File." : "Filed to today's V File ✓");
    } catch (e: any) {
      setFileMsg(e?.response?.data?.detail || "Couldn't file that card.");
    } finally { setFiling(false); }
  }

  async function runAiFill() {
    const text = aiText.trim();
    if (!text) { setAiMsg("Paste some text first."); return; }
    setAiBusy(true); setAiMsg("");
    try {
      const { fields, summary } = await aiFillContactCard(text, {
        store: card.store, owner: card.owner, name: card.name, number: card.number,
        email: card.email, website: card.website, ig: card.ig,
        address: card.address, city: card.city, state: card.state,
      });
      const keys = Object.keys(fields);
      if (!keys.length) {
        setAiMsg("Nothing usable in that text — it only fills what's actually written there.");
      } else {
        setCard(c => ({ ...c, ...fields }));
        setAiMsg(`Filled ${keys.join(", ")}${summary ? ` — ${summary}` : ""}`);
        setAiText("");
      }
    } catch (e: any) {
      setAiMsg(e?.response?.data?.detail || "Couldn't read that text.");
    } finally { setAiBusy(false); }
  }
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
        recap: card.recap || "",
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
          <Row label="Saves as" value={contactDisplayName(card)} />
          <Row label="Card store" value={card.store} />
          <Row label="Owner" value={card.owner} />
          <Row label="Contact name" value={card.name} />
          <Row label="Number" value={card.number} />
          <Row label="State" value={card.state} />
          <Row label="Email" value={card.email} />
          <Row label="Instagram" value={igHandle(card.ig)} />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-sm" onClick={fileToVFile} disabled={filing}>
            {filing ? "Filing…" : "📁 Add to V File"}
          </button>
          <button className="btn btn-sm" onClick={download}>⬇ Save to contacts (.vcf)</button>
          <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.12)", boxShadow: "none" }} onClick={copy}>{copied ? "Copied ✓" : "Copy text"}</button>
          <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.12)", boxShadow: "none" }}
            onClick={() => setAiOpen(o => !o)}>✨ AI fill</button>
        </div>
        {fileMsg && <div style={{ fontSize: 12, marginTop: 6, color: fileMsg.includes("✓") ? "#34d399" : "#fbbf24" }}>{fileMsg}</div>}

        {aiOpen && (
          <div style={{ marginTop: 12, padding: 10, borderRadius: 8, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)" }}>
            <div className="shop-field-label" style={{ marginBottom: 6 }}>✨ Fill from pasted text</div>
            <textarea value={aiText} onChange={e => setAiText(e.target.value)} rows={4}
              placeholder="Paste the shop's website footer, a Google result, an email signature, your call notes…"
              style={{ width: "100%", padding: "8px 10px", borderRadius: 8, border: "1px solid rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.05)", color: "inherit", fontFamily: "inherit", fontSize: 13, resize: "vertical" }} />
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6, flexWrap: "wrap" }}>
              <button className="btn btn-sm" onClick={runAiFill} disabled={aiBusy || !aiText.trim()}>
                {aiBusy ? "Reading…" : "Fill the card"}
              </button>
              <span style={{ fontSize: 11, color: "rgba(255,255,255,0.45)" }}>
                Only fills what's written in the text — it can't look anything up.
              </span>
            </div>
            {aiMsg && <div style={{ fontSize: 12, marginTop: 6, color: aiMsg.startsWith("Filled") ? "#34d399" : "#fbbf24" }}>{aiMsg}</div>}
          </div>
        )}

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
