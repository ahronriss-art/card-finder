"""Identify a trading card from a photo using Claude vision (Anthropic).

Phase 1 of the Card Lookup tab: photo -> structured card identity + an eBay
search string. Pricing (sold comps, buy price, profit odds) is computed by the
caller from get_sold_history; PSA pop/gem-rate is Phase 2 (needs PSA_API_TOKEN).
"""
import os
import json
from anthropic import AsyncAnthropic

_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

# Vision model — claude-opus-4-8 (capable, vision-enabled). Identification is a
# short structured-extraction task, so no thinking needed (omitted).
_MODEL = "claude-opus-4-8"

_SYSTEM = """You are an expert sports-card and TCG identifier. Given a photo of a SINGLE trading card (raw or in a graded slab), identify it as precisely as you can.

Return ONLY a JSON object — no prose, no markdown fences — with exactly these keys:
{
  "identified": true,            // false if the image is not a single card or is unreadable
  "player": "full player or character name, or null",
  "year": "season/year e.g. 2023-24, or null",
  "brand": "manufacturer/product e.g. Topps Chrome, Panini Prizm, Pokemon SV, or null",
  "card_number": "the # printed on the card, or null",
  "parallel": "parallel/insert/variation e.g. Gold /10, Silver Prizm, Holo, or null",
  "is_graded": false,            // true only if it's clearly a graded slab
  "grader": "PSA/BGS/SGC, or null",
  "grade": "numeric grade if graded e.g. 10, or null",
  "cert_number": "cert/serial number read off the slab label, or null",
  "search_query": "the best concise eBay search to find SOLD comps of this exact card",
  "confidence": "high",          // high | medium | low
  "notes": "one short helpful line, or null"
}

Make search_query specific: include player, year, brand, parallel, card number, and grade when known, so it pulls comps for this exact card and not similar ones."""


def _extract_json(text: str) -> dict:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        # in case there's a trailing fence remnant
        t = t.strip("`").strip()
    # grab the outermost {...} if the model added stray text
    if not t.startswith("{"):
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b != -1:
            t = t[a:b + 1]
    return json.loads(t)


async def identify_card(image_b64: str, media_type: str = "image/jpeg") -> dict:
    """Return the parsed identification dict (raises on API/parse failure)."""
    msg = await _client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": "Identify this card. Return only the JSON object."},
            ],
        }],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    return _extract_json(text)
