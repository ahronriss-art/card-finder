import { useState } from "react";
import SearchPage from "./SearchPage";
import AlertsPage from "./AlertsPage";
import ShopsPage from "./ShopsPage";
import AuctionsPage from "./AuctionsPage";
import CallerNotesPage from "./CallerNotesPage";
import DealsPage from "./DealsPage";
import BroadcastPage from "./BroadcastPage";
import RecentFindsPage from "./RecentFindsPage";
import AuctionWatchPage from "./AuctionWatchPage";
import AllMatchesPage from "./AllMatchesPage";
import CardLookupPage from "./CardLookupPage";
import Chatbot from "./Chatbot";
import "./index.css";

type Tab = "search" | "alerts" | "shops" | "auctions" | "notes" | "deals" | "broadcast" | "finds" | "auctionwatch" | "matches" | "lookup";

export default function App() {
  const [tab, setTab] = useState<Tab>("alerts");
  const [auctionAlertSignal, setAuctionAlertSignal] = useState(0);

  return (
    <>
      <nav>
        <div className="nav-inner">
          <span className="nav-logo" onClick={() => setTab("alerts")}>Card Finder</span>
          <button className={`nav-tab${tab === "alerts" ? " active" : ""}`} onClick={() => setTab("alerts")}>Alerts</button>
          <button className={`nav-tab${tab === "finds" ? " active" : ""}`} onClick={() => setTab("finds")}>Recent Finds</button>
          <button className={`nav-tab${tab === "matches" ? " active" : ""}`} onClick={() => setTab("matches")}>All Matches</button>
          <button className={`nav-tab${tab === "lookup" ? " active" : ""}`} onClick={() => setTab("lookup")}>Card Lookup</button>
          <button className={`nav-tab${tab === "auctionwatch" ? " active" : ""}`} onClick={() => setTab("auctionwatch")}>Auction Watch</button>
          <button className={`nav-tab${tab === "notes" ? " active" : ""}`} onClick={() => setTab("notes")}>Caller Notes</button>
          <button className={`nav-tab${tab === "shops" ? " active" : ""}`} onClick={() => setTab("shops")}>Shops</button>
          <button className={`nav-tab${tab === "auctions" ? " active" : ""}`} onClick={() => setTab("auctions")}>Auctions</button>
          <button className={`nav-tab${tab === "broadcast" ? " active" : ""}`} onClick={() => setTab("broadcast")}>Broadcast</button>
          <button className={`nav-tab${tab === "search" ? " active" : ""}`} onClick={() => setTab("search")}>Search</button>
          <button className={`nav-tab${tab === "deals" ? " active" : ""}`} onClick={() => setTab("deals")}>Deals</button>
        </div>
      </nav>
      {tab === "search" && <SearchPage />}
      {tab === "alerts" && <AlertsPage auctionAlertSignal={auctionAlertSignal} />}
      {tab === "finds" && <RecentFindsPage />}
      {tab === "matches" && <AllMatchesPage />}
      {tab === "lookup" && <CardLookupPage />}
      {tab === "auctionwatch" && <AuctionWatchPage />}
      {tab === "shops" && <ShopsPage />}
      {tab === "auctions" && <AuctionsPage onCreateAuctionAlert={() => { setAuctionAlertSignal(n => n + 1); setTab("alerts"); }} />}
      {tab === "notes" && <CallerNotesPage />}
      {tab === "deals" && <DealsPage />}
      {tab === "broadcast" && <BroadcastPage />}
      <Chatbot />
    </>
  );
}
