import { useEffect, useState } from "react";
import {
  checkShopPassword, getShopsPassword, clearShopsPassword,
  getCardHistory, getTrackedCards, trackCard, untrackCard, setCardTarget,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";
import LadderBoard, { type LadderConfig } from "./LadderBoard";

const CARD_CONFIG: LadderConfig = {
  title: "Card Prices",
  subtitle: "Search any single card → see its recent sold prices, a chart, and track it over time.",
  placeholder: "e.g. 2023 Prizm Victor Wembanyama Silver PSA 10",
  suggest: [
    "2023 Prizm Victor Wembanyama Silver PSA 10",
    "2024 Topps Chrome Paul Skenes Refractor",
    "2003 Topps Chrome LeBron James Refractor PSA 10",
    "2018 Prizm Luka Doncic Silver PSA 10",
  ],
  trackLabel: "📌 Track this card",
  trackedTitle: "📌 Tracked cards",
  emptyHint: "No card sales found — add more detail (year, set, parallel, grade).",
  compsNote: "Sold comps from eBay (last ~50), filtered to this exact card — boxes, breaks, and lots are excluded, and a '/N' serial is enforced.",
  api: { history: getCardHistory, tracked: getTrackedCards, track: trackCard, untrack: untrackCard, target: setCardTarget },
};

export default function CardLadderPage() {
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
  if (!unlocked) return <ShopPasswordForm title="Card Prices" onUnlocked={() => setUnlocked(true)} />;
  return <LadderBoard config={CARD_CONFIG} />;
}
