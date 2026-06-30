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
export async function signup(email: string, password: string) {
  const { data } = await api.post("/auth/signup", { email, password });
  return data as { token: string; user: any };
}

export async function login(email: string, password: string) {
  const { data } = await api.post("/auth/login", { email, password });
  return data as { token: string; user: any };
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
  extraEmails?: string, extraPhones?: string,
) {
  const { data } = await api.put(`/users/${userId}`, {
    email, phone, alert_method: alertMethod,
    extra_emails: extraEmails ?? "", extra_phones: extraPhones ?? "",
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
export async function getBroadcastGroup(id: number) {
  const { data } = await api.get(`/broadcast/groups/${id}`, shopHeaders());
  return data as { id: number; name: string; contacts: { id: number; phone: string; name?: string | null }[] };
}
export async function createBroadcastGroup(name: string, recipients: string) {
  const { data } = await api.post("/broadcast/groups", { name, recipients }, shopHeaders());
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

export type Assignee = { name?: string; phone: string };
export async function sendBroadcast(recipients: string, message: string, assignees?: Assignee[], saveAsGroup?: string) {
  const { data } = await api.post(
    "/broadcast",
    { recipients, message, assignees: assignees && assignees.length ? assignees : null, save_as_group: saveAsGroup || null },
    { ...shopHeaders(), timeout: 120000 },
  );
  return data as BroadcastResult;
}

// --- Inbox: shared team SMS conversations on the 877 line ---
export type SmsConversation = {
  phone: string; name?: string | null; assigned_to?: string | null; assignee_phone?: string | null;
  assignees?: { name?: string | null; phone: string }[];
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
