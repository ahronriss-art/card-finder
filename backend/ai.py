"""Shared LLM helper using Groq's free API (OpenAI-compatible)."""
import os
import json
import re
import httpx

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
# Groq vision models (multimodal). Primary + fallback; base64 images must be <4MB.
GROQ_VISION_MODELS = ["qwen/qwen3.6-27b", "meta-llama/llama-4-scout-17b-16e-instruct"]
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _extract_json(text: str):
    """Pull the first JSON array/object out of an LLM reply (handles ```json fences)."""
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.MULTILINE).strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass
    return None


def parse_release_screenshot(image_data_url: str) -> list:
    """Extract card-product releases from a screenshot of a release calendar using
    Groq vision. Returns [{product, date, sport, brand}]. Raises on total failure."""
    if not GROQ_API_KEY:
        raise RuntimeError("Vision isn't configured (missing GROQ_API_KEY).")

    system = (
        "You read screenshots of trading-card release calendars and return ONLY structured data. "
        "Extract every product row you can see. Respond with a JSON array; each item has: "
        '"product" (full product name as written, include the year, e.g. "2026 Topps Chrome Baseball"), '
        '"date" (the release/street date exactly as shown, e.g. "Jul 29, 2026", or "TBD" if none), '
        '"sport" (Baseball, Basketball, Football, Hockey, Soccer, Pokemon, or "" if unclear), '
        '"brand" (Topps, Bowman, Panini, or the brand in the product name). '
        "Do not invent rows. Return ONLY the JSON array, no prose."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": "Extract all release rows from this calendar screenshot as JSON."},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]},
    ]

    last_err = None
    for model in GROQ_VISION_MODELS:
        try:
            resp = httpx.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "max_tokens": 2000, "temperature": 0},
                timeout=60,
            )
            if resp.status_code >= 400:
                last_err = f"{model}: {resp.status_code} {resp.text[:200]}"
                continue
            text = resp.json()["choices"][0]["message"]["content"]
            parsed = _extract_json(text)
            if isinstance(parsed, dict):
                parsed = parsed.get("releases") or parsed.get("products") or [parsed]
            if isinstance(parsed, list):
                return [r for r in parsed if isinstance(r, dict) and r.get("product")]
            last_err = f"{model}: couldn't parse JSON from reply"
        except Exception as e:
            last_err = f"{model}: {e}"
    raise RuntimeError(last_err or "Vision request failed")


def generate(prompt: str, system: str = "", max_tokens: int = 500) -> str:
    """Generate text with Groq. Returns the text, or raises on failure."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    resp = httpx.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": GROQ_MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": 0.7},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# Fields the model is allowed to set, with short hints so it extracts the right thing.
_SHOP_FIELD_HINTS = {
    "website": "official website URL",
    "phone": "phone number",
    "email": "email address",
    "instagram": "Instagram handle or URL",
    "tiktok": "TikTok handle or URL",
    "whatnot": "Whatnot handle or URL",
    "contact_way": "how they were contacted / preferred contact method",
    "contacted": "contact status and who (e.g. 'yes (Mike)', 'left voicemail')",
    "topps_fanatics": "whether they have a direct account with Topps/Fanatics (yes/no + detail)",
    "tcg_account": "whether they have a direct account with TCG (yes/no + detail)",
    "buys_wholesale": "whether they buy from wholesalers (yes/no + detail)",
    "willing_to_wholesale": "whether they're willing to wholesale with us (yes/no + detail)",
    "collectors": "collectors / sellers they've been working with",
    "city": "city",
    "state": "state (full name)",
    "full_address": "full street address",
    "rating": "Google rating number",
    "reviews": "number of reviews (integer)",
}


def extract_shop_fields(free_text: str, current: dict) -> dict:
    """Parse a free-text note about a card shop into structured field updates.

    Returns {"fields": {field: value, ...}, "summary": "..."}. Only includes
    fields the note gives clear new/changed info for. Never invents data.
    """
    field_lines = "\n".join(f"- {k}: {hint}" for k, hint in _SHOP_FIELD_HINTS.items())
    known = {k: current.get(k) for k in _SHOP_FIELD_HINTS if current.get(k) not in (None, "")}

    system = (
        "You extract structured card-shop info from a user's free-text note and return "
        "ONLY a JSON object. Do not add commentary. Use this exact shape:\n"
        '{"fields": {<field>: <value>}, "summary": "<one short sentence of what changed>"}\n'
        "Rules:\n"
        "- Only include a field if the note clearly provides new or updated info for it.\n"
        "- Never guess or fabricate. If unsure, leave the field out.\n"
        "- rating must be a number; reviews must be an integer. All others are strings.\n"
        "- Keep yes/no answers concise, e.g. 'yes (Mike, calls back fast)'.\n"
        "- Do NOT put anything in a generic notes field; only the listed fields.\n\n"
        "Available fields:\n" + field_lines
    )
    prompt = (
        f"Known info already on file (do not repeat unless the note changes it):\n"
        f"{json.dumps(known, ensure_ascii=False)}\n\n"
        f"User's note:\n{free_text}\n\n"
        "Return the JSON object now."
    )

    raw = generate(prompt, system=system, max_tokens=600)
    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        return {"fields": {}, "summary": ""}
    fields = parsed.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    # keep only allowed fields, coerce numerics
    clean = {}
    for k, v in fields.items():
        if k not in _SHOP_FIELD_HINTS or v in (None, ""):
            continue
        if k == "rating":
            try:
                clean[k] = float(v)
            except (ValueError, TypeError):
                continue
        elif k == "reviews":
            try:
                clean[k] = int(float(v))
            except (ValueError, TypeError):
                continue
        else:
            clean[k] = str(v).strip()
    return {"fields": clean, "summary": str(parsed.get("summary", "")).strip()}


_SHOP_FILTER_KEYS = {
    "q": "free-text keyword to match name/city/address/email",
    "state": "full US state name, e.g. 'Texas'",
    "city": "city name",
    "contacted": "'yes' or 'no' — whether we've contacted them",
    "shop_type": "'shop' for physical shops or 'whatnot_breaker' for online breakers",
    "min_rating": "minimum Google rating number, e.g. 4.5",
    "min_reviews": "minimum number of reviews (integer)",
    "has_website": "true if they must have a website",
    "has_email": "true if they must have an email",
    "has_phone": "true if they must have a phone",
    "has_instagram": "true if they must have an Instagram",
    "topps_fanatics": "true if they must have a Topps/Fanatics account",
    "willing_to_wholesale": "true if they must be willing to wholesale with us",
    "sort": "'rating' (top rated), 'reviews' (most reviews), or 'name'",
}


def nl_to_shop_filters(question: str) -> dict:
    """Turn a natural-language question into structured shop filters (JSON)."""
    keys = "\n".join(f"- {k}: {hint}" for k, hint in _SHOP_FILTER_KEYS.items())
    system = (
        "You convert a question about a card-shop database into a JSON filter object. "
        "Return ONLY JSON, no commentary. Include only keys the question implies; "
        "omit everything else. Use the exact key names below.\n\n" + keys + "\n\n"
        "IMPORTANT: If the question is about ONE specific named shop (e.g. asking for its "
        "email, phone, or details), put ONLY the shop name in 'q' and DO NOT add any "
        "has_email/has_phone/has_website/has_instagram/topps_fanatics/willing_to_wholesale "
        "filters — those are for browsing many shops, not looking one up.\n\n"
        "Examples:\n"
        '"top rated shops in Florida" -> {"state":"Florida","sort":"rating"}\n'
        '"shops I haven\'t contacted with over 100 reviews" -> {"contacted":"no","min_reviews":100}\n'
        '"who has a topps account and wants to wholesale" -> {"topps_fanatics":true,"willing_to_wholesale":true}\n'
        '"what is 502 Frank\'s email and phone?" -> {"q":"502 Frank"}\n'
        '"tell me about Steel City Collectibles" -> {"q":"Steel City Collectibles"}'
    )
    parsed = _parse_json(generate(question, system=system, max_tokens=300))
    if not isinstance(parsed, dict):
        return {}
    out = {}
    for k, v in parsed.items():
        if k in _SHOP_FILTER_KEYS and v not in (None, "", []):
            out[k] = v
    return out


def answer_shop_question(question: str, shops: list, total: int) -> str:
    """Write a concise, grounded answer from the matching shops."""
    lines = []
    for s in shops[:40]:
        bits = [s.get("name")]
        for f in ("full_address", "city", "state", "rating", "reviews", "email", "phone",
                  "website", "instagram", "tiktok", "whatnot", "contact_way", "contacted",
                  "topps_fanatics", "tcg_account", "buys_wholesale", "willing_to_wholesale",
                  "collectors", "notes"):
            if s.get(f):
                bits.append(f"{f}={s[f]}")
        lines.append("- " + ", ".join(str(b) for b in bits))
    context = "\n".join(lines) if lines else "(no matching shops)"
    system = (
        "You answer questions about a sports-card shop database. Use ONLY the provided "
        "matching shops — never invent data. Be concise (1-4 sentences). "
        "For any count or 'how many' question, the answer is exactly the 'Total matching "
        "shops' number given — use that number verbatim, never count the sample rows "
        "(only up to 40 are shown). If listing shops, name a few of the most relevant."
    )
    prompt = (
        f"Question: {question}\n\n"
        f"Total matching shops: {total}. Showing up to 40:\n{context}\n\n"
        "Answer the question."
    )
    return generate(prompt, system=system, max_tokens=400)


def nl_to_card_query(question: str) -> str:
    """Turn a natural-language card question into a tight eBay/auction search
    string (e.g. '2003 Topps Chrome LeBron James #111 PSA 10'). Falls back to
    the raw question so we always search something."""
    system = (
        "You extract the sports/TCG card a user is asking about and return a SHORT "
        "marketplace search string — just the card. Include year, brand/set, player "
        "or subject, card number (with #), parallel/insert, and grade (e.g. PSA 10, "
        "BGS 9.5) when present. Return ONLY the search string, no quotes, no commentary.\n"
        "Examples:\n"
        "'what did the 2003 topps chrome lebron psa 10 last sell for?' -> 2003 Topps Chrome LeBron James #111 PSA 10\n"
        "'how much is a charizard base set psa 9 worth' -> Pokemon Charizard Base Set #4 PSA 9\n"
        "'recent sales of jordan 86 fleer rookie' -> 1986 Fleer Michael Jordan #57 rookie"
    )
    try:
        out = generate(question, system=system, max_tokens=80).strip().strip('"')
        out = out.splitlines()[0].strip() if out else ""
        return out or question
    except Exception:
        return question


def answer_card_question(question: str, sales: list, sources: list) -> str:
    """Write a concise, grounded answer about a card's sales from the real rows
    we gathered. Never invents prices — only uses the provided sales."""
    lines = []
    for s in sales[:40]:
        bits = [s.get("auction_house") or s.get("source") or "?"]
        if s.get("status") == "live auction":
            bits.append("LIVE auction (current bid)")
        if s.get("sold_price"):
            bits.append(f"${s['sold_price']:,.0f}")
        if s.get("status") == "live auction" and s.get("sold_at"):
            bits.append(f"ends {s['sold_at']}")
        elif s.get("sold_at"):
            bits.append(str(s["sold_at"]))
        if s.get("bids") is not None:
            bits.append(f"{s['bids']} bids")
        if s.get("title"):
            bits.append(str(s["title"])[:70])
        lines.append("- " + " | ".join(bits))
    context = "\n".join(lines) if lines else "(no sales found from any source)"
    src_summary = ", ".join(f"{x['name']}: {x['status']}" for x in sources) or "(none)"
    system = (
        "You are a sports-card price assistant. Answer using ONLY the rows provided — "
        "never invent prices, dates, or sources. Be concise and concrete. "
        "IMPORTANT: rows marked 'LIVE auction (current bid)' are OPEN auctions still in "
        "progress — they are NOT completed sales. Describe them as 'currently up for "
        "auction' with the current bid and end date; never call them sold prices. eBay "
        "rows are recent marketplace listings/sales. "
        "When possible give: the most recent completed sale (price + date if known), the "
        "typical/average and range of actual sales, plus any notable live auctions "
        "happening now and from which source. If a row has no date, say the date is "
        "unavailable rather than guessing. If there are no rows, say so plainly and "
        "suggest a more specific card (year, set, number, grade). Prices are USD."
    )
    prompt = (
        f"User question: {question}\n\n"
        f"Source status — {src_summary}\n"
        f"Sale rows ({len(sales)} total, showing up to 40):\n{context}\n\n"
        "Answer the question grounded in these rows."
    )
    try:
        return generate(prompt, system=system, max_tokens=450)
    except Exception as e:
        n = len(sales)
        return f"Found {n} sale{'s' if n != 1 else ''}, but couldn't generate a summary ({e})."


def enhance_image_prompt(description: str) -> str:
    """Expand a short request into a vivid image-gen prompt for a card business.
    Tells the model to render NO text — the user overlays real text afterward."""
    system = (
        "You turn a short request into one vivid, detailed image-generation prompt for a "
        "sports-card / collectibles business flyer or picture. Describe composition, subject, "
        "style, lighting, colors, and mood concretely. CRITICAL: produce background art and "
        "imagery ONLY — do NOT include any words, letters, captions, logos, or text to render "
        "in the image (the user adds real text on top later). Leave clean, uncluttered space "
        "where text could go. Return ONLY the prompt, no preamble."
    )
    try:
        out = generate(description, system=system, max_tokens=220).strip()
        return out or description
    except Exception:
        return description


def _parse_json(text: str):
    """Best-effort JSON extraction from an LLM reply."""
    text = text.strip()
    # strip ```json fences if present
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


def plan_folder_actions(folder: str, alerts: list, instruction: str) -> dict:
    """Turn a natural-language request about a folder of saved-search alerts into
    a structured action plan the caller can apply. Returns
    {"summary": str, "actions": [ ... ]}. If the request is just a question,
    actions is empty and the answer goes in summary."""
    compact = [
        {"id": a.get("id"), "query": a.get("query"), "folder": a.get("folder"),
         "min_price": a.get("min_price"), "numbered_to": a.get("numbered_to"),
         "interval_min": a.get("check_interval_minutes")}
        for a in alerts
    ]
    system = (
        "You help organize a user's saved card-search alerts. "
        "Reply with ONLY valid JSON, no prose, no code fences."
    )
    prompt = f"""Folder being worked on: "{folder}"

The user's alerts (JSON):
{json.dumps(compact, indent=2)}

User request: {instruction}

Return JSON exactly like:
{{"summary": "<1-2 sentence plain-English description of what you'll do>", "actions": [ ... ]}}

Allowed actions (only use ids from the list above):
- {{"op":"rename_folder","to":"NEW NAME"}}  (renames the whole "{folder}" folder)
- {{"op":"set_folder","id":123,"folder":"NAME"}}  (move an alert to a folder; use "" to ungroup)
- {{"op":"delete","id":123}}  (remove an alert)
- {{"op":"update","id":123,"fields":{{...}}}}  (edit an alert's filter details — include ONLY fields you're changing)

Editable fields for "update": query (search text), sport, brand, insert_type,
card_number, year, exclude (words to exclude), min_price, max_price, numbered_to
(serial /N), check_interval_minutes (15-1440), source ("ebay" or "auction"),
folder. Use "" or null to clear a text field.

Examples:
- raise the price floor: {{"op":"update","id":5,"fields":{{"min_price":3000}}}}
- add an exclude + brand: {{"op":"update","id":7,"fields":{{"exclude":"reprint lot","brand":"Topps Chrome"}}}}
- change the search wording: {{"op":"update","id":9,"fields":{{"query":"Wembanyama Silver","numbered_to":99}}}}
- ADD/APPEND words to EVERY alert's search: emit one "update" per alert whose new
  "query" is that alert's CURRENT query text plus the requested words. E.g. if the
  user says 'add "true base /10 auto" to every search' and alert 3's query is
  "2025-26 Topps Chrome Flagg", emit {{"op":"update","id":3,"fields":{{"query":"2025-26 Topps Chrome Flagg true base /10 auto"}}}}
  — do this for EVERY alert in the list, keeping each alert's own base query.

Rules: Only reference alert ids that exist. "Add words to the searches" / "put X on
every alert" means append those words to each alert's existing query (one update per
alert) — never drop the original text. If the request is just a question or you have
no changes to make, return an empty actions array and put your answer in summary.
Return ONLY the JSON object."""
    text = generate(prompt, system=system, max_tokens=700)
    parsed = _parse_json(text)
    if not isinstance(parsed, dict):
        return {"summary": "Sorry, I couldn't understand that — try rephrasing.", "actions": []}
    parsed.setdefault("summary", "")
    parsed.setdefault("actions", [])
    if not isinstance(parsed["actions"], list):
        parsed["actions"] = []
    return parsed


def plan_organize_actions(alerts: list, instruction: str) -> dict:
    """Whole-list organizer: file the user's alerts into folders. Same JSON shape
    as plan_folder_actions, focused on set_folder actions."""
    compact = [
        {"id": a.get("id"), "query": a.get("query"), "folder": a.get("folder"),
         "min_price": a.get("min_price"), "numbered_to": a.get("numbered_to")}
        for a in alerts
    ]
    system = (
        "You organize a user's saved card-search alerts into folders. "
        "Reply with ONLY valid JSON, no prose, no code fences."
    )
    prompt = f"""The user's alerts (JSON):
{json.dumps(compact, indent=2)}

User request: {instruction}

File the alerts into sensible folders (e.g. by player, set, sport, or however the
user asks). Return JSON exactly like:
{{"summary": "<1-2 sentence plain-English description>", "actions": [ ... ]}}

Allowed actions (only use ids that exist above):
- {{"op":"set_folder","id":123,"folder":"FOLDER NAME"}}  (file an alert into a folder; "" to ungroup)
- {{"op":"delete","id":123}}
- {{"op":"update","id":123,"fields":{{...}}}}  (edit filter details; include ONLY changed fields)

Editable fields for "update": query, sport, brand, insert_type, card_number, year,
exclude, min_price, max_price, numbered_to, check_interval_minutes, source, folder.

Prefer reusing existing folder names when they fit. If it's just a question, return
empty actions and answer in summary. Return ONLY the JSON object."""
    text = generate(prompt, system=system, max_tokens=900)
    parsed = _parse_json(text)
    if not isinstance(parsed, dict):
        return {"summary": "Sorry, I couldn't understand that — try rephrasing.", "actions": []}
    parsed.setdefault("summary", "")
    parsed.setdefault("actions", [])
    if not isinstance(parsed["actions"], list):
        parsed["actions"] = []
    return parsed
