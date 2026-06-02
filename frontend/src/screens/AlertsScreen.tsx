import React, { useState, useEffect } from "react";
import {
  View, Text, TextInput, TouchableOpacity, FlatList,
  StyleSheet, Alert
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { createUser, saveSearch, getSavedSearches, deleteSearch } from "../api/client";

export default function AlertsScreen() {
  const [userId, setUserId] = useState<number | null>(null);
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [alertMethod, setAlertMethod] = useState<"email" | "sms" | "both">("email");
  const [searches, setSearches] = useState<any[]>([]);
  const [newQuery, setNewQuery] = useState("");
  const [onboarded, setOnboarded] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem("userId").then(id => {
      if (id) {
        setUserId(Number(id));
        setOnboarded(true);
        loadSearches(Number(id));
      }
    });
  }, []);

  async function loadSearches(id: number) {
    try {
      const data = await getSavedSearches(id);
      setSearches(data);
    } catch {}
  }

  async function handleOnboard() {
    if (!email && !phone) {
      Alert.alert("Required", "Please enter an email or phone number.");
      return;
    }
    try {
      const user = await createUser(email || undefined, phone || undefined, alertMethod);
      await AsyncStorage.setItem("userId", String(user.id));
      setUserId(user.id);
      setOnboarded(true);
    } catch {
      Alert.alert("Error", "Could not create account. Check your connection.");
    }
  }

  async function handleAddSearch() {
    if (!newQuery.trim() || !userId) return;
    try {
      await saveSearch(userId, newQuery.trim());
      setNewQuery("");
      loadSearches(userId);
    } catch {
      Alert.alert("Error", "Could not save search.");
    }
  }

  async function handleDelete(id: number) {
    await deleteSearch(id);
    setSearches(prev => prev.filter(s => s.id !== id));
  }

  if (!onboarded) {
    return (
      <View style={styles.container}>
        <Text style={styles.title}>Set Up Alerts</Text>
        <Text style={styles.subtitle}>Get notified when a card you're watching is listed or sold.</Text>

        <Text style={styles.label}>Email</Text>
        <TextInput
          style={styles.input} placeholder="you@email.com"
          value={email} onChangeText={setEmail}
          keyboardType="email-address" autoCapitalize="none"
        />

        <Text style={styles.label}>Phone (for SMS)</Text>
        <TextInput
          style={styles.input} placeholder="+1 555-555-5555"
          value={phone} onChangeText={setPhone}
          keyboardType="phone-pad"
        />

        <Text style={styles.label}>Alert method</Text>
        <View style={styles.methodRow}>
          {(["email", "sms", "both"] as const).map(m => (
            <TouchableOpacity
              key={m}
              style={[styles.methodChip, alertMethod === m && styles.methodChipActive]}
              onPress={() => setAlertMethod(m)}
            >
              <Text style={[styles.methodText, alertMethod === m && styles.methodTextActive]}>
                {m.toUpperCase()}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        <TouchableOpacity style={styles.btn} onPress={handleOnboard}>
          <Text style={styles.btnText}>Save & Enable Alerts</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>My Alerts</Text>
      <Text style={styles.subtitle}>You'll be notified when new cards matching these searches are listed.</Text>

      <View style={styles.addRow}>
        <TextInput
          style={[styles.input, { flex: 1, marginRight: 8 }]}
          placeholder="Add a card to watch..."
          value={newQuery}
          onChangeText={setNewQuery}
        />
        <TouchableOpacity style={styles.addBtn} onPress={handleAddSearch}>
          <Text style={styles.addBtnText}>+ Add</Text>
        </TouchableOpacity>
      </View>

      <FlatList
        data={searches}
        keyExtractor={item => String(item.id)}
        renderItem={({ item }) => (
          <View style={styles.searchItem}>
            <View>
              <Text style={styles.searchQuery}>{item.query}</Text>
              {item.sport ? <Text style={styles.searchMeta}>{item.sport}</Text> : null}
            </View>
            <TouchableOpacity onPress={() => handleDelete(item.id)}>
              <Text style={styles.deleteBtn}>Remove</Text>
            </TouchableOpacity>
          </View>
        )}
        ListEmptyComponent={<Text style={styles.empty}>No saved searches yet.</Text>}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f8fafc", padding: 16, paddingTop: 56 },
  title: { fontSize: 28, fontWeight: "800", color: "#1e3a8a", marginBottom: 8 },
  subtitle: { fontSize: 14, color: "#64748b", marginBottom: 24 },
  label: { fontSize: 13, fontWeight: "600", color: "#374151", marginBottom: 4 },
  input: {
    backgroundColor: "#fff", borderRadius: 12, padding: 14,
    fontSize: 15, borderWidth: 1, borderColor: "#e2e8f0", marginBottom: 12,
  },
  methodRow: { flexDirection: "row", gap: 8, marginBottom: 24 },
  methodChip: {
    flex: 1, paddingVertical: 10, borderRadius: 10,
    backgroundColor: "#e2e8f0", alignItems: "center",
  },
  methodChipActive: { backgroundColor: "#2563eb" },
  methodText: { fontWeight: "700", color: "#475569" },
  methodTextActive: { color: "#fff" },
  btn: {
    backgroundColor: "#2563eb", borderRadius: 12, padding: 14, alignItems: "center",
  },
  btnText: { color: "#fff", fontSize: 16, fontWeight: "700" },
  addRow: { flexDirection: "row", alignItems: "center", marginBottom: 16 },
  addBtn: {
    backgroundColor: "#2563eb", borderRadius: 10, padding: 14, alignItems: "center",
  },
  addBtnText: { color: "#fff", fontWeight: "700" },
  searchItem: {
    backgroundColor: "#fff", borderRadius: 12, padding: 14,
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    marginBottom: 8, borderWidth: 1, borderColor: "#e2e8f0",
  },
  searchQuery: { fontSize: 15, fontWeight: "600", color: "#1e293b" },
  searchMeta: { fontSize: 12, color: "#94a3b8", marginTop: 2 },
  deleteBtn: { color: "#dc2626", fontWeight: "600", fontSize: 13 },
  empty: { textAlign: "center", color: "#94a3b8", marginTop: 32 },
});
