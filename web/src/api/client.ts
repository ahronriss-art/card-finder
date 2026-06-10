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

export async function saveSearch(userId: number, query: string, sport?: string, intervalMinutes = 15, alertMethod = "both", minPrice?: number, maxPrice?: number) {
  const { data } = await api.post("/saved-searches", { user_id: userId, query, sport, check_interval_minutes: intervalMinutes, alert_method: alertMethod, min_price: minPrice, max_price: maxPrice });
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

export async function aiUpdateShop(id: number, text: string) {
  const { data } = await api.post(`/shops/${id}/ai-update`, { text }, shopHeaders());
  return data as { shop: Shop; changed: Record<string, { from: any; to: any }>; summary: string };
}
