import { useState } from "react";
import SearchPage from "./SearchPage";
import AlertsPage from "./AlertsPage";
import Chatbot from "./Chatbot";
import "./index.css";

export default function App() {
  const [tab, setTab] = useState<"search" | "alerts">("search");

  return (
    <>
      <nav>
        <div className="nav-inner">
          <span className="nav-logo" onClick={() => setTab("search")}>Card Finder</span>
          <button className={`nav-tab${tab === "search" ? " active" : ""}`} onClick={() => setTab("search")}>Search</button>
          <button className={`nav-tab${tab === "alerts" ? " active" : ""}`} onClick={() => setTab("alerts")}>Alerts</button>
        </div>
      </nav>
      {tab === "search" ? <SearchPage /> : <AlertsPage />}
      <Chatbot />
    </>
  );
}
