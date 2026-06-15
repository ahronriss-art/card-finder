import { useState } from "react";
import SearchPage from "./SearchPage";
import AlertsPage from "./AlertsPage";
import EmailWriterPage from "./EmailWriterPage";
import ShopsPage from "./ShopsPage";
import AuctionsPage from "./AuctionsPage";
import StudioPage from "./StudioPage";
import Chatbot from "./Chatbot";
import "./index.css";

type Tab = "search" | "alerts" | "email" | "shops" | "auctions" | "studio";

export default function App() {
  const [tab, setTab] = useState<Tab>("alerts");
  const [auctionAlertSignal, setAuctionAlertSignal] = useState(0);

  return (
    <>
      <nav>
        <div className="nav-inner">
          <span className="nav-logo" onClick={() => setTab("alerts")}>Card Finder</span>
          <button className={`nav-tab${tab === "alerts" ? " active" : ""}`} onClick={() => setTab("alerts")}>Alerts</button>
          <button className={`nav-tab${tab === "search" ? " active" : ""}`} onClick={() => setTab("search")}>Search</button>
          <button className={`nav-tab${tab === "email" ? " active" : ""}`} onClick={() => setTab("email")}>Email Writer</button>
          <button className={`nav-tab${tab === "shops" ? " active" : ""}`} onClick={() => setTab("shops")}>Shops</button>
          <button className={`nav-tab${tab === "auctions" ? " active" : ""}`} onClick={() => setTab("auctions")}>Auctions</button>
          <button className={`nav-tab${tab === "studio" ? " active" : ""}`} onClick={() => setTab("studio")}>Studio</button>
        </div>
      </nav>
      {tab === "search" && <SearchPage />}
      {tab === "alerts" && <AlertsPage auctionAlertSignal={auctionAlertSignal} />}
      {tab === "email" && <EmailWriterPage />}
      {tab === "shops" && <ShopsPage />}
      {tab === "auctions" && <AuctionsPage onCreateAuctionAlert={() => { setAuctionAlertSignal(n => n + 1); setTab("alerts"); }} />}
      {tab === "studio" && <StudioPage />}
      <Chatbot />
    </>
  );
}
