import { useState } from "react";
import SearchPage from "./SearchPage";
import AlertsPage from "./AlertsPage";
import ShopsPage from "./ShopsPage";
import AuctionsPage from "./AuctionsPage";
import CallerNotesPage from "./CallerNotesPage";
import TasksPage from "./TasksPage";
import InboxPage from "./InboxPage";
import ReleasesPage from "./ReleasesPage";
import DealsPage from "./DealsPage";
import BroadcastPage from "./BroadcastPage";
import RecentFindsPage from "./RecentFindsPage";
import AuctionWatchPage from "./AuctionWatchPage";
import AllMatchesPage from "./AllMatchesPage";
import CardLookupPage from "./CardLookupPage";
import TrendingPage from "./TrendingPage";
import PortfolioPage from "./PortfolioPage";
import NewsPage from "./NewsPage";
import DashboardPage from "./DashboardPage";
import Chatbot from "./Chatbot";
import "./index.css";

type Tab = "search" | "alerts" | "shops" | "auctions" | "notes" | "tasks" | "deals" | "broadcast" | "inbox" | "releases" | "finds" | "auctionwatch" | "matches" | "lookup" | "trending" | "portfolio" | "news" | "dashboard";

export default function App() {
  const [tab, setTab] = useState<Tab>("alerts");
  const [auctionAlertSignal, setAuctionAlertSignal] = useState(0);

  return (
    <>
      <nav>
        <div className="nav-inner">
          <span className="nav-logo" onClick={() => setTab("alerts")}>Card Finder</span>
          <button className={`nav-tab${tab === "dashboard" ? " active" : ""}`} onClick={() => setTab("dashboard")}>Dashboard</button>
          <button className={`nav-tab${tab === "alerts" ? " active" : ""}`} onClick={() => setTab("alerts")}>Alerts</button>
          <button className={`nav-tab${tab === "finds" ? " active" : ""}`} onClick={() => setTab("finds")}>Recent Finds</button>
          <button className={`nav-tab${tab === "lookup" ? " active" : ""}`} onClick={() => setTab("lookup")}>Pop Report</button>
          <button className={`nav-tab${tab === "releases" ? " active" : ""}`} onClick={() => setTab("releases")}>Releases/Wax</button>
          <button className={`nav-tab${tab === "portfolio" ? " active" : ""}`} onClick={() => setTab("portfolio")}>Portfolio</button>
          <button className={`nav-tab${tab === "news" ? " active" : ""}`} onClick={() => setTab("news")}>News</button>
          <button className={`nav-tab${tab === "auctionwatch" ? " active" : ""}`} onClick={() => setTab("auctionwatch")}>Auction Watch</button>
          <button className={`nav-tab${tab === "notes" ? " active" : ""}`} onClick={() => setTab("notes")}>Caller Notes</button>
          <button className={`nav-tab${tab === "tasks" ? " active" : ""}`} onClick={() => setTab("tasks")}>Tasks</button>
          <button className={`nav-tab${tab === "shops" ? " active" : ""}`} onClick={() => setTab("shops")}>Shops</button>
          <button className={`nav-tab${tab === "trending" ? " active" : ""}`} onClick={() => setTab("trending")}>Trending</button>
          <button className={`nav-tab${tab === "auctions" ? " active" : ""}`} onClick={() => setTab("auctions")}>Auctions</button>
          <button className={`nav-tab${tab === "broadcast" ? " active" : ""}`} onClick={() => setTab("broadcast")}>Broadcast</button>
          <button className={`nav-tab${tab === "inbox" ? " active" : ""}`} onClick={() => setTab("inbox")}>Inbox</button>
          <button className={`nav-tab${tab === "search" ? " active" : ""}`} onClick={() => setTab("search")}>Search</button>
          <button className={`nav-tab${tab === "deals" ? " active" : ""}`} onClick={() => setTab("deals")}>Deals</button>
          <button className={`nav-tab${tab === "matches" ? " active" : ""}`} onClick={() => setTab("matches")}>All Matches</button>
        </div>
      </nav>
      {tab === "search" && <SearchPage />}
      {tab === "alerts" && <AlertsPage auctionAlertSignal={auctionAlertSignal} />}
      {tab === "finds" && <RecentFindsPage />}
      {tab === "matches" && <AllMatchesPage />}
      {tab === "lookup" && <CardLookupPage />}
      {tab === "auctionwatch" && <AuctionWatchPage />}
      {tab === "shops" && <ShopsPage />}
      {tab === "trending" && <TrendingPage />}
      {tab === "auctions" && <AuctionsPage onCreateAuctionAlert={() => { setAuctionAlertSignal(n => n + 1); setTab("alerts"); }} />}
      {tab === "notes" && <CallerNotesPage />}
      {tab === "tasks" && <TasksPage />}
      {tab === "deals" && <DealsPage />}
      {tab === "broadcast" && <BroadcastPage />}
      {tab === "inbox" && <InboxPage />}
      {tab === "releases" && <ReleasesPage />}
      {tab === "portfolio" && <PortfolioPage />}
      {tab === "news" && <NewsPage />}
      {tab === "dashboard" && <DashboardPage />}
      <Chatbot />
    </>
  );
}
