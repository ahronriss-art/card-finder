import { useState, useEffect, useRef, useCallback } from "react";
import { designFlyer, generateImage, getImageEngines, type FlyerSpec, type ImageEngine } from "./api/client";
import ShopPasswordForm from "./ShopPasswordForm";
import { checkShopPassword, getShopsPassword } from "./api/client";

// Canvas sizes people actually post to.
const SIZES = {
  square: { w: 1080, h: 1080, label: "Square (post)" },
  story: { w: 1080, h: 1920, label: "Story / Reel" },
  letter: { w: 1275, h: 1650, label: "Print (8.5×11)" },
} as const;
type SizeKey = keyof typeof SIZES;

const TEMPLATES: { id: FlyerSpec["template"]; label: string }[] = [
  { id: "poster", label: "Poster — photo behind the text" },
  { id: "hero", label: "Hero — photo on top" },
  { id: "split", label: "Split — photo beside the text" },
  { id: "grid", label: "Grid — several photos" },
];

const BLANK: FlyerSpec = {
  template: "poster", headline: "", subhead: "", bullets: [],
  price: "", cta: "", contact: "",
  palette: { bg: "#0b1220", accent: "#f5b301", text: "#ffffff" },
};

/** Shrink an image to fit inside `max` px and return a data URL. Uploads go to
 *  the server for AI editing, and a 12MP phone photo is pointlessly large. */
function downscale(file: File, max = 1400): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("read failed"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("not an image"));
      img.onload = () => {
        const scale = Math.min(1, max / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.round(img.width * scale);
        c.height = Math.round(img.height * scale);
        c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
        resolve(c.toDataURL("image/jpeg", 0.9));
      };
      img.src = String(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

/** Re-encode a data URL at <= `max` px. FLUX.2 klein rejects any input over
 *  512x512, so the edit path has to shrink further than the display copy. */
async function shrinkTo(dataUrl: string, max: number): Promise<string> {
  const img = await loadImg(dataUrl);
  const scale = Math.min(1, max / Math.max(img.width, img.height));
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(img.width * scale));
  c.height = Math.max(1, Math.round(img.height * scale));
  c.getContext("2d")!.drawImage(img, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.9);
}

const loadImg = (src: string) =>
  new Promise<HTMLImageElement>((res, rej) => {
    const i = new Image();
    i.onload = () => res(i);
    i.onerror = () => rej(new Error("image failed to load"));
    i.src = src;
  });

/** Draw `img` filling the box, cropping the overflow (CSS object-fit: cover). */
function drawCover(g: CanvasRenderingContext2D, img: HTMLImageElement,
                   x: number, y: number, w: number, h: number) {
  const scale = Math.max(w / img.width, h / img.height);
  const dw = img.width * scale, dh = img.height * scale;
  g.save();
  g.beginPath();
  g.rect(x, y, w, h);
  g.clip();
  g.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
  g.restore();
}

/** Largest font size (<= start) at which `text` fits `maxW` on one line. */
function fitFont(g: CanvasRenderingContext2D, text: string, maxW: number,
                 start: number, weight = 800, min = 14) {
  let size = start;
  while (size > min) {
    g.font = `${weight} ${size}px Impact, "Arial Black", system-ui, sans-serif`;
    if (g.measureText(text).width <= maxW) break;
    size -= 2;
  }
  return size;
}

function wrap(g: CanvasRenderingContext2D, text: string, maxW: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const w of words) {
    const next = line ? `${line} ${w}` : w;
    if (g.measureText(next).width > maxW && line) {
      lines.push(line);
      line = w;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}


type CopyOpts = {
  textX: number; textTop: number; textW: number;
  w: number; h: number; pad: number; scale: number; measure: boolean;
};

/** Draw (or just measure) the text block. Returns the height it occupies.
 *  `measure: true` runs the identical layout maths without painting, so the
 *  caller can discover an overflow before anything is committed to the canvas. */
function drawCopy(g: CanvasRenderingContext2D, spec: FlyerSpec, o: CopyOpts): number {
  const { textX, textTop, textW, w, pad, scale, measure } = o;
  const { bg: bgc, accent, text } = spec.palette;
  const S = (v: number) => Math.max(8, v * scale);
  let y = textTop;
  g.textBaseline = "top";

  if (spec.headline) {
    const words = spec.headline.toUpperCase();
    const s1 = fitFont(g, words, textW, S(w * 0.13));
    g.font = `800 ${s1}px Impact, "Arial Black", system-ui, sans-serif`;
    if (!measure) g.fillStyle = text;
    for (const ln of wrap(g, words, textW)) {
      if (!measure) g.fillText(ln, textX, y);
      y += s1 * 1.02;
    }
    const rule = Math.max(4, S(w * 0.008));
    if (!measure) {
      g.fillStyle = accent;
      g.fillRect(textX, y + S(10), Math.min(textW, s1 * 3), rule);
    }
    y += S(10) + rule + S(pad * 0.45);
  }

  if (spec.subhead) {
    const s2 = S(w * 0.036);
    g.font = `600 ${s2}px system-ui, -apple-system, sans-serif`;
    if (!measure) g.fillStyle = text;
    for (const ln of wrap(g, spec.subhead, textW)) {
      if (!measure) g.fillText(ln, textX, y);
      y += s2 * 1.3;
    }
    y += S(pad * 0.35);
  }

  if (spec.bullets.length) {
    const s3 = S(w * 0.031);
    g.font = `500 ${s3}px system-ui, -apple-system, sans-serif`;
    for (const b of spec.bullets) {
      if (!measure) { g.fillStyle = accent; g.fillText("\u2022", textX, y); g.fillStyle = text; }
      for (const ln of wrap(g, b, textW - s3 * 1.4)) {
        if (!measure) g.fillText(ln, textX + s3 * 1.4, y);
        y += s3 * 1.32;
      }
    }
    y += S(pad * 0.3);
  }

  if (spec.price) {
    const s4 = fitFont(g, spec.price, textW, S(w * 0.085));
    g.font = `800 ${s4}px Impact, "Arial Black", system-ui, sans-serif`;
    if (!measure) { g.fillStyle = accent; g.fillText(spec.price, textX, y); }
    y += s4 * 1.15;
  }

  if (spec.cta) {
    const s5 = S(w * 0.034);
    g.font = `700 ${s5}px system-ui, -apple-system, sans-serif`;
    const bw = g.measureText(spec.cta).width + s5 * 1.6, bh = s5 * 2;
    if (!measure) {
      g.fillStyle = accent;
      g.fillRect(textX, y, Math.min(bw, textW), bh);
      g.fillStyle = bgc;
      g.fillText(spec.cta, textX + s5 * 0.8, y + bh / 2 - s5 * 0.55);
    }
    y += bh + S(pad * 0.35);
  }

  if (spec.contact) {
    const s6 = S(w * 0.028);
    g.font = `600 ${s6}px system-ui, -apple-system, sans-serif`;
    if (!measure) { g.fillStyle = text; g.fillText(spec.contact, textX, y); }
    y += s6 * 1.2;
  }

  return y - textTop;
}

export default function FlyersPage() {
  const [unlocked, setUnlocked] = useState(false);
  const [checking, setChecking] = useState(true);
  const [photos, setPhotos] = useState<string[]>([]);
  const [brief, setBrief] = useState("");
  const [contact, setContact] = useState("");
  const [spec, setSpec] = useState<FlyerSpec>(BLANK);
  const [size, setSize] = useState<SizeKey>("square");
  const [bg, setBg] = useState<string | null>(null);      // AI-generated backdrop
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [engines, setEngines] = useState<ImageEngine[]>([]);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    (async () => {
      try {
        if (getShopsPassword()) {
          await checkShopPassword(getShopsPassword());
          setUnlocked(true);
        }
      } catch { /* stay locked */ } finally { setChecking(false); }
    })();
  }, []);

  useEffect(() => {
    if (unlocked) getImageEngines().then(setEngines).catch(() => {});
  }, [unlocked]);

  // ---- the renderer: AI chooses the design, this draws it -----------------
  const render = useCallback(async () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { w, h } = SIZES[size];
    canvas.width = w; canvas.height = h;
    const g = canvas.getContext("2d")!;
    const { bg: bgc } = spec.palette;   // accent/text are used inside drawCopy
    const pad = Math.round(w * 0.07);

    g.fillStyle = bgc;
    g.fillRect(0, 0, w, h);

    const imgs = await Promise.all(
      photos.slice(0, 4).map(p => loadImg(p).catch(() => null)));
    const shots = imgs.filter(Boolean) as HTMLImageElement[];
    const backdrop = bg ? await loadImg(bg).catch(() => null) : null;

    // Where the text block starts, per template.
    let textTop = pad;
    let textW = w - pad * 2;
    let textX = pad;

    if (spec.template === "poster") {
      const hero = shots[0] || backdrop;
      if (hero) drawCover(g, hero, 0, 0, w, h);
      // Scrim so text stays readable over any photo.
      const grad = g.createLinearGradient(0, h * 0.25, 0, h);
      grad.addColorStop(0, "rgba(0,0,0,0)");
      grad.addColorStop(1, bgc);
      g.fillStyle = grad;
      g.fillRect(0, 0, w, h);
      textTop = Math.round(h * 0.52);
    } else if (spec.template === "hero") {
      const boxH = Math.round(h * 0.5);
      if (backdrop) drawCover(g, backdrop, 0, 0, w, boxH);
      if (shots[0]) drawCover(g, shots[0], 0, 0, w, boxH);
      textTop = boxH + pad;
    } else if (spec.template === "split") {
      const half = Math.round(w * 0.46);
      if (shots[0]) drawCover(g, shots[0], 0, 0, half, h);
      textX = half + pad * 0.7;
      textW = w - textX - pad * 0.7;
      textTop = Math.round(h * 0.16);
    } else {
      // grid: header band, photos, then the copy underneath
      const gridTop = Math.round(h * 0.20);
      const gridH = Math.round(h * 0.42);
      const cols = shots.length > 1 ? 2 : 1;
      const rows = Math.ceil(Math.max(shots.length, 1) / cols);
      const cw = (w - pad * 2 - (cols - 1) * 12) / cols;
      const ch = (gridH - (rows - 1) * 12) / rows;
      shots.forEach((im, i) => {
        const cx = pad + (i % cols) * (cw + 12);
        const cy = gridTop + Math.floor(i / cols) * (ch + 12);
        drawCover(g, im, cx, cy, cw, ch);
      });
      textTop = gridTop + gridH + pad * 0.8;
    }

    // Two passes: measure the copy at full size, then, if it would run off the
    // bottom, redraw it scaled to fit. Without this a flyer with a headline,
    // bullets, a price AND a CTA silently overflowed — the contact line landed
    // on top of the price and the button fell off the canvas.
    const avail = h - textTop - pad;
    const needed = drawCopy(g, spec, { textX, textTop, textW, w, h, pad, scale: 1, measure: true });
    const scale = needed > avail ? Math.max(0.4, avail / needed) : 1;
    drawCopy(g, spec, { textX, textTop, textW, w, h, pad, scale, measure: false });
  }, [spec, photos, size, bg]);

  useEffect(() => { render().catch(() => {}); }, [render]);

  async function addPhotos(files: FileList | null) {
    if (!files?.length) return;
    setError("");
    try {
      const next = await Promise.all(Array.from(files).slice(0, 4).map(f => downscale(f)));
      setPhotos(p => [...p, ...next].slice(0, 4));
    } catch {
      setError("Couldn't read that file — try a JPG or PNG.");
    }
  }

  async function handleDesign() {
    if (!brief.trim()) { setError("Say what the flyer is for."); return; }
    setBusy("Designing…"); setError(""); setNote("");
    try {
      const s = await designFlyer(brief.trim(), Math.max(photos.length, 1), contact.trim());
      setSpec({ ...s, template: photos.length > 1 ? s.template : s.template });
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't design the flyer.");
    } finally { setBusy(""); }
  }

  /** `whole` = let the image model draw the entire flyer, words and all.
   *  Lucid Origin spells reliably, so this is viable for a punchy poster; the
   *  canvas path stays the choice when exact prices/phone numbers matter. */
  async function handleArt(whole: boolean) {
    setBusy(whole ? "Making flyer…" : "Generating art…");
    setError(""); setNote("");
    try {
      const prompt = whole
        ? `Bold sports-card shop flyer poster. Headline text reads "${spec.headline || brief}".` +
          (spec.subhead ? ` Smaller text reads "${spec.subhead}".` : "") +
          (spec.price ? ` Price callout reads "${spec.price}".` : "") +
          ` Professional graphic design, high contrast, clean modern typography, no watermark.`
        : `${brief || "sports card shop promo"} — flyer background art, no text, no words, no letters`;
      const r = await generateImage(prompt, size === "story" ? "portrait" : "square",
                                    "medium", { engine: "lucid" });
      setBg(r.image);
      if (whole) setSpec(s => ({ ...s, template: "poster", headline: "", subhead: "", bullets: [], price: "" }));
      const skipped = (r.fell_back_from || []).map(x => x.split(":")[0]).join(", ");
      setNote(`Art by ${r.engine}${skipped ? ` — ${skipped} unavailable` : ""}.`
              + (whole ? " Check the spelling before posting." : ""));
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't generate art.");
    } finally { setBusy(""); }
  }

  /** Restyle the uploaded photo into flyer art. klein is the only free engine
   *  that accepts a reference image — but it invents gibberish lettering if
   *  left to its own devices, so the prompt bans text and the real copy is
   *  drawn on the canvas afterwards. */
  async function handleRestyle() {
    if (!photos.length) { setError("Upload a photo first."); return; }
    setBusy("Restyling…"); setError(""); setNote("");
    try {
      const refs = await Promise.all(photos.slice(0, 4).map(p => shrinkTo(p, 512)));
      const prompt = `${brief || "sports card shop promo"} — turn this into dramatic flyer `
        + `background art. Keep the card as the subject. No text, no words, no letters, no watermark.`;
      const r = await generateImage(prompt, size === "story" ? "portrait" : "square", "medium",
                                    { engine: "klein", image: refs[0] });
      setBg(r.image);
      setSpec(s => ({ ...s, template: "poster" }));
      setNote(`Restyled by ${r.engine} — your text is drawn over it, so it stays readable.`);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Couldn't restyle the photo.");
    } finally { setBusy(""); }
  }

  function download() {
    const c = canvasRef.current;
    if (!c) return;
    const a = document.createElement("a");
    a.download = `flyer-${Date.now()}.png`;
    a.href = c.toDataURL("image/png");
    a.click();
  }

  const nano = engines.find(e => e.id === "gemini");
  const setField = (k: keyof FlyerSpec, v: any) => setSpec(s => ({ ...s, [k]: v }));

  if (checking) return <div className="app" style={{ paddingTop: 60 }}><p className="subtitle">Loading…</p></div>;
  if (!unlocked) return <ShopPasswordForm title="Flyers" subtitle="This tool is private. Enter the password to continue." onUnlocked={() => setUnlocked(true)} />;

  return (
    <div className="app">
      <h1 className="title">Flyers</h1>
      <p className="subtitle">
        Upload a card photo, describe the flyer, and the AI art-directs it. The text is drawn as
        real text, so prices and phone numbers stay sharp.
      </p>

      {error && <div className="error-box" style={{ marginBottom: 12 }}>{error}</div>}
      {note && <div className="subtitle" style={{ marginBottom: 12 }}>{note}</div>}

      <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-start" }}>
        {/* ---- controls ---- */}
        <div style={{ flex: "1 1 340px", minWidth: 300 }}>
          <div className="add-alert-box" style={{ marginBottom: 14 }}>
            <div className="add-alert-title">1 · Photos</div>
            <input type="file" accept="image/*" multiple onChange={e => addPhotos(e.target.files)} />
            {photos.length > 0 && (
              <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                {photos.map((p, i) => (
                  <div key={i} style={{ position: "relative" }}>
                    <img src={p} alt="" style={{ width: 62, height: 62, objectFit: "cover", borderRadius: 8 }} />
                    <button className="alert-remove-btn" style={{ position: "absolute", top: -6, right: -6 }}
                      onClick={() => setPhotos(ps => ps.filter((_, j) => j !== i))} title="Remove">✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="add-alert-box" style={{ marginBottom: 14 }}>
            <div className="add-alert-title">2 · What's it for?</div>
            <textarea rows={3} value={brief} onChange={e => setBrief(e.target.value)}
              placeholder={`e.g. "We're buying Chrome Update singles over $1,000 — cash same day"`}
              style={{ width: "100%", padding: 10, borderRadius: 8, background: "rgba(255,255,255,0.05)",
                       color: "inherit", border: "1px solid rgba(255,255,255,0.15)" }} />
            <input type="text" value={contact} onChange={e => setContact(e.target.value)}
              placeholder="Contact line (phone / @handle)"
              style={{ width: "100%", marginTop: 8, padding: 10, borderRadius: 8,
                       background: "rgba(255,255,255,0.05)", color: "inherit",
                       border: "1px solid rgba(255,255,255,0.15)" }} />
            <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              <button className="btn" disabled={!!busy} onClick={handleDesign}>
                {busy === "Designing…" ? "Designing…" : "✨ Design with AI"}
              </button>
              <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.1)" }}
                disabled={!!busy} onClick={() => handleArt(false)}>
                {busy === "Generating art…" ? "Generating…" : "🎨 AI background"}
              </button>
              <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.1)" }}
                disabled={!!busy} onClick={() => handleArt(true)}
                title="The image model draws the whole flyer including the words">
                {busy === "Making flyer…" ? "Making…" : "🖼 Whole flyer (AI text)"}
              </button>
              <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.1)" }}
                disabled={!!busy || !photos.length} onClick={handleRestyle}
                title="Restyle your uploaded photo into flyer art — free">
                {busy === "Restyling…" ? "Restyling…" : "🪄 Restyle my photo"}
              </button>
              {bg && <button className="btn btn-sm" style={{ background: "rgba(255,255,255,0.1)" }}
                onClick={() => setBg(null)}>Clear art</button>}
            </div>
          </div>

          <div className="add-alert-box">
            <div className="add-alert-title">3 · Tweak</div>
            <label className="numbered-hint">Layout</label>
            <select value={spec.template} onChange={e => setField("template", e.target.value)}
              style={{ width: "100%", padding: 9, borderRadius: 8, marginBottom: 10 }}>
              {TEMPLATES.map(t => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <label className="numbered-hint">Size</label>
            <select value={size} onChange={e => setSize(e.target.value as SizeKey)}
              style={{ width: "100%", padding: 9, borderRadius: 8, marginBottom: 10 }}>
              {Object.entries(SIZES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
            {([["headline", "Headline"], ["subhead", "Subhead"], ["price", "Price / offer"],
               ["cta", "Call to action"], ["contact", "Contact"]] as const).map(([k, label]) => (
              <div key={k} style={{ marginBottom: 8 }}>
                <label className="numbered-hint">{label}</label>
                <input type="text" value={(spec as any)[k]} onChange={e => setField(k, e.target.value)}
                  style={{ width: "100%", padding: 9, borderRadius: 8,
                           background: "rgba(255,255,255,0.05)", color: "inherit",
                           border: "1px solid rgba(255,255,255,0.15)" }} />
              </div>
            ))}
            <label className="numbered-hint">Bullets (one per line)</label>
            <textarea rows={3} value={spec.bullets.join("\n")}
              onChange={e => setField("bullets", e.target.value.split("\n").filter(Boolean).slice(0, 4))}
              style={{ width: "100%", padding: 9, borderRadius: 8, background: "rgba(255,255,255,0.05)",
                       color: "inherit", border: "1px solid rgba(255,255,255,0.15)" }} />
            <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
              {(["bg", "accent", "text"] as const).map(k => (
                <label key={k} style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
                  <input type="color" value={spec.palette[k]}
                    onChange={e => setSpec(s => ({ ...s, palette: { ...s.palette, [k]: e.target.value } }))} />
                  {k}
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* ---- preview ---- */}
        <div style={{ flex: "1 1 340px", minWidth: 300 }}>
          <canvas ref={canvasRef}
            style={{ width: "100%", maxWidth: 420, borderRadius: 12, display: "block",
                     border: "1px solid rgba(255,255,255,0.15)", background: "#111" }} />
          <button className="btn" style={{ marginTop: 12 }} onClick={download}>⬇ Download PNG</button>
          {nano && !nano.ready && (
            <p className="numbered-hint" style={{ marginTop: 10 }}>
              All of this runs on Cloudflare's free tier (10,000 neurons/day). Lucid Origin makes
              art and is the one free model that spells reliably; FLUX.2 klein restyles your
              uploaded photo but invents gibberish lettering, so its prompt bans text and your copy
              is drawn over the top. Gemini (nano banana) would edit at higher quality — the key is
              set but Google returns a quota error until billing is enabled. Nothing depends on it.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
