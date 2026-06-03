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

export async function saveSearch(userId: number, query: string, sport?: string) {
  const { data } = await api.post("/saved-searches", { user_id: userId, query, sport });
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
