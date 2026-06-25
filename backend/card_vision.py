"""Identify a trading card from a photo using Groq's FREE vision model.

Phase 1 of the Card Lookup tab: photo -> structured card identity + an eBay
search string. Groq (Llama 4 Scout, multimodal) is free — same GROQ_API_KEY the
chatbot/email-writer already use. Pricing is computed by the caller from
get_sold_history; PSA pop/gem-rate is Phase 2 (needs PSA_API_TOKEN).
"""
import os
import json
import httpx

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Free, vision-capable model on Groq.
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_INSTRUCTIONS = """You are an expert sports-card and TCG identifier. Identify the SINGLE trading card in this image as precisely as you can.

The image is one of two things:
1. A photo of a card (raw or in a graded slab), OR
2. A SCREENSHOT of a marketplace listing (eBay, COMC, Whatnot, etc.).

If it's a listing screenshot: READ THE TEXT. The listing title and visible details almost always spell out the exact year, brand/product, parallel, serial (e.g. /50), card number, player, and grade (e.g. "BGS 9.5", "PSA 10"). Trust that text over guessing from the picture — it is the authoritative source. Parse every field straight from the title. For search_query, base it on the listing title (trimmed to the card's identifying words), since that's what finds matching sold comps. Ignore the listed price, seller, and shipping text — only extract the card's identity.

If it's a plain card photo: identify it visually from the design, logos, player, and any serial/grade text on the card or slab label.

Return ONLY a JSON object — no prose, no markdown fences — with exactly these keys:
{
  "identified": true,            // false if the image is not a single card or is unreadable
  "player": "full player or character name, or null",
  "year": "season/year e.g. 2023-24, or null",
  "brand": "manufacturer/product e.g. Topps Chrome, Panini Prizm, Bowman Chrome, Pokemon SV, or null",
  "card_number": "the # printed on the card, or null",
  "parallel": "parallel/insert/variation e.g. Gold /50, Silver Prizm, Holo, or null",
  "is_graded": false,            // true only if it's clearly a graded slab
  "grader": "PSA/BGS/SGC, or null",
  "grade": "numeric grade if graded e.g. 9.5, or null",
  "cert_number": "cert/serial number read off the slab label, or null",
  "search_query": "the best concise eBay search to find SOLD comps of this exact card",
  "confidence": "high",          // high | medium | low
  "notes": "one short helpful line, or null"
}

CRITICAL for "parallel": capture the FULL parallel/insert name — the color AND the insert/refractor type together (e.g. "Gold Sapphire", "Gold Geometric Refractor", "Sky Write Green", "Orange Wave"), not just the color. These words are what distinguish otherwise-identical cards, so read them carefully off the card/label/title. Always include the serial (e.g. "/50") in "parallel" when the card is numbered — read it from the card, slab label, or listing text.

Make search_query specific: include player, year, brand, the FULL parallel, card number, serial, and grade when known, so it pulls comps for this exact card and not similar ones. Output only the JSON object."""


def _extract_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        t = t.strip("`").strip()
    if not t.startswith("{"):
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b != -1:
            t = t[a:b + 1]
    return json.loads(t)


async def identify_card(image_b64: str, media_type: str = "image/jpeg") -> dict:
    """Return the parsed identification dict (raises on API/parse failure)."""
    data_url = f"data:{media_type};base64,{image_b64}"
    payload = {
        "model": GROQ_VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _INSTRUCTIONS},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        "max_tokens": 1024,
        "temperature": 0.1,
    }
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(text)
