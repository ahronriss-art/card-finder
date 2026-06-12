import { useEffect, useRef, useState } from "react";
import { checkShopPassword, generateImage } from "./api/client";

type Layer = {
  id: number;
  text: string;
  xPct: number;   // top-left, % of image width
  yPct: number;   // top-left, % of image height
  sizePct: number; // font size, % of image height
  color: string;
  bold: boolean;
};

const SIZES = [
  { key: "portrait", label: "Portrait", ratio: "1024 / 1536" },
  { key: "square", label: "Square", ratio: "1 / 1" },
  { key: "landscape", label: "Landscape", ratio: "1536 / 1024" },
];

const IDEAS = [
  "Vintage baseball stadium at golden hour, dramatic clouds, empty space at top",
  "Holographic Pokémon-style background, electric blue and purple, sparkles",
  "Luxury dark display case with spotlights, premium card-shop vibe",
  "Retro 90s basketball court, bold neon shapes, clean center area",
];

type LayerDef = Omit<Layer, "id">;

const PRESETS: { name: string; emoji: string; size: string; prompt: string; layers: LayerDef[] }[] = [
  {
    name: "Buy · Sell · Trade", emoji: "🤝", size: "portrait",
    prompt: "Premium sports card shop interior, glass display cases with spotlights, warm dramatic lighting, clean empty space at the top and bottom for text, photorealistic",
    layers: [
      { text: "BUY · SELL · TRADE", xPct: 7, yPct: 7, sizePct: 11, color: "#ffffff", bold: true },
      { text: "Your Shop Name", xPct: 7, yPct: 78, sizePct: 7, color: "#fde047", bold: true },
      { text: "123 Main St · (555) 555-5555", xPct: 7, yPct: 88, sizePct: 4, color: "#ffffff", bold: false },
    ],
  },
  {
    name: "Card Show", emoji: "🎪", size: "portrait",
    prompt: "Busy sports card convention hall with rows of vendor tables, bright energetic lighting and banners, clean ceiling space at the top for a title, photorealistic",
    layers: [
      { text: "CARD SHOW", xPct: 7, yPct: 7, sizePct: 12, color: "#ffffff", bold: true },
      { text: "Saturday · 10AM–4PM", xPct: 7, yPct: 80, sizePct: 6, color: "#fde047", bold: true },
      { text: "Community Center · Free Entry", xPct: 7, yPct: 89, sizePct: 4, color: "#ffffff", bold: false },
    ],
  },
  {
    name: "Now Open", emoji: "🎉", size: "portrait",
    prompt: "Grand opening of a modern trading card store, ribbon and confetti, bright welcoming storefront, lots of clean open space, photorealistic",
    layers: [
      { text: "NOW OPEN", xPct: 7, yPct: 8, sizePct: 13, color: "#ffffff", bold: true },
      { text: "Grand Opening Weekend", xPct: 7, yPct: 80, sizePct: 6, color: "#fde047", bold: true },
      { text: "Your Shop Name", xPct: 7, yPct: 89, sizePct: 4.5, color: "#ffffff", bold: false },
    ],
  },
  {
    name: "New Inventory", emoji: "📦", size: "square",
    prompt: "Fresh sealed sports card wax boxes and packs, vibrant colors, studio product lighting, dark clean background with space for text, photorealistic",
    layers: [
      { text: "JUST IN", xPct: 7, yPct: 8, sizePct: 13, color: "#ffffff", bold: true },
      { text: "New Inventory Drop", xPct: 7, yPct: 82, sizePct: 6, color: "#fde047", bold: true },
      { text: "@yourhandle", xPct: 7, yPct: 90, sizePct: 4.5, color: "#ffffff", bold: false },
    ],
  },
  {
    name: "Live Breaks", emoji: "📺", size: "portrait",
    prompt: "Exciting live card-breaking studio with neon lights and cameras, packs ready to open, dark stage with glowing accents and clean space, photorealistic",
    layers: [
      { text: "LIVE BREAKS", xPct: 7, yPct: 7, sizePct: 12, color: "#ffffff", bold: true },
      { text: "Tonight · 8PM", xPct: 7, yPct: 80, sizePct: 6, color: "#fde047", bold: true },
      { text: "Watch on Whatnot", xPct: 7, yPct: 89, sizePct: 4.5, color: "#ffffff", bold: false },
    ],
  },
];

export default function StudioPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);
  const [pw, setPw] = useState("");
  const [pwError, setPwError] = useState("");

  const [prompt, setPrompt] = useState("");
  const [size, setSize] = useState("portrait");
  const [quality, setQuality] = useState("medium");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [imageUrl, setImageUrl] = useState<string | null>(null);

  const [layers, setLayers] = useState<Layer[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [starterLayers, setStarterLayers] = useState<LayerDef[]>([]); // queued by a preset until art is generated
  const nextId = useRef(1);
  const wrapRef = useRef<HTMLDivElement>(null);
  const drag = useRef<null | { id: number; sx: number; sy: number; ox: number; oy: number; w: number; h: number }>(null);

  const ratio = SIZES.find(s => s.key === size)?.ratio || "1 / 1";
  const selected = layers.find(l => l.id === selectedId) || null;

  // Same gate as Shops/Auctions — one password unlocks all.
  useEffect(() => {
    const stored = localStorage.getItem("shopsPassword");
    const url = new URL(window.location.href);
    const key = url.searchParams.get("key");
    const candidate = key || stored;
    if (key) { url.searchParams.delete("key"); window.history.replaceState({}, "", url.toString()); }
    if (!candidate) { setChecking(false); return; }
    localStorage.setItem("shopsPassword", candidate);
    setUnlocked(true);
    setChecking(false);
    checkShopPassword(candidate).catch((err) => {
      if (err?.response?.status === 401) { localStorage.removeItem("shopsPassword"); setUnlocked(false); }
    });
  }, []);

  // Drag handling for text layers
  useEffect(() => {
    function move(e: PointerEvent) {
      const d = drag.current;
      if (!d) return;
      const dx = ((e.clientX - d.sx) / d.w) * 100;
      const dy = ((e.clientY - d.sy) / d.h) * 100;
      const x = Math.max(0, Math.min(96, d.ox + dx));
      const y = Math.max(0, Math.min(96, d.oy + dy));
      setLayers(prev => prev.map(l => l.id === d.id ? { ...l, xPct: x, yPct: y } : l));
    }
    function up() { drag.current = null; }
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, []);

  async function submitPw(e: React.FormEvent) {
    e.preventDefault();
    setPwError("");
    try {
      await checkShopPassword(pw.trim());
      localStorage.setItem("shopsPassword", pw.trim());
      setUnlocked(true);
    } catch { setPwError("Wrong password."); }
  }

  async function handleGenerate() {
    if (!prompt.trim() || loading) return;
    setLoading(true); setError("");
    try {
      const res = await generateImage(prompt.trim(), size, quality);
      setImageUrl(res.image);
      // Drop in preset starter text if one was queued; otherwise keep any
      // text the user already placed (so "Regenerate" doesn't wipe their work).
      if (starterLayers.length) { applyLayers(starterLayers); setStarterLayers([]); }
    } catch (err: any) {
      const status = err?.response?.status;
      setError(
        status === 401 ? "Session expired — refresh and re-enter the password."
        : "Couldn't generate the image — the free art service may be busy. Try again in a moment."
      );
    } finally { setLoading(false); }
  }

  function addLayer() {
    const id = nextId.current++;
    setLayers(prev => [...prev, { id, text: "Your text", xPct: 12, yPct: 44, sizePct: 9, color: "#ffffff", bold: true }]);
    setSelectedId(id);
  }
  function applyLayers(defs: LayerDef[]) {
    setLayers(defs.map(d => ({ ...d, id: nextId.current++ })));
    setSelectedId(null);
  }
  function pickPreset(p: typeof PRESETS[number]) {
    setPrompt(p.prompt);
    setSize(p.size);
    if (imageUrl) applyLayers(p.layers);   // art already there → drop text in now
    else setStarterLayers(p.layers);        // no art yet → text appears after Generate
  }
  function patchLayer(id: number, patch: Partial<Layer>) {
    setLayers(prev => prev.map(l => l.id === id ? { ...l, ...patch } : l));
  }
  function deleteLayer(id: number) {
    setLayers(prev => prev.filter(l => l.id !== id));
    if (selectedId === id) setSelectedId(null);
  }
  function startDrag(e: React.PointerEvent, l: Layer) {
    e.preventDefault();
    setSelectedId(l.id);
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    drag.current = { id: l.id, sx: e.clientX, sy: e.clientY, ox: l.xPct, oy: l.yPct, w: rect.width, h: rect.height };
  }

  function download() {
    if (!imageUrl) return;
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(img, 0, 0);
      for (const l of layers) {
        const fontPx = (l.sizePct / 100) * canvas.height;
        ctx.font = `${l.bold ? "bold " : ""}${fontPx}px Arial, Helvetica, sans-serif`;
        ctx.fillStyle = l.color;
        ctx.textBaseline = "top";
        ctx.shadowColor = "rgba(0,0,0,0.45)";
        ctx.shadowBlur = fontPx * 0.12;
        ctx.fillText(l.text, (l.xPct / 100) * canvas.width, (l.yPct / 100) * canvas.height);
      }
      canvas.toBlob((blob) => {
        if (!blob) return;
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "flyer.png";
        a.click();
        URL.revokeObjectURL(a.href);
      }, "image/png");
    };
    img.src = imageUrl;
  }

  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;

  if (!unlocked) {
    return (
      <div className="app" style={{ paddingTop: 60, maxWidth: 440 }}>
        <h1>🔒 Studio</h1>
        <p className="subtitle">This tool is private. Enter the password to continue.</p>
        <form onSubmit={submitPw} style={{ marginTop: 24 }}>
          <div className="form-group">
            <input type="password" placeholder="Password" value={pw} onChange={e => setPw(e.target.value)} autoFocus />
          </div>
          {pwError && <div className="error-msg">{pwError}</div>}
          <button className="btn" type="submit" style={{ width: "100%", marginTop: 8 }}>Unlock →</button>
        </form>
      </div>
    );
  }

  return (
    <div className="app" style={{ paddingTop: 40, paddingBottom: 60 }}>
      <h1>Studio</h1>
      <p className="subtitle">Describe the art you want — AI makes the background, then you drop your own text on top and download the flyer.</p>

      {/* Prompt + controls */}
      <div className="studio-controls">
        <textarea
          className="studio-prompt"
          placeholder="e.g. Vintage baseball stadium at sunset, dramatic sky, empty space at top for text"
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          rows={3}
        />
        <div className="studio-row">
          <div className="studio-seg">
            {SIZES.map(s => (
              <button key={s.key} type="button" className={`seg-btn${size === s.key ? " active" : ""}`} onClick={() => setSize(s.key)}>{s.label}</button>
            ))}
          </div>
          <div className="studio-seg">
            {[{ k: "medium", l: "Standard" }, { k: "high", l: "High" }].map(q => (
              <button key={q.k} type="button" className={`seg-btn${quality === q.k ? " active" : ""}`} onClick={() => setQuality(q.k)}>{q.l}</button>
            ))}
          </div>
          <button className="btn btn-sm" onClick={handleGenerate} disabled={loading || !prompt.trim()}>
            {loading ? "Generating…" : imageUrl ? "Regenerate" : "Generate art"}
          </button>
        </div>
        <div className="studio-presets">
          <span className="studio-presets-label">Flyer presets</span>
          <div className="studio-preset-chips">
            {PRESETS.map(p => (
              <button key={p.name} type="button" className="studio-preset" onClick={() => pickPreset(p)} disabled={loading}>
                {p.emoji} {p.name}
              </button>
            ))}
          </div>
          <span className="studio-presets-hint">
            {imageUrl ? "Drops editable text onto your art." : "Fills the prompt + queues text — hit Generate, then edit the words."}
          </span>
        </div>

        {!imageUrl && (
          <div className="studio-ideas">
            {IDEAS.map(i => (
              <button key={i} type="button" className="studio-idea" onClick={() => setPrompt(i)} disabled={loading}>{i}</button>
            ))}
          </div>
        )}
        {error && <div className="error-msg" style={{ marginTop: 10 }}>{error}</div>}
      </div>

      {loading && <div className="studio-loading">🎨 Painting your background… (this can take ~20–40s)</div>}

      {imageUrl && (
        <div className="studio-editor">
          {/* Canvas / editor */}
          <div className="studio-stage">
            <div className="studio-stage-wrap" ref={wrapRef} style={{ aspectRatio: ratio }}
                 onPointerDown={(e) => { if (e.target === wrapRef.current?.querySelector("img")) setSelectedId(null); }}>
              <img src={imageUrl} alt="generated art" draggable={false} />
              {layers.map(l => (
                <div
                  key={l.id}
                  className={`studio-text${selectedId === l.id ? " selected" : ""}`}
                  style={{ left: `${l.xPct}%`, top: `${l.yPct}%`, fontSize: `${l.sizePct}cqh`, color: l.color, fontWeight: l.bold ? 800 : 400 }}
                  onPointerDown={(e) => startDrag(e, l)}
                >
                  {l.text || " "}
                </div>
              ))}
            </div>
          </div>

          {/* Toolbar */}
          <div className="studio-tools">
            <div className="studio-tools-row">
              <button className="btn btn-sm" onClick={addLayer}>＋ Add text</button>
              <button className="btn btn-sm" style={{ background: "#16a34a" }} onClick={download}>⬇ Download flyer</button>
            </div>

            {selected ? (
              <div className="studio-layer-edit">
                <label>Text</label>
                <input type="text" value={selected.text} onChange={e => patchLayer(selected.id, { text: e.target.value })} autoFocus />
                <label>Size</label>
                <input type="range" min={3} max={22} step={0.5} value={selected.sizePct} onChange={e => patchLayer(selected.id, { sizePct: Number(e.target.value) })} />
                <div className="studio-layer-row">
                  <div>
                    <label>Color</label>
                    <input type="color" value={selected.color} onChange={e => patchLayer(selected.id, { color: e.target.value })} />
                  </div>
                  <button type="button" className={`seg-btn${selected.bold ? " active" : ""}`} onClick={() => patchLayer(selected.id, { bold: !selected.bold })}>Bold</button>
                  <button type="button" className="seg-btn danger" onClick={() => deleteLayer(selected.id)}>Delete</button>
                </div>
              </div>
            ) : (
              <p className="studio-hint">Click <strong>＋ Add text</strong>, then drag it onto the art. Select a text layer to edit its words, size, and color. Add multiple layers for multiple lines.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
