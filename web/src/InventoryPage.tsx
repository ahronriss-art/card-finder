import { useEffect, useRef, useState } from "react";
import {
  checkShopPassword, getShopsPassword, clearShopsPassword,
  getInventory, createInventory, updateInventory, deleteInventory,
  type InventoryItem, type InventoryInput, type InventoryTotals,
} from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";

const money = (n?: number | null) =>
  n == null ? "—" : `${n < 0 ? "-" : ""}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

const SORTS: { key: string; label: string }[] = [
  { key: "purchase_date", label: "Purchase date" },
  { key: "sold_date", label: "Sold date" },
  { key: "profit", label: "Profit" },
  { key: "bought_by", label: "Bought by" },
  { key: "sold", label: "Sold" },
  { key: "player", label: "Player" },
  { key: "cost", label: "Cost" },
];

const EMPTY: Partial<InventoryInput> = {
  image: null, sport: "", player: "", card_set: "", grade: "", cost: null,
  bought_by: "", purchase_date: "", sold: false, sale_price: null, sold_date: "", notes: "",
};

function ItemForm({ initial, onSave, onCancel }: {
  initial: Partial<InventoryInput>; onSave: (b: Partial<InventoryInput>) => Promise<void>; onCancel: () => void;
}) {
  const [f, setF] = useState<Partial<InventoryInput>>(initial);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const set = (k: keyof InventoryInput, v: any) => setF(p => ({ ...p, [k]: v }));

  function pickImage(file?: File) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => set("image", reader.result as string);
    reader.readAsDataURL(file);
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await onSave({
        ...f,
        cost: f.cost === ("" as any) ? null : f.cost,
        sale_price: f.sale_price === ("" as any) ? null : f.sale_price,
      });
    } finally { setSaving(false); }
  }

  const inp: React.CSSProperties = { padding: "8px 10px", borderRadius: 8, border: "1px solid #cbd5e1", background: "#fff", color: "#0f172a", fontSize: 14, width: "100%" };
  const lbl: React.CSSProperties = { fontSize: 11, fontWeight: 700, color: "#64748b", marginBottom: 3, display: "block" };
  const field = (label: string, node: React.ReactNode) => (<div><span style={lbl}>{label}</span>{node}</div>);

  return (
    <form onSubmit={submit} style={{ background: "#211d3f", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 12, padding: 16 }}>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        {/* image */}
        <div style={{ width: 130 }}>
          <span style={lbl}>Card image</span>
          <div onClick={() => fileRef.current?.click()}
            style={{ width: 130, height: 170, borderRadius: 10, border: "1px dashed #64748b", background: "#0f172a",
              display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", overflow: "hidden" }}>
            {f.image ? <img src={f.image} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              : <span style={{ color: "#64748b", fontSize: 12, textAlign: "center" }}>Tap to upload</span>}
          </div>
          {f.image && <button type="button" onClick={() => set("image", null)} style={{ fontSize: 11, color: "#94a3b8", background: "none", border: "none", cursor: "pointer", marginTop: 4 }}>Remove</button>}
          <input ref={fileRef} type="file" accept="image/*" style={{ display: "none" }} onChange={e => pickImage(e.target.files?.[0])} />
        </div>
        {/* fields */}
        <div style={{ flex: 1, minWidth: 260, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          {field("Player", <input style={inp} value={f.player || ""} onChange={e => set("player", e.target.value)} placeholder="e.g. Victor Wembanyama" />)}
          {field("Sport", <input style={inp} value={f.sport || ""} onChange={e => set("sport", e.target.value)} placeholder="Basketball" />)}
          {field("Set", <input style={inp} value={f.card_set || ""} onChange={e => set("card_set", e.target.value)} placeholder="2023 Prizm" />)}
          {field("Grade", <input style={inp} value={f.grade || ""} onChange={e => set("grade", e.target.value)} placeholder="PSA 10 / Raw" />)}
          {field("Cost ($)", <input style={inp} type="number" step="0.01" value={f.cost ?? ""} onChange={e => set("cost", e.target.value === "" ? null : parseFloat(e.target.value))} />)}
          {field("Bought by", <input style={inp} value={f.bought_by || ""} onChange={e => set("bought_by", e.target.value)} placeholder="Teammate" />)}
          {field("Purchase date", <input style={inp} type="date" value={f.purchase_date || ""} onChange={e => set("purchase_date", e.target.value)} />)}
          {field("Sold?", (
            <label style={{ display: "flex", alignItems: "center", gap: 8, color: "#e2e8f0", fontSize: 14, height: 38 }}>
              <input type="checkbox" checked={!!f.sold} onChange={e => set("sold", e.target.checked)} /> Marked sold
            </label>
          ))}
          {f.sold && field("Sale price ($)", <input style={inp} type="number" step="0.01" value={f.sale_price ?? ""} onChange={e => set("sale_price", e.target.value === "" ? null : parseFloat(e.target.value))} />)}
          {f.sold && field("Sold date", <input style={inp} type="date" value={f.sold_date || ""} onChange={e => set("sold_date", e.target.value)} />)}
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button className="btn btn-sm" type="submit" disabled={saving}>{saving ? "Saving…" : "Save card"}</button>
        <button type="button" onClick={onCancel} style={{ fontSize: 13, color: "#94a3b8", background: "none", border: "1px solid rgba(255,255,255,0.15)", borderRadius: 8, padding: "4px 12px", cursor: "pointer" }}>Cancel</button>
      </div>
    </form>
  );
}

function Board() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [totals, setTotals] = useState<InventoryTotals | null>(null);
  const [sort, setSort] = useState("purchase_date");
  const [desc, setDesc] = useState(true);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);

  async function load() {
    setLoading(true);
    try { const r = await getInventory(sort, desc); setItems(r.items); setTotals(r.totals); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [sort, desc]);

  async function save(id: number | null, body: Partial<InventoryInput>) {
    if (id == null) await createInventory(body); else await updateInventory(id, body);
    setAdding(false); setEditing(null); await load();
  }
  async function remove(id: number) {
    if (!confirm("Delete this card from inventory?")) return;
    await deleteInventory(id); await load();
  }

  const totalCard = (label: string, val: string, color?: string) => (
    <div style={{ flex: "1 1 120px", minWidth: 110, background: "#fff", color: "#0f172a", border: "1px solid #e2e8f0", borderRadius: 12, padding: "10px 14px" }}>
      <div style={{ fontSize: 11, color: "#64748b", fontWeight: 700 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 800, color: color || "#0f172a" }}>{val}</div>
    </div>
  );

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60, maxWidth: 1000 }}>
      <h1>Inventory</h1>
      <p className="subtitle">Track every card you buy and sell — cost, who bought it, dates, and profit.</p>

      {totals && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 14 }}>
          {totalCard("In stock", String(totals.in_stock))}
          {totalCard("Sold", String(totals.sold_count))}
          {totalCard("Cost basis", money(totals.total_cost))}
          {totalCard("Total sales", money(totals.total_sales))}
          {totalCard("Profit", money(totals.total_profit), totals.total_profit >= 0 ? "#16a34a" : "#dc2626")}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
        {!adding && editing == null && <button className="btn btn-sm" onClick={() => setAdding(true)}>+ Add card</button>}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: "#94a3b8" }}>Sort:</span>
        <select value={sort} onChange={e => setSort(e.target.value)}
          style={{ padding: "6px 8px", borderRadius: 8, border: "1px solid #cbd5e1", background: "#fff", color: "#0f172a", fontSize: 13 }}>
          {SORTS.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
        </select>
        <button onClick={() => setDesc(d => !d)}
          style={{ fontSize: 13, color: "#e2e8f0", background: "none", border: "1px solid rgba(255,255,255,0.2)", borderRadius: 8, padding: "5px 10px", cursor: "pointer" }}>
          {desc ? "↓ Desc" : "↑ Asc"}
        </button>
      </div>

      {adding && <div style={{ marginTop: 14 }}><ItemForm initial={EMPTY} onSave={b => save(null, b)} onCancel={() => setAdding(false)} /></div>}

      {loading ? <p className="subtitle" style={{ marginTop: 20 }}>Loading…</p> : (
        <div style={{ marginTop: 16, overflowX: "auto", border: "1px solid #e2e8f0", borderRadius: 12 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, background: "#fff", color: "#0f172a" }}>
            <thead>
              <tr style={{ background: "#f1f5f9", textAlign: "left" }}>
                {["", "Card", "Grade", "Cost", "Bought by", "Purchased", "Sold", "Sale", "Sold date", "Profit", ""].map((h, i) =>
                  <th key={i} style={{ padding: "8px 10px", whiteSpace: "nowrap" }}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && <tr><td colSpan={11} style={{ padding: 20, textAlign: "center", color: "#64748b" }}>No cards yet — add your first above.</td></tr>}
              {items.map(it => editing === it.id ? (
                <tr key={it.id}><td colSpan={11} style={{ padding: 12 }}>
                  <ItemForm initial={it} onSave={b => save(it.id, b)} onCancel={() => setEditing(null)} />
                </td></tr>
              ) : (
                <tr key={it.id} style={{ borderTop: "1px solid #e2e8f0" }}>
                  <td style={{ padding: "6px 10px" }}>
                    {it.image ? <img src={it.image} alt="" style={{ width: 34, height: 46, objectFit: "cover", borderRadius: 4 }} /> : <div style={{ width: 34, height: 46, borderRadius: 4, background: "#e2e8f0" }} />}
                  </td>
                  <td style={{ padding: "6px 10px" }}>
                    <div style={{ fontWeight: 700 }}>{it.player || "—"}</div>
                    <div style={{ fontSize: 11, color: "#64748b" }}>{[it.card_set, it.sport].filter(Boolean).join(" · ") || ""}</div>
                  </td>
                  <td style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>{it.grade || "—"}</td>
                  <td style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>{money(it.cost)}</td>
                  <td style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>{it.bought_by || "—"}</td>
                  <td style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>{it.purchase_date || "—"}</td>
                  <td style={{ padding: "6px 10px" }}>
                    {it.sold ? <span style={{ color: "#16a34a", fontWeight: 700 }}>Sold</span> : <span style={{ color: "#64748b" }}>In stock</span>}
                  </td>
                  <td style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>{it.sold ? money(it.sale_price) : "—"}</td>
                  <td style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>{it.sold_date || "—"}</td>
                  <td style={{ padding: "6px 10px", whiteSpace: "nowrap", fontWeight: 800, color: it.profit == null ? "#64748b" : it.profit >= 0 ? "#16a34a" : "#dc2626" }}>
                    {it.profit == null ? "—" : money(it.profit)}
                  </td>
                  <td style={{ padding: "6px 10px", whiteSpace: "nowrap" }}>
                    <button onClick={() => { setAdding(false); setEditing(it.id); }} style={{ fontSize: 12, color: "#2563eb", background: "none", border: "none", cursor: "pointer" }}>Edit</button>
                    <button onClick={() => remove(it.id)} style={{ fontSize: 12, color: "#dc2626", background: "none", border: "none", cursor: "pointer" }}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function InventoryPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    const stored = getShopsPassword();
    if (!stored) { setChecking(false); return; }
    setUnlocked(true); setChecking(false);
    checkShopPassword(stored).catch((err) => {
      if (err?.response?.status === 401) { clearShopsPassword(); setUnlocked(false); }
    });
  }, []);
  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;
  if (!unlocked) return <ShopPasswordForm title="Inventory" onUnlocked={() => setUnlocked(true)} />;
  return <Board />;
}
