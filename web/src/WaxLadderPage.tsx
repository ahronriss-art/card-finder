import { useEffect, useState } from "react";
import {
  checkShopPassword, getShopsPassword, clearShopsPassword,
  getWaxHistory, getTrackedWax, trackWaxBox, untrackWaxBox, setWaxTarget,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";
import LadderBoard, { type LadderConfig } from "./LadderBoard";

const WAX_CONFIG: LadderConfig = {
  title: "Wax Ladder",
  subtitle: "Search any sealed wax box → see what it's actually selling for on eBay, with a price chart.",
  placeholder: "e.g. 2024 Topps Chrome Baseball Hobby Box",
  suggest: [
    "2024 Topps Chrome Baseball Hobby Box",
    "2023-24 Panini Prizm Basketball Hobby Box",
    "2024 Bowman Chrome Baseball Hobby Box",
    "2023 Topps Chrome UCL Hobby Box",
  ],
  trackLabel: "📌 Track this box",
  trackedTitle: "📌 Tracked boxes",
  emptyHint: "No sealed-box sales found — try the full box name (e.g. add 'Hobby Box').",
  compsNote: "Sold comps from eBay (last ~50), filtered to sealed boxes — breaks, cases, singles, and graded lots are excluded.",
  api: { history: getWaxHistory, tracked: getTrackedWax, track: trackWaxBox, untrack: untrackWaxBox, target: setWaxTarget },
};

export default function WaxLadderPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    const stored = getShopsPassword();
    if (!stored) { setChecking(false); return; }
    setUnlocked(true); setChecking(false);
    checkShopPassword(stored).catch((err) => {
      if (err?.response?.status === 401) { clearShopsPassword(); setUnlocked(false); }
    });
  }, []);
  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;
  if (!unlocked) return <ShopPasswordForm title="Wax Ladder" onUnlocked={() => setUnlocked(true)} />;
  return <LadderBoard config={WAX_CONFIG} />;
}
