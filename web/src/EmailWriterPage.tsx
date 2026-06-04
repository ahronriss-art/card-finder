import { useState } from "react";
import { api } from "./api/client";

const TEMPLATES = [
  { label: "Make an offer", prompt: "I want to offer a lower price for a card" },
  { label: "Ask about condition", prompt: "I want to ask the seller about the card's condition and if it has any flaws" },
  { label: "Bundle deal", prompt: "I want to ask if they'll bundle multiple cards for a discount" },
  { label: "Ask for more photos", prompt: "I want to ask the seller for more photos of the card" },
  { label: "Respond to lowball", prompt: "A buyer lowballed me and I want to counter-offer politely" },
  { label: "Ask about shipping", prompt: "I want to ask about shipping cost, speed, and packaging method" },
  { label: "Negotiate after inspection", prompt: "The card arrived and it's not as described, I want to ask for a partial refund" },
  { label: "Thank seller", prompt: "I want to thank the seller after receiving a card in great condition" },
];

export default function EmailWriterPage() {
  const [prompt, setPrompt] = useState("");
  const [cardName, setCardName] = useState("");
  const [price, setPrice] = useState("");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    if (!prompt.trim()) return;
    setLoading(true);
    setError("");
    setEmail("");
    try {
      const fullPrompt = [
        cardName && `Card: ${cardName}`,
        price && `Price/offer: $${price}`,
        `Request: ${prompt}`,
      ].filter(Boolean).join("\n");

      const { data } = await api.post("/chat", {
        message: `Write a complete, ready-to-send email to an eBay seller. ${fullPrompt}.

Format it exactly like this:
Subject: [subject line]

[email body]

Make it polite, professional, and specific. Just output the subject line and email body — nothing else.`,
        history: [],
      });
      setEmail(data.reply);
    } catch {
      setError("Failed to generate email. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  }

  function copyEmail() {
    navigator.clipboard.writeText(email);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 700 }}>
      <h1>Email Writer</h1>
      <p className="subtitle">Describe what you want to say — AI writes the perfect email to copy and send to the seller.</p>

      {/* Quick templates */}
      <div className="email-templates-label">Quick templates</div>
      <div className="email-templates">
        {TEMPLATES.map(t => (
          <button key={t.label} className="email-template-chip" onClick={() => setPrompt(t.prompt)}>
            {t.label}
          </button>
        ))}
      </div>

      <form onSubmit={generate}>
        {/* Card name */}
        <div className="form-group">
          <label>Card Name (optional)</label>
          <input
            type="text"
            placeholder="e.g. LeBron James 2003 Rookie PSA 9"
            value={cardName}
            onChange={e => setCardName(e.target.value)}
          />
        </div>

        {/* Price */}
        <div className="form-group">
          <label>Price / Offer Amount (optional)</label>
          <input
            type="text"
            placeholder="e.g. 150"
            value={price}
            onChange={e => setPrice(e.target.value)}
          />
        </div>

        {/* Main prompt */}
        <div className="form-group">
          <label>What do you want to say?</label>
          <textarea
            className="email-prompt-input"
            placeholder="e.g. I want to offer $150 instead of the listed $200, and ask if they'll include free shipping..."
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            rows={4}
          />
        </div>

        {error && <div className="error-msg">{error}</div>}

        <button className="btn" type="submit" disabled={loading || !prompt.trim()} style={{ width: "100%" }}>
          {loading ? "Writing email..." : "✍️ Generate Email"}
        </button>
      </form>

      {/* Generated email */}
      {email && (
        <div className="email-output">
          <div className="email-output-header">
            <span className="email-output-title">Your Email</span>
            <button className={`copy-btn${copied ? " copied" : ""}`} onClick={copyEmail}>
              {copied ? "✓ Copied!" : "Copy"}
            </button>
          </div>
          <pre className="email-output-body">{email}</pre>
          <p className="email-output-hint">Copy this and paste it directly into eBay's message system or your email client.</p>
        </div>
      )}
    </div>
  );
}
