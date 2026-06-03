import { useState, useRef, useEffect } from "react";
import { api } from "./api/client";

interface Message {
  role: "user" | "assistant";
  text: string;
}

export default function Chatbot() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([
    { role: "assistant", text: "Hi! I can help you write messages to sellers or buyers. Tell me what you want to say and I'll craft the perfect message. For example:\n\n• \"Offer $X for this card\"\n• \"Ask if they'll bundle 2 cards\"\n• \"Ask about the card's condition\"\n• \"Respond to a lowball offer\"" }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, open]);

  async function sendMessage(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setInput("");
    setMessages(prev => [...prev, { role: "user", text: userMsg }]);
    setLoading(true);
    try {
      const { data } = await api.post("/chat", { message: userMsg, history: messages.slice(-6) });
      setMessages(prev => [...prev, { role: "assistant", text: data.reply }]);
    } catch {
      setMessages(prev => [...prev, { role: "assistant", text: "Sorry, something went wrong. Try again." }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {/* Floating button */}
      <button className="chat-bubble" onClick={() => setOpen(v => !v)} title="Message Helper">
        {open ? "✕" : "💬"}
        {!open && <span className="chat-bubble-label">Message Helper</span>}
      </button>

      {/* Chat panel */}
      {open && (
        <div className="chat-panel">
          <div className="chat-header">
            <div>
              <div className="chat-title">Message Helper</div>
              <div className="chat-subtitle">AI writes seller/buyer messages for you</div>
            </div>
            <button className="chat-close" onClick={() => setOpen(false)}>✕</button>
          </div>

          <div className="chat-messages">
            {messages.map((msg, i) => (
              <div key={i} className={`chat-msg ${msg.role}`}>
                {msg.role === "assistant" && <div className="chat-avatar">🤖</div>}
                <div className="chat-bubble-msg">
                  {msg.text.split("\n").map((line, j) => (
                    <span key={j}>{line}{j < msg.text.split("\n").length - 1 && <br />}</span>
                  ))}
                </div>
              </div>
            ))}
            {loading && (
              <div className="chat-msg assistant">
                <div className="chat-avatar">🤖</div>
                <div className="chat-bubble-msg chat-typing">
                  <span /><span /><span />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <form className="chat-input-row" onSubmit={sendMessage}>
            <input
              type="text"
              placeholder="e.g. Offer $200, ask about condition..."
              value={input}
              onChange={e => setInput(e.target.value)}
              disabled={loading}
            />
            <button type="submit" disabled={loading || !input.trim()}>Send</button>
          </form>
        </div>
      )}
    </>
  );
}
