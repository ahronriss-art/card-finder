import React, { useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, FlatList,
  ActivityIndicator, StyleSheet, Linking, ScrollView
} from "react-native";
import { searchCards } from "../api/client";

const SPORTS = ["All", "NBA", "NFL", "MLB", "NHL", "Pokemon", "UFC", "Soccer"];

const VERDICT_COLORS: Record<string, string> = {
  great_deal: "#16a34a",
  good_deal: "#65a30d",
  fair: "#ca8a04",
  overpriced: "#dc2626",
  unknown: "#6b7280",
};

const VERDICT_LABELS: Record<string, string> = {
  great_deal: "GREAT DEAL",
  good_deal: "Good Deal",
  fair: "Fair Price",
  overpriced: "Overpriced",
  unknown: "No Data",
};

export default function SearchScreen() {
  const [query, setQuery] = useState("");
  const [sport, setSport] = useState("All");
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSearch() {
    if (!query.trim()) return;
    setLoading(true);
    setError("");
    try {
      const data = await searchCards(query, sport === "All" ? undefined : sport);
      setResults(data.listings || []);
    } catch {
      setError("Search failed. Make sure the backend is running.");
    } finally {
      setLoading(false);
    }
  }

  function openListing(url: string) {
    if (url && url !== "https://ebay.com") {
      Linking.openURL(url);
    }
  }

  const header = (
    <View>
      <Text style={styles.title}>Card Finder</Text>
      <TextInput
        style={styles.input}
        placeholder="Search cards (e.g. LeBron James 2003 Rookie)"
        value={query}
        onChangeText={setQuery}
        onSubmitEditing={handleSearch}
        returnKeyType="search"
      />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.sportsRow} keyboardShouldPersistTaps="always">
        {SPORTS.map(s => (
          <TouchableOpacity
            key={s}
            style={[styles.sportChip, sport === s && styles.sportChipActive]}
            onPress={() => setSport(s)}
          >
            <Text style={[styles.sportChipText, sport === s && styles.sportChipTextActive]}>{s}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>
      <TouchableOpacity style={styles.searchBtn} onPress={handleSearch}>
        <Text style={styles.searchBtnText}>Search</Text>
      </TouchableOpacity>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      {loading ? <ActivityIndicator size="large" color="#2563eb" style={{ marginVertical: 24 }} /> : null}
      {results.length > 0 && (
        <Text style={styles.resultsCount}>{results.length} listings found</Text>
      )}
    </View>
  );

  return (
    <View style={styles.container}>
      <FlatList
        data={results}
        keyExtractor={(item, i) => item.external_id || String(i)}
        ListHeaderComponent={header}
        keyboardShouldPersistTaps="always"
        keyboardDismissMode="on-drag"
        renderItem={({ item }) => {
          const verdict = item.analysis?.verdict || "unknown";
          const avg = item.analysis?.avg_sold_price;
          const recentSold = item.analysis?.most_recent_sold;
          const recentDate = item.analysis?.most_recent_date;
          const pct = item.analysis?.pct_vs_market;
          const hasRealUrl = item.listing_url && item.listing_url !== "https://ebay.com";

          return (
            <View style={styles.card}>
              <View style={styles.cardHeader}>
                <Text style={styles.cardTitle} numberOfLines={2}>{item.title}</Text>
                <View style={[styles.verdictBadge, { backgroundColor: VERDICT_COLORS[verdict] }]}>
                  <Text style={styles.verdictText}>{VERDICT_LABELS[verdict]}</Text>
                </View>
              </View>

              <Text style={styles.price}>${item.price?.toFixed(2)}</Text>

              <View style={styles.priceRow}>
                {recentSold ? (
                  <View style={styles.priceBox}>
                    <Text style={styles.priceBoxLabel}>Last Sold</Text>
                    <Text style={styles.priceBoxValue}>${recentSold.toFixed(2)}</Text>
                    {recentDate ? <Text style={styles.priceBoxDate}>{recentDate}</Text> : null}
                  </View>
                ) : null}
                {avg ? (
                  <View style={styles.priceBox}>
                    <Text style={styles.priceBoxLabel}>Avg Sold</Text>
                    <Text style={styles.priceBoxValue}>${avg}</Text>
                    {pct !== undefined ? (
                      <Text style={[styles.pct, { color: pct <= 0 ? "#16a34a" : "#dc2626" }]}>
                        {pct > 0 ? "+" : ""}{pct}% vs market
                      </Text>
                    ) : null}
                  </View>
                ) : null}
              </View>

              {item.analysis?.summary ? (
                <Text style={styles.summary}>{item.analysis.summary}</Text>
              ) : null}

              <View style={styles.cardFooter}>
                <Text style={styles.source}>{item.source?.toUpperCase()} · {item.seller_name || "Unknown seller"}</Text>
                <TouchableOpacity
                  onPress={() => openListing(item.listing_url)}
                  style={[styles.viewBtn, !hasRealUrl && styles.viewBtnDisabled]}
                  disabled={!hasRealUrl}
                >
                  <Text style={[styles.viewBtnText, !hasRealUrl && styles.viewBtnTextDisabled]}>
                    {hasRealUrl ? "View on eBay →" : "Pending eBay key"}
                  </Text>
                </TouchableOpacity>
              </View>
            </View>
          );
        }}
        contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 32, paddingTop: 56 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc" },
  title: { fontSize: 28, fontWeight: "800", color: "#1e3a8a", marginBottom: 16 },
  input: {
    backgroundColor: "#fff", borderRadius: 12, padding: 14,
    fontSize: 15, borderWidth: 1, borderColor: "#e2e8f0",
    shadowColor: "#000", shadowOpacity: 0.05, shadowRadius: 4, elevation: 2,
  },
  sportsRow: { marginVertical: 12 },
  sportChip: {
    paddingHorizontal: 14, paddingVertical: 7, borderRadius: 20,
    backgroundColor: "#e2e8f0", marginRight: 8,
  },
  sportChipActive: { backgroundColor: "#2563eb" },
  sportChipText: { fontSize: 13, color: "#475569", fontWeight: "600" },
  sportChipTextActive: { color: "#fff" },
  searchBtn: {
    backgroundColor: "#2563eb", borderRadius: 12, padding: 14,
    alignItems: "center", marginBottom: 8,
  },
  searchBtnText: { color: "#fff", fontSize: 16, fontWeight: "700" },
  error: { color: "#dc2626", textAlign: "center", marginVertical: 8 },
  resultsCount: { fontSize: 13, color: "#64748b", marginBottom: 12, marginTop: 4 },
  card: {
    backgroundColor: "#fff", borderRadius: 16, padding: 16,
    marginBottom: 12, borderWidth: 1, borderColor: "#e2e8f0",
    shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 6, elevation: 3,
  },
  cardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 },
  cardTitle: { flex: 1, fontSize: 14, fontWeight: "600", color: "#1e293b", marginRight: 8 },
  verdictBadge: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  verdictText: { color: "#fff", fontSize: 11, fontWeight: "800" },
  price: { fontSize: 26, fontWeight: "800", color: "#1e293b", marginBottom: 10 },
  priceRow: { flexDirection: "row", gap: 10, marginBottom: 8 },
  priceBox: {
    flex: 1, backgroundColor: "#f1f5f9", borderRadius: 10,
    padding: 10,
  },
  priceBoxLabel: { fontSize: 11, color: "#64748b", fontWeight: "600", marginBottom: 2 },
  priceBoxValue: { fontSize: 16, fontWeight: "800", color: "#1e293b" },
  priceBoxDate: { fontSize: 11, color: "#94a3b8", marginTop: 2 },
  pct: { fontSize: 11, fontWeight: "700", marginTop: 2 },
  summary: { fontSize: 13, color: "#475569", marginTop: 4, lineHeight: 18 },
  cardFooter: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 12 },
  source: { fontSize: 12, color: "#94a3b8", flex: 1 },
  viewBtn: {
    backgroundColor: "#2563eb", borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 6,
  },
  viewBtnDisabled: { backgroundColor: "#e2e8f0" },
  viewBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  viewBtnTextDisabled: { color: "#94a3b8" },
});
