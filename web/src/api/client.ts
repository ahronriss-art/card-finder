import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const api = axios.create({ baseURL: API_BASE, timeout: 15000 });

// Attach the saved session token (set at login) to every request.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("authToken");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// --- Email + password login ---
// Auth calls get a longer timeout: the backend can be asleep (free tier) and take
// 30s+ to wake on the first request. The default 15s cutoff was making sign-in and
// "Email me a reset code" fail with a false error while the server was booting.
const AUTH_TIMEOUT = { timeout: 45000 };

export async function signup(email: string, password: string) {
  const { data } = await api.post("/auth/signup", { email, password }, AUTH_TIMEOUT);
  return data as { token: string; user: any };
}

export async function login(email: string, password: string) {
  const { data } = await api.post("/auth/login", { email, password }, AUTH_TIMEOUT);
  return data as { token: string; user: any };
}

export async function requestPasswordReset(email: string) {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const { data } = await api.post("/auth/request-reset", { email, origin }, AUTH_TIMEOUT);
  return data as { ok: boolean; message: string };
}

export async function resetPassword(email: string, code: string, password: string) {
  const { data } = await api.post("/auth/reset-password", { email, code, password }, AUTH_TIMEOUT);
  return data as { token: string; user: any };
}

export async function changePassword(newPassword: string) {
  const { data } = await api.post("/auth/change-password", { new_password: newPassword }, AUTH_TIMEOUT);
  return data as { ok: boolean };
}

export async function authMe() {
  const { data } = await api.get("/auth/me");
  return data;
}

export async function authLogout() {
  try { await api.post("/auth/logout"); } catch {}
}

export async function searchCards(query: string, sport?: string, minPrice?: number, maxPrice?: number) {
  const { data } = await api.post("/search", { query, sport, min_price: minPrice, max_price: maxPrice });
  return data;
}

export async function getSoldHistory(query: string, sport?: string) {
  const { data } = await api.get("/sold-history", { params: { query, sport } });
  return data;
}

export async function createUser(email?: string, phone?: string, alertMethod = "email") {
  const { data } = await api.post("/users", { email, phone, alert_method: alertMethod });
  return data;
}

export async function updateUser(
  userId: number, email?: string, phone?: string, alertMethod = "email",
  extraEmails?: string, extraPhones?: string, digest?: boolean,
) {
  const { data } = await api.put(`/users/${userId}`, {
    email, phone, alert_method: alertMethod,
    extra_emails: extraEmails ?? "", extra_phones: extraPhones ?? "",
    ...(digest !== undefined ? { digest } : {}),
  });
  return data;
}

export type SavedSearchPayload = {
  query: string;
  sport?: string;
  intervalMinutes?: number;
  alertMethod?: string;
  minPrice?: number;
  maxPrice?: number;
  numberedTo?: number;
  brand?: string;
  insertType?: string;
  cardNumber?: string;
  year?: string;
  exclude?: string;
  source?: string;          // "ebay" listings or "auction" (Goldin live lots)
  drySpellMonths?: number;  // auction: only alert if no sale in N months
  dealThresholdPct?: number;    // ebay: only alert if >= N% below market
  folder?: string;              // optional group name
  includeAuctions?: boolean;    // also watch eBay auctions (off by default)
  catchMisspellings?: boolean;  // also match common seller misspellings
};

function savedSearchBody(p: SavedSearchPayload) {
  return {
    query: p.query, sport: p.sport,
    check_interval_minutes: p.intervalMinutes ?? 15,
    alert_method: p.alertMethod ?? "both",
    min_price: p.minPrice, max_price: p.maxPrice, numbered_to: p.numberedTo,
    brand: p.brand, insert_type: p.insertType, card_number: p.cardNumber,
    year: p.year, exclude: p.exclude,
    source: p.source ?? "ebay", dry_spell_months: p.drySpellMonths,
    deal_threshold_pct: p.dealThresholdPct,
    folder: p.folder,
    include_auctions: p.includeAuctions ?? false,
    catch_misspellings: p.catchMisspellings ?? false,
  };
}

export async function saveSearch(userId: number, p: SavedSearchPayload) {
  const { data } = await api.post("/saved-searches", { user_id: userId, ...savedSearchBody(p) });
  return data;
}

export async function updateSearch(searchId: number, p: SavedSearchPayload) {
  const { data } = await api.put(`/saved-searches/${searchId}`, savedSearchBody(p));
  return data;
}

export async function getSavedSearches(userId: number) {
  const { data } = await api.get(`/saved-searches/${userId}`);
  return data;
}

export async function scanAlertHealth() {
  const { data } = await api.post("/alerts/scan-health", {}, { timeout: 120000 });
  return data as { scanned: number; summary: Record<string, number> };
}

export interface AuctionListing {
  external_id: string | null;
  title: string | null;
  price: number | null;
  listing_url: string | null;
  image_url: string | null;
  end_date: string | null;
  alert?: string | null;  // which alert matched (only in the "all" view)
}

export async function getAlertAuctions(searchId: number) {
  const { data } = await api.get("/alert-auctions", { params: { search_id: searchId }, timeout: 30000 });
  return data as AuctionListing[];
}

export async function getAlertAuctionsAll() {
  const { data } = await api.get("/alert-auctions-all", { timeout: 120000 });
  return data as AuctionListing[];
}

export interface CardLookupResult {
  identified: boolean;
  card: any;
  query?: string;
  exact_comps?: boolean;
  pricing?: {
    count: number; market?: number; last_sold?: number | null; low?: number; high?: number;
    recommended_buy?: number; profit_probability?: number; expected_profit?: number; fees_pct?: number;
  } | null;
  pop?: {
    total?: number; psa10?: number; psa9?: number; gem_rate?: number | null;
    grades?: Record<string, number>; this_grade?: string | null; cert?: string | null;
    cert_url?: string | null; label?: string | null;
  } | null;
  comps?: { title: string | null; price: number | null; url: string | null; image_url: string | null }[];
}

// Identify a card from a photo and price it from eBay sold comps.
export async function cardLookup(imageBase64: string, mediaType: string) {
  const { data } = await api.post("/card-lookup", { image: imageBase64, media_type: mediaType }, { timeout: 60000 });
  return data as CardLookupResult;
}

// Same, but from a photo URL (e.g. a recent find) — the server fetches the image.
export async function cardLookupUrl(imageUrl: string) {
  const { data } = await api.post("/card-lookup", { image_url: imageUrl }, { timeout: 60000 });
  return data as CardLookupResult;
}

export interface TrendingCard {
  title: string; watch_count: number; price: number | null; url: string | null; image_url: string | null;
  sport?: string; graded?: boolean; auto?: boolean;
}
export async function getTrendingCards(category = "all") {
  const { data } = await api.get("/trending-cards", { params: { category }, timeout: 40000 });
  return data as { cards: TrendingCard[]; as_of: string };
}

// AI advisor: summarize a looked-up card + buy verdict, and answer follow-ups.
export async function cardChat(context: any, messages: { role: string; content: string }[]) {
  const { data } = await api.post("/card-chat", { context, messages }, { timeout: 45000 });
  return data as { answer: string };
}

// Kick off an on-demand check of all alerts against eBay (sends alerts for new
// finds). Returns immediately; the check runs in the background server-side.
export async function runAlertCheck() {
  const { data } = await api.post("/run-alert-check", {}, { timeout: 30000 });
  return data as { status: string };
}

export interface MatchListing {
  external_id: string | null;
  title: string | null;
  price: number | null;
  listing_url: string | null;
  image_url: string | null;
  is_auction: boolean;
  alert: string | null;
}

export async function getAlertMatchesAll() {
  const { data } = await api.get("/alert-matches-all", { timeout: 120000 });
  return data as MatchListing[];
}

export type DealListing = {
  external_id: string; title: string | null; price: number; market: number;
  pct_below: number; comps: number; listing_url: string | null;
  image_url: string | null; alert: string | null;
};
export async function getDealsFeed() {
  const { data } = await api.get("/deals-feed", { timeout: 120000 });
  return data as DealListing[];
}

// --- Card-world news feed ---
export type NewsItem = {
  title: string; url: string; source: string; published: string | null; category: string;
};
export async function getNews() {
  const { data } = await api.get("/news", { timeout: 30000 });
  return data as { items: NewsItem[]; count: number };
}

// --- Portfolio (cards you own, valued vs eBay sold comps) ---
export type PortfolioCard = {
  id: number; name: string; paid: number | null; qty: number; notes: string | null;
  market_value: number | null; comps: number | null; valued_at: string | null;
};
export async function getPortfolio() {
  const { data } = await api.get("/portfolio");
  return data as PortfolioCard[];
}
export async function addPortfolioCard(p: { name: string; paid?: number; qty?: number; notes?: string }) {
  const { data } = await api.post("/portfolio", p);
  return data as PortfolioCard;
}
export async function updatePortfolioCard(id: number, p: { paid?: number; qty?: number; notes?: string }) {
  const { data } = await api.put(`/portfolio/${id}`, p);
  return data as PortfolioCard;
}
export async function deletePortfolioCard(id: number) {
  const { data } = await api.delete(`/portfolio/${id}`);
  return data;
}
export async function revaluePortfolio() {
  const { data } = await api.post("/portfolio/revalue", {}, { timeout: 120000 });
  return data as { cards: PortfolioCard[]; total_value: number; total_cost: number; total_gain: number };
}

// --- Seller watch (alert when a specific eBay seller lists new items) ---
export type SellerWatch = {
  id: number; seller_name: string; label: string | null;
  alert_method: string; last_checked_at: string | null; url: string;
};
export async function getSellerWatches() {
  const { data } = await api.get("/seller-watches");
  return data as SellerWatch[];
}
export async function addSellerWatch(sellerName: string, label?: string) {
  const { data } = await api.post("/seller-watches", { seller_name: sellerName, label: label || null }, { timeout: 60000 });
  return data as SellerWatch;
}
export async function deleteSellerWatch(id: number) {
  const { data } = await api.delete(`/seller-watches/${id}`);
  return data;
}

export interface WatchedAuctionItem {
  id: number;
  external_id: string;
  title: string | null;
  image_url: string | null;
  listing_url: string | null;
  price: number | null;
  end_date: string | null;
  notified: boolean;
}

export async function listWatchedAuctions() {
  const { data } = await api.get("/watched-auctions");
  return data as WatchedAuctionItem[];
}

export async function watchAuction(a: AuctionListing) {
  await api.post("/watched-auctions", {
    external_id: a.external_id, title: a.title, image_url: a.image_url,
    listing_url: a.listing_url, price: a.price, end_date: a.end_date,
  });
}

export async function unwatchAuction(externalId: string) {
  await api.delete(`/watched-auctions/${encodeURIComponent(externalId)}`);
}

export async function deleteSearch(searchId: number) {
  const { data } = await api.delete(`/saved-searches/${searchId}`);
  return data;
}

export async function setSearchFolder(searchId: number, folder: string | null) {
  const { data } = await api.put(`/saved-searches/${searchId}/folder`, { folder });
  return data;
}

export async function folderAssistant(folder: string, instruction: string) {
  const { data } = await api.post("/saved-searches/folder-assistant", { folder, instruction });
  return data as { summary: string; applied: string[] };
}

export async function getAlertsPaused() {
  const { data } = await api.get("/alerts/pause-state");
  return (data as { paused: boolean }).paused;
}

export async function setAlertsPaused(paused: boolean) {
  const { data } = await api.post("/alerts/pause-state", { paused });
  return (data as { paused: boolean }).paused;
}

export async function searchMisspellings(query: string, sport?: string) {
  const { data } = await api.post("/search-misspellings", { query, sport });
  return data;
}

export type LintResult = {
  status: "ok" | "dead" | "narrow" | "empty" | "error";
  messages: string[];
  suggestions: string[];
  stats: { results?: number; matches?: number; priced?: number; keywords?: string };
};

export async function lintAlert(p: {
  query: string; sport?: string; minPrice?: number; maxPrice?: number; numberedTo?: number;
  brand?: string; insertType?: string; cardNumber?: string; year?: string; exclude?: string;
  includeAuctions?: boolean;
}) {
  const { data } = await api.post("/alerts/lint", {
    query: p.query, sport: p.sport, min_price: p.minPrice, max_price: p.maxPrice,
    numbered_to: p.numberedTo, brand: p.brand, insert_type: p.insertType,
    card_number: p.cardNumber, year: p.year, exclude: p.exclude, include_auctions: p.includeAuctions,
  }, { timeout: 30000 });
  return data as LintResult;
}

export async function sendTestAlert(userId: number) {
  const { data } = await api.post("/test-alert", { user_id: userId });
  return data as { sent: boolean; via: string[] };
}

// --- Pop Watch: track a PSA cert's population, alert when it increases ---

export type PopWatch = {
  id: number;
  cert_number: string;
  label?: string | null;
  grade?: string | null;
  population?: number | null;
  population_higher?: number | null;
  auction_url?: string | null;
  auction_ends_at?: string | null;
  check_interval_minutes?: number;
  alert_method?: string;
  last_checked_at?: string | null;
  cert_url: string;
};

export type PopLookup = {
  cert: string; label?: string | null; subject?: string | null; year?: string | null;
  brand?: string | null; card_number?: string | null; variety?: string | null;
  grade?: string | null; population?: number | null; population_higher?: number | null;
  population_qualifier?: number | null; url: string; valid: boolean;
};

export async function popLookup(cert: string) {
  const { data } = await api.get("/pop-lookup", { params: { cert } });
  return data as PopLookup;
}

export async function createPopWatch(p: {
  userId: number; certNumber: string; auctionUrl?: string;
  auctionEndsAt?: string; intervalMinutes?: number; alertMethod?: string;
}) {
  const { data } = await api.post("/pop-watches", {
    user_id: p.userId, cert_number: p.certNumber,
    auction_url: p.auctionUrl, auction_ends_at: p.auctionEndsAt,
    check_interval_minutes: p.intervalMinutes ?? 60, alert_method: p.alertMethod ?? "both",
  });
  return data as PopWatch;
}

export async function getPopWatches(userId: number) {
  const { data } = await api.get(`/pop-watches/${userId}`);
  return data as PopWatch[];
}

export async function deletePopWatch(watchId: number) {
  const { data } = await api.delete(`/pop-watches/${watchId}`);
  return data;
}

// --- Card Shops (password-gated) ---

export type Shop = {
  id: number;
  name: string;
  website?: string | null;
  phone?: string | null;
  full_address?: string | null;
  city?: string | null;
  state?: string | null;
  rating?: number | null;
  reviews?: number | null;
  email?: string | null;
  instagram?: string | null;
  tiktok?: string | null;
  whatnot?: string | null;
  contact_way?: string | null;
  contacted?: string | null;
  active?: string | null;
  contacted_by?: string | null;
  call_notes?: string | null;
  topps_fanatics?: string | null;
  tcg_account?: string | null;
  buys_wholesale?: string | null;
  willing_to_wholesale?: string | null;
  collectors?: string | null;
  notes?: string | null;
  shop_type?: string | null;
  update_log?: any[];
  updated_at?: string | null;
};

const SHOP_PW_KEY = "shopsPassword";

// Read the saved Shops password from either store (persistent or this-session-only).
export function getShopsPassword(): string {
  return localStorage.getItem(SHOP_PW_KEY) || sessionStorage.getItem(SHOP_PW_KEY) || "";
}

// Save the password. remember=true persists across sessions (localStorage);
// remember=false keeps it only until the browser tab closes (sessionStorage).
export function saveShopsPassword(password: string, remember: boolean) {
  localStorage.removeItem(SHOP_PW_KEY);
  sessionStorage.removeItem(SHOP_PW_KEY);
  (remember ? localStorage : sessionStorage).setItem(SHOP_PW_KEY, password);
}

export function clearShopsPassword() {
  localStorage.removeItem(SHOP_PW_KEY);
  sessionStorage.removeItem(SHOP_PW_KEY);
}

function shopHeaders() {
  return { headers: { "X-Shops-Password": getShopsPassword() } };
}

export async function checkShopPassword(password: string) {
  await api.post("/shops/check-password", {}, { headers: { "X-Shops-Password": password } });
  return true;
}

// --- Caller Notes (shared, gated by the Shops password) ---
export type CallerNote = {
  id: number; caller_name: string; caller_phone?: string | null;
  instagram?: string | null; facebook?: string | null; email?: string | null;
  category?: string | null; buys_wax?: boolean; note: string; created_at: string;
};

export async function setCallerCategory(callerName: string, category: string | null) {
  const { data } = await api.put("/caller-notes/category", { caller_name: callerName, category }, shopHeaders());
  return data as { caller_name: string; category: string | null; updated: number };
}

export async function setCallerBuysWax(callerName: string, buysWax: boolean) {
  const { data } = await api.put("/caller-notes/buys-wax", { caller_name: callerName, buys_wax: buysWax }, shopHeaders());
  return data as { caller_name: string; buys_wax: boolean; updated: number };
}

export type CallerContact = {
  callerPhone?: string; instagram?: string; facebook?: string; email?: string;
};

export interface Find {
  sent_at: string | null;
  title: string | null;
  price: number | null;
  is_auction: boolean;
  pct_vs_market: number | null;
  alert: string | null;
  listing_url: string | null;
  image_url: string | null;
  sport?: string | null;
}

export async function listMyFinds(limit = 200) {
  const { data } = await api.get("/my-finds", { params: { limit } });
  return data as Find[];
}

export interface BroadcastResult {
  sms: { sent: number; failed: number; total: number };
  skipped: string[];
  saved_group?: { id: number; name: string; added: number; total: number } | null;
}

// --- Broadcast groups (reusable saved audiences) ---
export type BroadcastGroup = { id: number; name: string; folder?: string | null; count: number; created_at?: string };
export async function updateBroadcastGroup(id: number, p: { name?: string; folder?: string | null }) {
  const { data } = await api.put(`/broadcast/groups/${id}`, { name: p.name, folder: p.folder ?? "" }, shopHeaders());
  return data as BroadcastGroup;
}
export async function listBroadcastGroups() {
  const { data } = await api.get("/broadcast/groups", shopHeaders());
  return data as BroadcastGroup[];
}
export type BroadcastLogEntry = { message: string; sent_count: number; created_at?: string | null };
export async function getBroadcastGroup(id: number) {
  const { data } = await api.get(`/broadcast/groups/${id}`, shopHeaders());
  return data as {
    id: number; name: string; folder?: string | null;
    contacts: { id: number; phone: string; name?: string | null }[];
    history?: BroadcastLogEntry[];
  };
}
export async function createBroadcastGroup(name: string, recipients: string, folder?: string) {
  const { data } = await api.post("/broadcast/groups", { name, recipients, folder: folder ?? null }, shopHeaders());
  return data as BroadcastGroup;
}
export async function deleteBroadcastGroup(id: number) {
  const { data } = await api.delete(`/broadcast/groups/${id}`, shopHeaders());
  return data;
}
export async function addToBroadcastGroup(id: number, recipients: string) {
  const { data } = await api.post(`/broadcast/groups/${id}/contacts`, { name: "", recipients }, shopHeaders());
  return data as { added: number; total: number };
}
export async function updateBroadcastContact(contactId: number, p: { name?: string; phone?: string }) {
  const { data } = await api.put(`/broadcast/contacts/${contactId}`, p, shopHeaders());
  return data as { id: number; phone: string; name: string | null };
}
export async function deleteBroadcastContact(contactId: number) {
  const { data } = await api.delete(`/broadcast/contacts/${contactId}`, shopHeaders());
  return data;
}

export type Assignee = { name?: string; phone: string };
export async function sendBroadcast(recipients: string, message: string, assignees?: Assignee[], saveAsGroup?: string, image?: string) {
  const { data } = await api.post(
    "/broadcast",
    { recipients, message, assignees: assignees && assignees.length ? assignees : null, save_as_group: saveAsGroup || null, image: image || null },
    { ...shopHeaders(), timeout: 120000 },
  );
  return data as BroadcastResult;
}

// Reusable saved messages (templates)
export type BroadcastTemplate = { id: number; name: string; body: string };
export async function listBroadcastTemplates() {
  const { data } = await api.get("/broadcast/templates", shopHeaders());
  return data as BroadcastTemplate[];
}
export async function saveBroadcastTemplate(name: string, body: string) {
  const { data } = await api.post("/broadcast/templates", { name, body }, shopHeaders());
  return data as BroadcastTemplate;
}
export async function deleteBroadcastTemplate(id: number) {
  const { data } = await api.delete(`/broadcast/templates/${id}`, shopHeaders());
  return data;
}

// Scheduled broadcasts (send later)
export type ScheduledBroadcast = {
  id: number; message: string; has_image: boolean; recipient_count: number;
  save_as_group?: string | null; send_at: string | null; status: string;
  result?: string | null; sent_at?: string | null;
};
export async function listScheduledBroadcasts() {
  const { data } = await api.get("/broadcast/scheduled", shopHeaders());
  return data as ScheduledBroadcast[];
}
export async function scheduleBroadcast(p: {
  recipients: string; message: string; sendAt: string; assignees?: Assignee[];
  saveAsGroup?: string; image?: string;
}) {
  const { data } = await api.post("/broadcast/schedule", {
    recipients: p.recipients, message: p.message, send_at: p.sendAt,
    assignees: p.assignees && p.assignees.length ? p.assignees : null,
    save_as_group: p.saveAsGroup || null, image: p.image || null,
  }, shopHeaders());
  return data as ScheduledBroadcast;
}
export async function cancelScheduledBroadcast(id: number) {
  const { data } = await api.delete(`/broadcast/scheduled/${id}`, shopHeaders());
  return data;
}

export type Dashboard = {
  as_of: string;
  searches: { active: number; total: number };
  alerts: { total: number; last_7d: number };
  broadcasts: { blasts: number; recipients_total: number; last_at: string | null; scheduled_pending: number };
  inbox: { conversations: number; unread: number; replies: number; replies_7d: number; reply_rate_pct: number | null };
  audience: { groups: number; contacts: number; named: number };
  deals: { logged: number; bought: number; sold: number; callers: number };
  portfolio: { cards: number; market_value: number; cost: number; pnl: number };
};
export async function getDashboard() {
  const { data } = await api.get("/dashboard", shopHeaders());
  return data as Dashboard;
}

// --- Inbox: shared team SMS conversations on the 877 line ---
export type SmsConversation = {
  phone: string; name?: string | null; assigned_to?: string | null; assignee_phone?: string | null;
  assignees?: { name?: string | null; phone: string }[];
  contact_type?: string | null; location?: string | null; email?: string | null; notes?: string | null;
  unread: number; last_preview?: string | null; last_direction?: string | null; last_at?: string | null;
};
export type SmsMessage = { id: number; direction: "in" | "out"; body: string; sender?: string | null; created_at: string };

export async function listConversations() {
  const { data } = await api.get("/sms/conversations", shopHeaders());
  return data as SmsConversation[];
}
export async function getConversation(phone: string) {
  const { data } = await api.get("/sms/conversation", { ...shopHeaders(), params: { phone } });
  return data as { conversation: SmsConversation; messages: SmsMessage[] };
}
export async function sendConversationReply(phone: string, body: string, sender?: string) {
  const { data } = await api.post("/sms/conversation/send", { phone, body, sender: sender || null }, { ...shopHeaders(), timeout: 60000 });
  return data;
}
export async function assignConversation(phone: string, p: { assignees?: Assignee[]; name?: string }) {
  const { data } = await api.put("/sms/conversation/assign",
    { phone, assignees: p.assignees && p.assignees.length ? p.assignees : [], name: p.name }, shopHeaders());
  return data as SmsConversation;
}
export async function updateConversationDetails(phone: string, p: {
  name?: string; contact_type?: string; location?: string; email?: string; notes?: string;
}) {
  const { data } = await api.put("/sms/conversation/details", { phone, ...p }, shopHeaders());
  return data as SmsConversation;
}
export async function deleteConversation(phone: string) {
  const { data } = await api.delete("/sms/conversation", { ...shopHeaders(), params: { phone } });
  return data;
}

export async function listCallerNotes() {
  const { data } = await api.get("/caller-notes", shopHeaders());
  return data as CallerNote[];
}

export async function addCallerNote(callerName: string, note: string, contact: CallerContact = {}) {
  const { data } = await api.post("/caller-notes", {
    caller_name: callerName, note,
    caller_phone: contact.callerPhone || null,
    instagram: contact.instagram || null,
    facebook: contact.facebook || null,
    email: contact.email || null,
  }, shopHeaders());
  return data as CallerNote;
}

export async function deleteCallerNote(id: number) {
  const { data } = await api.delete(`/caller-notes/${id}`, shopHeaders());
  return data;
}

export async function updateCallerNote(id: number, note: string) {
  const { data } = await api.put(`/caller-notes/${id}`, { note }, shopHeaders());
  return data as CallerNote;
}

// --- Caller Deals (closed deals per caller) ---
export type CallerDeal = {
  id: number; caller_name: string; description: string;
  amount?: number | null; kind?: "buy" | "sell" | null; created_at: string;
};

export async function listCallerDeals() {
  const { data } = await api.get("/caller-deals", shopHeaders());
  return data as CallerDeal[];
}

export async function addCallerDeal(callerName: string, description: string, amount?: number, kind?: "buy" | "sell") {
  const { data } = await api.post("/caller-deals",
    { caller_name: callerName, description, amount: amount ?? null, kind: kind ?? null }, shopHeaders());
  return data as CallerDeal;
}

export async function deleteCallerDeal(id: number) {
  const { data } = await api.delete(`/caller-deals/${id}`, shopHeaders());
  return data;
}

// --- Tasks (shared team to-do board, gated by the Shops password) ---
export type ChecklistItem = { id: string; text: string; done: boolean };
export type TaskChatMessage = { role: "user" | "assistant"; text: string };
export type Task = {
  id: number; text: string; assigned_to?: string | null; created_by?: string | null;
  done: boolean; created_at: string; completed_at?: string | null;
  checklist?: ChecklistItem[]; chat?: TaskChatMessage[];
};

export async function listTasks() {
  const { data } = await api.get("/tasks", shopHeaders());
  return data as Task[];
}

export async function addTask(text: string, assignedTo?: string, createdBy?: string) {
  const { data } = await api.post("/tasks",
    { text, assigned_to: assignedTo || null, created_by: createdBy || null }, shopHeaders());
  return data as Task;
}

export async function updateTask(id: number, patch: { text?: string; assigned_to?: string | null; done?: boolean; checklist?: ChecklistItem[] }) {
  const { data } = await api.put(`/tasks/${id}`, patch, shopHeaders());
  return data as Task;
}

export async function deleteTask(id: number) {
  const { data } = await api.delete(`/tasks/${id}`, shopHeaders());
  return data;
}

export async function sendTaskChat(id: number, message: string) {
  const { data } = await api.post(`/tasks/${id}/chat`, { message }, { ...shopHeaders(), timeout: 60000 });
  return data as Task;
}


export async function listShops(params: {
  q?: string; state?: string; city?: string; contacted?: string; active?: string; shop_type?: string;
  min_rating?: number; min_reviews?: number;
  has_website?: boolean; has_email?: boolean; has_phone?: boolean; has_instagram?: boolean;
  topps_fanatics?: boolean; willing_to_wholesale?: boolean;
  sort?: string; limit?: number; offset?: number;
}) {
  const { data } = await api.get("/shops", { ...shopHeaders(), params });
  return data as { shops: Shop[]; total: number };
}

export async function getShopStates() {
  const { data } = await api.get("/shops/states", shopHeaders());
  return data as { state: string; count: number }[];
}

export async function createShop(shop: Partial<Shop>) {
  const { data } = await api.post("/shops", shop, shopHeaders());
  return data as Shop;
}

export async function updateShop(id: number, shop: Partial<Shop>) {
  const { data } = await api.put(`/shops/${id}`, shop, shopHeaders());
  return data as Shop;
}

export async function deleteShop(id: number) {
  const { data } = await api.delete(`/shops/${id}`, shopHeaders());
  return data;
}

export async function askShops(question: string) {
  const { data } = await api.post("/shops/ask", { text: question }, shopHeaders());
  return data as { answer: string; filters: Record<string, any>; shops: Shop[]; total: number };
}

export async function syncShopsFromSheet() {
  const { data } = await api.post("/shops/sync-from-sheet", {}, { ...shopHeaders(), timeout: 60000 });
  return data as { checked: number; added: number; updated: number; fields_changed: number; error?: string };
}

export async function getSyncStatus() {
  const { data } = await api.get("/shops/sync-status", shopHeaders());
  return data as { at: string | null; checked?: number; added?: number; updated?: number; fields_changed?: number };
}

export async function getEbayUsage() {
  const { data } = await api.get("/ebay-usage");
  return data as { day: string; calls: number; cap: number; remaining: number };
}

export async function getTwilioBalance() {
  const { data } = await api.get("/twilio-balance");
  return data as { available: boolean; balance?: number; currency?: string };
}

export async function getAlertStatus() {
  const { data } = await api.get("/alert-status");
  return data as {
    active_searches: number; users_with_alerts: number;
    by_method: { email: number; sms: number; both: number; other: number };
    sms_sending: number; email_sending: number; alerts_sent_today: number;
  };
}

export async function setAllAlertsMethod(method: "email" | "sms" | "both") {
  const { data } = await api.post("/alerts/set-all-method", { method });
  return data as { updated: number; method: string };
}

export async function getNextAlertCheck() {
  const { data } = await api.get("/next-alert-check");
  return data as { seconds_remaining: number; interval_s: number; running: boolean };
}

// Saved Pop Report lookups (per-account, synced across devices).
export interface PopLookupRow { id: number; thumb: string; result: CardLookupResult; ts: number; }
export async function getPopLookups() {
  const { data } = await api.get("/pop-lookups");
  return (data.lookups || []) as PopLookupRow[];
}
export async function savePopLookup(thumb: string, result: CardLookupResult) {
  const { data } = await api.post("/pop-lookups", { thumb, result });
  return data as { id: number };
}
export async function deletePopLookup(id: number) {
  await api.delete(`/pop-lookups/${id}`);
}
export async function clearPopLookups() {
  await api.delete("/pop-lookups");
}

export async function aiUpdateShop(id: number, text: string) {
  const { data } = await api.post(`/shops/${id}/ai-update`, { text }, shopHeaders());
  return data as { shop: Shop; changed: Record<string, { from: any; to: any }>; summary: string };
}

// --- Auctions: card sales Q&A (password-gated, reuses the Shops password) ---

export type Sale = {
  source: string;
  auction_house?: string;
  status?: string | null;       // e.g. "live auction" (open bid, not a completed sale)
  title?: string | null;
  sold_price?: number | null;
  sold_at?: string | null;
  bids?: number | null;
  grade?: string | null;
  listing_url?: string | null;
  image_url?: string | null;
  // PSA population data (populated when a PSA source is configured)
  pop_10?: number | null;       // # graded PSA 10
  pop_total?: number | null;    // total graded across all grades
  pop_data?: Record<string, number> | null; // grade -> count
};

export type AuctionSource = { name: string; status: string; count: number; sold?: number | null; live?: number | null };

export type Market = {
  grade: string | null;
  median: number; low: number; high: number; count: number;
  trend_pct: number | null; // % change of recent vs older sales
};
export type TrendPoint = { date: string; price: number };
export type Deal = {
  title?: string | null; price: number; pct: number; score: string;
  grade?: string | null; listing_url?: string | null; image_url?: string | null;
};

// --- Studio: AI image/flyer generation (password-gated, reuses Shops password) ---

export async function generateImage(prompt: string, size: string, quality: string) {
  const { data } = await api.post(
    "/studio/generate",
    { prompt, size, quality, enhance: true },
    { ...shopHeaders(), timeout: 190000 },
  );
  return data as { image: string; prompt_used: string };
}

export async function askAuctions(question: string) {
  const { data } = await api.post("/auctions/ask", { text: question }, { ...shopHeaders(), timeout: 40000 });
  return data as {
    answer: string; card_query: string; sales: Sale[]; sources: AuctionSource[];
    market: Market | null; trend: TrendPoint[]; deals: Deal[];
  };
}

// --- New Releases (AI-parsed checklists → target sheet) ---
export type ReleaseProduct = { id: number; name: string; release_date?: string | null; card_count: number; created_at?: string };
export type ReleaseCard = {
  id: number; player?: string | null; card_number?: string | null; parallel?: string | null;
  numbered_to?: number | null; subset?: string | null; team?: string | null; targeted: boolean;
};
export async function listReleases() {
  const { data } = await api.get("/releases", shopHeaders());
  return data as ReleaseProduct[];
}
export async function createRelease(name: string, releaseDate: string, text: string) {
  const { data } = await api.post("/releases", { name, release_date: releaseDate || null, text }, { ...shopHeaders(), timeout: 120000 });
  return data as { product: ReleaseProduct; cards: Omit<ReleaseCard, "id" | "targeted">[] };
}
export async function autoFetchChecklist(name: string, url: string, releaseDate?: string | null) {
  const { data } = await api.post("/releases/auto-fetch",
    { name, url, release_date: releaseDate || null }, { ...shopHeaders(), timeout: 120000 });
  return data as { product: ReleaseProduct; cards: Omit<ReleaseCard, "id" | "targeted">[] };
}
export async function getRelease(id: number) {
  const { data } = await api.get(`/releases/${id}`, shopHeaders());
  return data as { product: ReleaseProduct; cards: ReleaseCard[] };
}
export async function setCardTargeted(cardId: number, targeted: boolean) {
  const { data } = await api.put(`/releases/card/${cardId}`, { targeted }, shopHeaders());
  return data as ReleaseCard;
}
export async function deleteRelease(id: number) {
  const { data } = await api.delete(`/releases/${id}`, shopHeaders());
  return data;
}
export async function deleteAllReleases() {
  const { data } = await api.delete("/releases", shopHeaders());
  return data;
}

// --- Release calendar (screenshot → product + street date) ---
export type ParsedCalendarRow = {
  product: string; date?: string | null; release_date?: string | null;
  sport?: string | null; brand?: string | null;
};
export type CalendarItem = ParsedCalendarRow & {
  id: number; date_text?: string | null; source_url?: string | null;
  allocated?: boolean; price?: number | null; alloc_qty?: number | null;
  notify_days_before?: number | null; notify_user_id?: number | null; notified_at?: string | null;
};

export async function parseReleaseCalendar(imageDataUrl: string) {
  // Vision can take a while — override the default 15s client timeout.
  const { data } = await api.post("/release-calendar/parse", { image: imageDataUrl }, { ...shopHeaders(), timeout: 90000 });
  return data as { releases: ParsedCalendarRow[]; count: number };
}
export async function saveReleaseCalendar(releases: ParsedCalendarRow[]) {
  const { data } = await api.post("/release-calendar", { releases }, shopHeaders());
  return data as { added: number };
}
export async function getReleaseCalendar() {
  const { data } = await api.get("/release-calendar", shopHeaders());
  return data as CalendarItem[];
}
export async function deleteReleaseCalendarItem(id: number) {
  const { data } = await api.delete(`/release-calendar/${id}`, shopHeaders());
  return data;
}
export async function clearReleaseCalendar() {
  const { data } = await api.delete("/release-calendar", shopHeaders());
  return data;
}
export async function autoImportReleases(notifyUserId?: number | null) {
  const { data } = await api.post("/release-calendar/auto-import",
    { notify_user_id: notifyUserId ?? null }, { ...shopHeaders(), timeout: 60000 });
  return data as { fetched: number; added: number; notify_on: boolean };
}
export type ScraperHealth = { status: "ok" | "degraded" | "down"; detail: string; calendar_count: number; checklist_count: number | null; checked_at?: string };
export async function getReleaseHealth() {
  const { data } = await api.get("/release-calendar/health", shopHeaders());
  return data as ScraperHealth;
}
export async function scanReleaseHealth() {
  const { data } = await api.post("/release-calendar/health", {}, { ...shopHeaders(), timeout: 60000 });
  return data as ScraperHealth;
}
export async function setReleaseWax(id: number, p: { allocated?: boolean; price?: number | null; alloc_qty?: number | null }) {
  const { data } = await api.put(`/release-calendar/${id}/wax`, p, shopHeaders());
  return data as CalendarItem;
}
export async function setReleaseReminder(id: number, userId: number | null, daysBefore: number | null) {
  const { data } = await api.put(`/release-calendar/${id}/notify`, { user_id: userId, days_before: daysBefore }, shopHeaders());
  return data as CalendarItem;
}

// --- Wax Ladder (sold-price history for sealed boxes) ---
export type WaxSale = { title?: string | null; sold_price?: number; sold_at?: string | null; listing_url?: string | null; image_url?: string | null };
export type WaxStats = { count: number; median: number; avg: number; min: number; max: number; last_price: number; last_date?: string | null };
export async function getWaxHistory(query: string) {
  const { data } = await api.get("/wax-history", { ...shopHeaders(), params: { query }, timeout: 40000 });
  return data as { query: string; sold: WaxSale[]; stats: WaxStats | null };
}

export type WaxSnapshot = { day: string; median: number | null; avg: number | null; min: number | null; max: number | null; count: number };
export type TrackedWax = {
  id: number; query: string; box_key: string; points: number; history: WaxSnapshot[];
  latest: number | null; first: number | null; change: number | null; change_pct: number | null;
};
export async function getTrackedWax() {
  const { data } = await api.get("/wax-tracked", { ...shopHeaders() });
  return (data.tracked || []) as TrackedWax[];
}
export async function trackWaxBox(query: string) {
  const { data } = await api.post("/wax-track", null, { ...shopHeaders(), params: { query }, timeout: 40000 });
  return data as { ok: boolean; box_key: string };
}
export async function untrackWaxBox(box_key: string) {
  await api.delete("/wax-track", { ...shopHeaders(), params: { box_key } });
}

export type InventoryStatus = "in_stock" | "listed" | "sold";
export type InventoryItem = {
  id: number; image?: string | null; sport?: string | null; player?: string | null;
  card_set?: string | null; grade?: string | null; cost?: number | null;
  bought_by?: string | null; purchase_date?: string | null;
  status: InventoryStatus; listing_url?: string | null; sold: boolean;
  sale_price?: number | null; fees?: number | null; shipping?: number | null;
  sold_date?: string | null; notes?: string | null;
  profit?: number | null; gross_profit?: number | null; roi?: number | null; days_held?: number | null;
  market_value?: number | null; market_comps?: number | null; valued_at?: string | null; unrealized?: number | null;
};
export type InventoryInput = Omit<InventoryItem, "id" | "profit" | "gross_profit" | "roi" | "days_held" | "sold"
  | "market_value" | "market_comps" | "valued_at" | "unrealized"> & { sold?: boolean };
export type InventoryTotals = {
  count: number; in_stock: number; listed: number; sold_count: number;
  total_cost: number; total_sales: number; total_fees: number; total_profit: number;
  shelf_value: number; unrealized_profit: number; valued_count: number; held_count: number;
};
export async function valueInventory(only_unvalued = false) {
  const { data } = await api.post("/inventory/value", null, { ...shopHeaders(), params: { only_unvalued }, timeout: 120000 });
  return data as { valued: number; skipped: number; targets: number };
}
export type InvGroup = { label: string; count: number; profit: number; roi: number | null };
export type InvFlip = { id: number; player?: string | null; card_set?: string | null; profit: number; roi: number | null; days_held: number | null };
export type InvAging = InvFlip & { days_in_stock: number; status: string; cost?: number | null };
export type InventoryAnalytics = {
  summary: { sold_count: number; total_profit: number; avg_profit: number; avg_days_to_sell: number | null; median_days_to_sell: number | null; held_count: number };
  by_month: { month: string; profit: number }[];
  by_teammate: InvGroup[]; by_sport: InvGroup[];
  best: InvFlip[]; worst: InvFlip[]; aging: InvAging[]; aging_days: number;
};
export async function getInventoryAnalytics() {
  const { data } = await api.get("/inventory/analytics", { ...shopHeaders() });
  return data as InventoryAnalytics;
}
export type GradeRoi = {
  query: string; grade: string; fee: number;
  raw_median: number | null; raw_comps: number;
  graded_median: number | null; graded_comps: number;
  net: number | null; multiplier: number | null; verdict: "grade" | "maybe" | "skip" | null;
};
export async function gradeRoi(query: string, grade = "PSA 10", fee = 25) {
  const { data } = await api.get("/grade-roi", { ...shopHeaders(), params: { query, grade, fee }, timeout: 40000 });
  return data as GradeRoi;
}
export async function getInventory(sort = "purchase_date", desc = true, q = "", status = "") {
  const { data } = await api.get("/inventory", { ...shopHeaders(), params: { sort, desc, q, status } });
  return data as { items: InventoryItem[]; totals: InventoryTotals };
}
export async function createInventory(body: Partial<InventoryInput>) {
  const { data } = await api.post("/inventory", body, { ...shopHeaders() });
  return data as InventoryItem;
}
export async function updateInventory(id: number, body: Partial<InventoryInput>) {
  const { data } = await api.put(`/inventory/${id}`, body, { ...shopHeaders() });
  return data as InventoryItem;
}
export async function deleteInventory(id: number) {
  await api.delete(`/inventory/${id}`, { ...shopHeaders() });
}
export type InventoryAutofill = {
  identified: boolean; confidence?: string;
  fields: Partial<Pick<InventoryItem, "player" | "sport" | "card_set" | "grade" | "notes">>;
};
export async function inventoryAutofill(image: string) {
  const { data } = await api.post("/inventory/autofill", { image }, { ...shopHeaders(), timeout: 50000 });
  return data as InventoryAutofill;
}
