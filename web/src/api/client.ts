import axios from "axios";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const api = axios.create({ baseURL: API_BASE, timeout: 15000 });

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

export async function updateUser(userId: number, email?: string, phone?: string, alertMethod = "email") {
  const { data } = await api.put(`/users/${userId}`, { email, phone, alert_method: alertMethod });
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
  catchMisspellings?: boolean;  // ebay: also sweep misspelled variants
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

export async function deleteSearch(searchId: number) {
  const { data } = await api.delete(`/saved-searches/${searchId}`);
  return data;
}

export async function searchMisspellings(query: string, sport?: string) {
  const { data } = await api.post("/search-misspellings", { query, sport });
  return data;
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

function shopHeaders() {
  return { headers: { "X-Shops-Password": localStorage.getItem("shopsPassword") || "" } };
}

export async function checkShopPassword(password: string) {
  await api.post("/shops/check-password", {}, { headers: { "X-Shops-Password": password } });
  return true;
}

export async function listShops(params: {
  q?: string; state?: string; city?: string; contacted?: string; shop_type?: string;
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
