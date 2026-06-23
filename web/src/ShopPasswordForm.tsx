import { useState } from "react";
import { checkShopPassword, saveShopsPassword } from "./api/client";

// Shared password gate form: validates the Shops password, lets the user choose
// whether to stay logged in on this device, and is structured so the browser's
// own password manager can offer to save + autofill it.
export default function ShopPasswordForm({
  title,
  subtitle,
  onUnlocked,
}: {
  title: string;
  subtitle?: string;
  onUnlocked: () => void;
}) {
  const [pw, setPw] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await checkShopPassword(pw.trim());
      saveShopsPassword(pw.trim(), remember);
      onUnlocked();
    } catch {
      setError("Wrong password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app" style={{ paddingTop: 60, maxWidth: 440 }}>
      <h1>🔒 {title}</h1>
      <p className="subtitle">{subtitle || "This is private. Enter the password to continue."}</p>
      <form onSubmit={submit} style={{ marginTop: 24 }}>
        {/* Hidden username so the browser's password manager offers to save the password. */}
        <input type="text" name="username" autoComplete="username" value="card-finder" readOnly hidden />
        <div className="form-group">
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            placeholder="Password"
            value={pw}
            onChange={e => setPw(e.target.value)}
            autoFocus
          />
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, margin: "6px 2px 14px" }}>
          <input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} />
          Remember me on this device
        </label>
        {error && <div className="error-msg">{error}</div>}
        <button className="btn" type="submit" disabled={busy} style={{ width: "100%", marginTop: 4 }}>
          {busy ? "Checking…" : "Enter →"}
        </button>
      </form>
    </div>
  );
}
