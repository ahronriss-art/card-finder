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


def parse_release_prose(text: str) -> list:
    """Read a release's article/overview prose and extract a STARTER checklist of
    notable chase cards. Returns [{player, card_number, parallel, numbered_to,
    subset, team}] — same shape as _parse_checklist_ai — or [] if nothing usable.
    Prose (not a structured list) is the only free data, so we extract the named
    stars and the key numbered parallels/inserts rather than every base card."""
    if not GROQ_API_KEY:
        return []
    system = (
        "You extract a STARTER card checklist from an article about a trading-card "
        "release. Return ONLY a JSON array (no prose). Each item: "
        '"player" (a named athlete/subject, or null for a set-wide parallel), '
        '"card_number" (null unless a specific number is stated), '
        '"parallel" (color/parallel/insert/auto name like "Gold","Superfractor","Rookie Auto"; null for plain base), '
        '"numbered_to" (integer print run if the text gives one, e.g. /50 -> 50, "1/1" -> 1, else null), '
        '"subset" (insert/subset name or null), "team" (or null). '
        "Rules: include every notable player the article names (rookies + stars). "
        "Include every numbered parallel or insert tier the article describes, with its print run. "
        "If the article pairs a star with a specific parallel/auto + print run, make that row. "
        "Do NOT invent players or numbers not supported by the text. Aim for 10-40 rows. "
        "Return ONLY the JSON array."
    )
    try:
        raw = generate(text[:12000], system=system, max_tokens=3000)
    except Exception as e:
        print(f"parse_release_prose failed: {e}")
        return []
    parsed = _extract_json(raw)
    if not isinstance(parsed, list):
        return []
    out = []
    for r in parsed:
        if not isinstance(r, dict):
            continue
        nt = r.get("numbered_to")
        try:
            nt = int(nt) if nt not in (None, "", "null") else None
        except Exception:
            nt = None
        player = (r.get("player") or "").strip() or None
        parallel = (r.get("parallel") or "").strip() or None
        if not player and not parallel:
            continue
        out.append({
            "player": player,
            "card_number": (str(r.get("card_number")).strip() if r.get("card_number") not in (None, "") else None),
            "parallel": parallel,
            "numbered_to": nt,
            "subset": (r.get("subset") or "").strip() or None,
            "team": (r.get("team") or "").strip() or None,
        })
    return out


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
    "contact_name": "name of the specific person contacted at the shop (e.g. the owner or manager)",
    "contact_phone": "that contact person's direct phone number",
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


_CARD_FIELD_HINTS = {
    "store": "the shop's business name",
    "owner": "the owner's name",
    "name": "the person we actually deal with at the shop, if different from the owner",
    "number": "phone number, digits only or 555-123-4567 style",
    "email": "email address",
    "website": "website domain, e.g. example.com (no http://)",
    "ig": "Instagram handle, e.g. @shopname",
    "address": "street address only, no city/state",
    "city": "city",
    "state": "2-letter state code, e.g. TX",
}


def extract_contact_card(free_text: str, current: dict) -> dict:
    """Pull contact-card fields out of text the user supplies (a pasted website
    footer, a Google result, an email signature, call notes).

    This model has NO web access, so it is strictly an extractor: everything it
    returns must be present in `free_text`. A fabricated phone number is worse
    than a blank one, hence the hard rules below and the post-filter that drops
    any value which doesn't actually appear in the source text.
    """
    field_lines = "\n".join(f"- {k}: {hint}" for k, hint in _CARD_FIELD_HINTS.items())
    known = {k: current.get(k) for k in _CARD_FIELD_HINTS if current.get(k) not in (None, "")}

    system = (
        "You extract a card shop's contact details from text the user pasted, and "
        "return ONLY a JSON object. No commentary. Exact shape:\n"
        '{"fields": {<field>: <value>}, "summary": "<one short sentence>"}\n'
        "Rules:\n"
        "- Every value MUST appear in the supplied text. You have no other knowledge.\n"
        "- NEVER guess, complete, or infer a phone number, email, handle or address. "
        "If it is not written in the text, leave the field out entirely.\n"
        "- Only include a field if the text gives new or corrected info for it.\n"
        "- Values are plain strings. Strip labels like 'Phone:' from the value.\n\n"
        "Fields:\n" + field_lines
    )
    prompt = (
        f"Already on the card (skip unless the text corrects it):\n"
        f"{json.dumps(known, ensure_ascii=False)}\n\n"
        f"Pasted text:\n{free_text}\n\n"
        "Return the JSON object now."
    )

    raw = generate(prompt, system=system, max_tokens=500)
    parsed = _parse_json(raw)
    if not isinstance(parsed, dict):
        return {"fields": {}, "summary": ""}
    fields = parsed.get("fields") or {}
    if not isinstance(fields, dict):
        fields = {}

    # Grounding check: a value only survives if its characters really are in the
    # source. Digits are compared separately so "(214) 238-0302" still matches
    # "2142380302" in the text, while an invented number is dropped.
    src = (free_text or "").lower()
    src_digits = re.sub(r"\D", "", src)
    clean = {}
    for k, v in fields.items():
        if k not in _CARD_FIELD_HINTS or v in (None, ""):
            continue
        val = str(v).strip()
        if not val:
            continue
        probe = val.lower().lstrip("@").replace("http://", "").replace("https://", "").replace("www.", "")
        digits = re.sub(r"\D", "", val)
        grounded = probe in src or (len(digits) >= 7 and digits in src_digits)
        if not grounded:
            continue
        clean[k] = val
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

If the user wants EACH alert in its OWN separate folder, emit one set_folder per
alert giving each a DISTINCT folder name based on that alert's card (use its query
text, e.g. folder "Cooper Flagg Bowman Chrome Auto /5" for that alert) — every
alert gets a unique folder, none shared.

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


_MASTER_FILTER_KEYS = {
    "q": "free-text search across name/city/owner/address; use this alone for a specific named shop",
    "state": "US state as the 2-LETTER code (e.g. 'TX', 'CA', 'NY')",
    "store_type": "store type text (e.g. 'Storefront')",
    "verification": "verification status text",
    "metro": "metro area name",
    "price_tier": "price tier, 1-5",
    "contacted": "'yes' or 'no' (whether we've contacted them)",
    "active": "'yes' or 'no'",
    "min_rating": "minimum Google rating, a number",
    "min_reviews": "minimum number of reviews, an integer",
    "sort": "one of: name | rating | reviews | state",
    "flags": ("array of required-present attributes, any of: website,email,phone,instagram,"
              "facebook,whatnot,ebay,psa,beckett,sgc,cgc,comc,sports,pokemon,tcg,memorabilia,"
              "wax,highend,buying,auto,show,appt"),
}


def nl_to_master_filters(question: str) -> dict:
    """Turn a natural-language question into structured master-shop filters (JSON)."""
    keys = "\n".join(f"- {k}: {h}" for k, h in _MASTER_FILTER_KEYS.items())
    system = (
        "You convert a question about a sports-card shop database into a JSON filter object. "
        "Return ONLY JSON, no commentary. Include only keys the question implies; omit the rest. "
        "Use the EXACT key names below.\n\n" + keys + "\n\n"
        "IMPORTANT: for a question about ONE specific named shop, put ONLY the name in 'q'.\n\n"
        "Examples:\n"
        '"top rated PSA dealers in Texas I haven\'t contacted" -> {"state":"TX","flags":["psa"],"contacted":"no","sort":"rating"}\n'
        '"shops with 100+ reviews that sell sealed wax" -> {"min_reviews":100,"flags":["wax"]}\n'
        '"pokemon shops in the Dallas metro" -> {"metro":"Dallas-Fort Worth","flags":["pokemon"]}\n'
        '"tell me about Burbank Sportscards" -> {"q":"Burbank Sportscards"}'
    )
    parsed = _parse_json(generate(question, system=system, max_tokens=300))
    return parsed if isinstance(parsed, dict) else {}


# --- Flyers: AI art-directs a flyer, the browser renders it ---------------

# The renderer owns layout, so the model only picks a template and writes the
# words. Diffusion models cannot spell a phone number reliably, and free-form
# x/y coordinates from an LLM collide and overflow — this split keeps the text
# crisp and the layout sane while still letting AI do the design thinking.
FLYER_TEMPLATES = ("poster", "hero", "split", "grid")

_FLYER_SYSTEM = """You are a graphic designer for a sports-card shop.
Return ONLY a JSON object, no prose, no markdown fence, with these keys:
  "template":  one of "poster" (full-bleed photo, text over it), "hero" (photo
               on top, text below), "split" (photo one side, text the other),
               "grid" (2-4 photos in a grid, text above/below).
  "headline":  4 words max, ALL CAPS, the hook.
  "subhead":   one short line under the headline, or "".
  "bullets":   0-4 very short lines (features, players, prices).
  "price":     a short price/offer string like "$1,200" or "WE PAY CASH", or "".
  "cta":       short call to action, e.g. "DM TO CLAIM".
  "contact":   the contact line, or "".
  "palette":   {"bg": hex, "accent": hex, "text": hex} — high contrast, bg dark
               unless asked otherwise, accent used for the price and CTA.
Keep every string short enough to fit on a flyer. Never invent prices, dates,
player names or contact details that were not given to you."""


def design_flyer(brief: str, photo_count: int = 1, contact: str = "") -> dict:
    """Turn a plain-English brief into a flyer spec the canvas renderer draws."""
    prompt = (f"Flyer brief: {brief}\n"
              f"Photos supplied: {photo_count}\n"
              f"Contact line to use: {contact or '(none given)'}\n"
              "Design the flyer.")
    raw = generate(prompt, system=_FLYER_SYSTEM, max_tokens=700)
    spec = _parse_json(raw) or {}

    tmpl = str(spec.get("template") or "").lower().strip()
    if tmpl not in FLYER_TEMPLATES:
        # Pick by photo count rather than failing — more photos want the grid.
        tmpl = "grid" if photo_count > 1 else "poster"
    pal = spec.get("palette") if isinstance(spec.get("palette"), dict) else {}

    def hexval(v, fallback):
        v = str(v or "").strip()
        return v if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else fallback

    bullets = [str(b).strip() for b in (spec.get("bullets") or []) if str(b).strip()][:4]
    return {
        "template": tmpl,
        "headline": str(spec.get("headline") or "").strip()[:40],
        "subhead": str(spec.get("subhead") or "").strip()[:70],
        "bullets": bullets,
        "price": str(spec.get("price") or "").strip()[:24],
        "cta": str(spec.get("cta") or "").strip()[:36],
        "contact": (str(spec.get("contact") or "").strip() or contact)[:60],
        "palette": {
            "bg": hexval(pal.get("bg"), "#0b1220"),
            "accent": hexval(pal.get("accent"), "#f5b301"),
            "text": hexval(pal.get("text"), "#ffffff"),
        },
    }


# --- Alert batch builder ---------------------------------------------------

_RUN_SYSTEM = """You normalize sports-card parallel/insert names for a search builder.
Return ONLY a JSON object: {"runs": [ ... ]}, no prose, no code fences.
Each run is an object:
  "label":       tidy display name, title case, e.g. "Black /10"
  "insert":      the insert or parallel WORDS only, no serial, e.g. "Black",
                 "Alter Ego", "Minions", "Shadow Etch". "" if the run is only a serial.
  "numbered_to": the print run as an integer if the name states one (the N in
                 /N or "numbered to N"), else null.
Rules:
- "black /10" -> {"label":"Black /10","insert":"Black","numbered_to":10}
- "alter ego" -> {"label":"Alter Ego","insert":"Alter Ego","numbered_to":null}
- "superfractor 1/1" -> {"label":"Superfractor 1/1","insert":"Superfractor","numbered_to":1}
- Keep the seller's wording; do NOT invent parallels the user didn't name.
- Singular vs plural: use the form sellers actually type in listing titles."""


def parse_card_runs(text: str) -> list:
    """Turn a messy list of parallels ("black /10, alter ego, minions") into
    structured runs. The combinations are built in code — this only cleans up
    the names and pulls out serials, which is the part that needs judgement."""
    raw = (text or "").strip()
    if not raw:
        return []
    out = _parse_json(generate(f"Parallels/inserts:\n{raw}\n\nNormalize them.",
                               system=_RUN_SYSTEM, max_tokens=700)) or {}
    runs = []
    for r in (out.get("runs") or []):
        if not isinstance(r, dict):
            continue
        label = str(r.get("label") or "").strip()[:48]
        insert = str(r.get("insert") or "").strip()[:48]
        n = r.get("numbered_to")
        try:
            n = int(n) if n not in (None, "", "null") else None
        except (TypeError, ValueError):
            n = None
        if label or insert:
            runs.append({"label": label or insert, "insert": insert, "numbered_to": n})
    if runs:
        return runs
    # The model failed or returned nothing usable — fall back to splitting the
    # raw text so the builder still works rather than silently producing zero.
    import re as _re
    for part in _re.split(r"[,\n]+", raw):
        part = part.strip()
        if not part:
            continue
        m = _re.search(r"/\s*(\d+)", part)
        runs.append({"label": part[:48],
                     "insert": _re.sub(r"\s*/\s*\d+", "", part).strip()[:48],
                     "numbered_to": int(m.group(1)) if m else None})
    return runs


_PHOTO_ALERT_SYSTEM = """You turn ONE identified trading card into the keywords for a saved eBay alert.

How the alert works — this is why keyword choice matters:
- The alert searches eBay newest-first, then throws away every listing whose TITLE does not contain EVERY word you put in "query".
- So each extra word is a filter that can silently kill the alert. A word that sellers phrase differently ("Chrome" when the title says only "Bowman", "Autographs" when the title says "Auto") makes the alert match nothing.
- The goal is the BROADEST query that still describes this card's family — usually the player plus the product family. 2-4 words. Not the exact card.

Rules:
1. "query": 2-4 words. Prefer "<Player> <Brand family>" (e.g. "Stephen Curry Bowman", "Cooper Flagg Topps Chrome"). If there is no player (a set-wide chase alert), use the product family plus the chase word sellers actually type ("Topps Chrome Superfractor").
2. Use the SHORT brand family, not the full product name: "Bowman" not "Bowman Chrome Sapphire Edition"; "Topps Chrome" not "Topps Chrome Update Series".
3. NEVER put these in "query": the parallel/color name (Black, Gold, Refractor, Sapphire...), the insert name, the card number, a grade (PSA 10), the year/season, or a "/N" serial. They are how sellers vary titles most, and each one is a hard filter. The price floor does the narrowing instead.
4. "numbered_to": only set it when the user's description explicitly asks for one exact print run (e.g. "only /10"). Otherwise null. It forces "/N" to appear in the title.
5. "min_price": the floor in dollars. Default 1000. Raise it (2500/5000) when the card is high-end and the user wants only big cards; lower it (250/500) only if the user asks for cheaper copies.
6. "sport": Basketball, Baseball, Football, Hockey, Soccer, or null for Pokemon/TCG/other. It filters by eBay's Sport category, not by title words, so it is safe.
7. "include_auctions": true only if the user's description mentions auctions/bidding.
8. "priority": true if the description says it is a new/hot release or asks to be told fast.
9. "folder": a short human label for grouping, e.g. "Stephen Curry Bowman".
10. Obey the user's description when it conflicts with these defaults — they know their cards.

Return ONLY this JSON object:
{
  "query": "the keywords",
  "sport": "Basketball or null",
  "min_price": 1000,
  "numbered_to": null,
  "include_auctions": false,
  "priority": false,
  "folder": "short label",
  "reason": "one sentence on why these words and what the alert will catch",
  "left_out": ["Black Refractor — parallel names vary by seller", "..."]
}"""


def alert_from_card(card: dict, notes: str = "") -> dict:
    """Turn an identified card (+ the user's own description) into a draft alert.

    Returns the spec dict; {} if the model fails, so the caller can fall back to
    something built from the identification alone rather than showing an error.
    """
    ident = {k: card.get(k) for k in
             ("player", "sport", "year", "brand", "card_number", "parallel",
              "is_graded", "grader", "grade", "search_query", "notes")
             if card.get(k) not in (None, "", False)}
    prompt = (f"Identified card:\n{json.dumps(ident, indent=2)}\n\n"
              f"What the user said they want:\n{(notes or '(nothing — use your judgement)').strip()[:600]}\n\n"
              "Build the alert.")
    out = _parse_json(generate(prompt, system=_PHOTO_ALERT_SYSTEM, max_tokens=500)) or {}
    return out if isinstance(out, dict) else {}


_ALERT_CHAT_SYSTEM = """You are the alert assistant for a sports-card watcher. The user tells you, in plain English, which cards they want to be told about; you propose the alerts that will catch them.

HOW AN ALERT WORKS (this is why keyword choice matters):
- It searches eBay newest-first, then discards every listing whose TITLE does not contain EVERY word in the alert's query.
- So each extra word is a filter that can silently kill the alert. Words sellers phrase differently ("Chrome" when the title says only "Bowman", "Autographs" vs "Auto") make it match nothing.
- Aim for the BROADEST query that still describes the card family: usually "<Player> <Brand family>", 2-4 words. The price floor does the narrowing, not the keywords.
- NEVER put in a query: parallel/color names (Black, Gold, Refractor, Sapphire), insert names, card numbers, grades (PSA 10), the year/season, or "/N" serials.
- "sport" filters by eBay's category, not by title words, so it is always safe: Basketball, Baseball, Football, Hockey, Soccer, or null.

YOUR JOB each turn:
- If the request is clear, propose the alerts. One proposal per card family — do not emit five near-identical alerts for five parallels of the same card; one broad alert with a price floor catches them all.
- If it is genuinely ambiguous (which player? how expensive?), ask ONE short question and propose nothing.
- If they ask a question about their existing alerts, answer it in "reply" and propose nothing.
- You may also propose changes to the alerts they already have (raise a floor, speed one up, remove one).
- Never propose an alert whose query duplicates an existing alert; say so in "reply" instead.

Return ONLY this JSON:
{
  "reply": "what you're doing, or your one question, in 1-2 friendly sentences",
  "proposals": [
    {"op": "create", "query": "Stephen Curry Bowman", "sport": "Basketball", "min_price": 1000,
     "numbered_to": null, "include_auctions": false, "priority": false,
     "interval_minutes": 60, "folder": "Curry Bowman", "why": "one line"},
    {"op": "update", "id": 12, "fields": {"min_price": 2500}, "why": "one line"},
    {"op": "delete", "id": 34, "why": "one line"}
  ]
}

Defaults for a create: min_price 1000 (raise to 2500/5000 for high-end-only, lower only if asked), interval_minutes 60, priority false. Set priority true and interval_minutes 10 only for a new/hot release or when they ask to hear fast. numbered_to only when they explicitly want one exact print run. include_auctions true only if they mention auctions or bidding. Use only ids that exist in the list you are given."""


def plan_alert_chat(alerts: list, messages: list) -> dict:
    """Conversational alert building: the user's chat history + their current
    alerts -> {"reply": str, "proposals": [...]}. Proposals are NOT applied here;
    the caller checks each one against live eBay and the user confirms."""
    compact = [{"id": a.get("id"), "query": a.get("query"), "folder": a.get("folder"),
                "min_price": a.get("min_price"), "sport": a.get("sport"),
                "interval_min": a.get("check_interval_minutes"),
                "priority": a.get("priority")} for a in alerts][:80]
    convo = "\n".join(f"{m.get('role', 'user').upper()}: {str(m.get('content') or '').strip()[:800]}"
                      for m in messages[-10:])
    prompt = (f"The user's existing alerts (JSON):\n{json.dumps(compact, indent=2)}\n\n"
              f"Conversation so far:\n{convo}\n\nRespond with the JSON object.")
    out = _parse_json(generate(prompt, system=_ALERT_CHAT_SYSTEM, max_tokens=900))
    if not isinstance(out, dict):
        return {"reply": "Sorry — I didn't follow that. Try naming the player and roughly what you'd pay.",
                "proposals": []}
    out.setdefault("reply", "")
    props = out.get("proposals")
    out["proposals"] = props if isinstance(props, list) else []
    return out


_AUDIENCE_SYSTEM = """You pick who a text message should go to, from a list of people a card-buying business has texted before.

Each person is given as a numbered line with whatever is known: what they are (shop, breaker, collector, seller), where they are, free-text notes, and how many days since the last message either way.

Return ONLY this JSON:
{"pick": [1, 4, 9], "reason": "one short sentence naming the rule you used"}

Rules:
- Include someone only if they genuinely fit the request. A text costs money and goodwill; a wrong recipient is worse than a missing one.
- "shops", "breakers", "collectors" refer to the contact type. Locations may be written as a city, a state, or an abbreviation — match them sensibly.
- "haven't heard from", "gone quiet", "old leads" refer to days since last contact.
- If the request names no filter at all ("everyone", "the whole inbox"), pick everyone.
- If nothing fits, return an empty pick and say so in the reason."""


def pick_sms_audience(people: list, instruction: str) -> dict:
    """Choose which inbox contacts match a plain-English audience description.

    Returns {"pick": [index, ...], "reason": str} using 1-based indexes into
    `people`, each of which is a dict with name/type/location/notes/days_since.
    """
    lines = []
    for i, p in enumerate(people, 1):
        bits = [x for x in [
            p.get("name") or "unnamed",
            p.get("contact_type"),
            p.get("location"),
            (p.get("notes") or "")[:70] or None,
            f"{p['days_since']}d since last message" if p.get("days_since") is not None else None,
        ] if x]
        lines.append(f"{i}. " + " | ".join(bits))
    prompt = (f"People:\n" + "\n".join(lines) +
              f"\n\nWho should get this message?\n{instruction.strip()}")
    out = _parse_json(generate(prompt, system=_AUDIENCE_SYSTEM, max_tokens=800)) or {}
    picks = out.get("pick")
    if not isinstance(picks, list):
        picks = []
    clean = []
    for x in picks:
        try:
            n = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= len(people):
            clean.append(n)
    return {"pick": sorted(set(clean)), "reason": str(out.get("reason") or "").strip()}


_TAILOR_SYSTEM = """You write ONE outbound SMS for 26 Buys, a business that BUYS sports trading cards from shops, breakers and collectors. You are the buyer, not the seller.

You are given what the message needs to say, plus what is known about the person and the last few messages exchanged with them. Write the version of that message that fits THIS person.

Rules:
- Under 280 characters. No subject line, no signature, no emoji, no exclamation marks.
- Plain and direct, the way one dealer texts another.
- Use their first name only if it is known and it reads naturally.
- You may refer to something specific from the thread when it is genuinely relevant; never invent history, prices, offers, or claims about payment or shipping.
- If there is no history, write a clean cold text that says who we are.
- Say the thing the instruction asks for. Do not add unrelated asks.
- Output only the message text, nothing else."""


def tailor_sms(instruction: str, person: dict, thread: str = "") -> str:
    """Write one person's version of a campaign message. Returns "" on failure so
    the caller can drop that recipient rather than send something generic."""
    about = ", ".join(x for x in [
        f"name: {person.get('name')}" if person.get("name") else None,
        f"type: {person.get('contact_type')}" if person.get("contact_type") else None,
        f"location: {person.get('location')}" if person.get("location") else None,
        f"notes: {person.get('notes')}" if person.get("notes") else None,
        f"{person['days_since']} days since the last message" if person.get("days_since") is not None else None,
    ] if x)
    prompt = (f"What the message needs to say:\n{instruction.strip()}\n\n"
              f"About them: {about or 'nothing known'}\n\n"
              + (f"Recent messages:\n{thread}\n\n" if thread else "No history with them yet.\n\n")
              + "Write our text to them.")
    try:
        return (generate(prompt, system=_TAILOR_SYSTEM, max_tokens=220) or "").strip().strip('"')
    except Exception as e:
        print(f"tailor_sms failed for {person.get('phone')}: {e}")
        return ""


_INTERVAL_SYSTEM = """You set how often each of a card collector's eBay alerts is checked.

You are given every alert with: how often it is checked now, whether it is a priority (new-release) watch, its price floor, how many times it has ever alerted, and how long since it last matched anything.

What matters, in order:
1. A card that lists and SELLS between two checks is lost forever — eBay drops ended listings from search, so no later sweep can find it. Fast-moving, high-value chase cards (superfractors, 1/1s, big autos, anything with a high price floor) are the ones worth checking often.
2. An alert that has never matched anything, or hasn't matched in months, does not deserve a fast lane. Slow it down and spend the budget elsewhere.
3. Broad or low-value alerts can be checked slowly without losing much.

Intervals must be one of: 3, 10, 30, 60, 180, 360, 720, 1440 minutes.
Never propose faster than 3. Do not change an alert unless there is a reason.

Return ONLY this JSON:
{
  "reply": "1-2 sentences on the trade you're making",
  "changes": [{"id": 12, "minutes": 60, "why": "one short reason"}]
}

Cost is not your problem — propose what the cards deserve and the caller will fit it to the budget. Just don't propose 3 minutes for everything; being deliberate about which alerts are fast is the entire job."""


def plan_alert_intervals(alerts: list, instruction: str = "") -> dict:
    """Propose a check interval per alert. Returns {"reply", "changes": [...]}.

    Budget arithmetic is deliberately NOT done here — the caller enforces it,
    so a hallucinated number can never overspend the eBay quota.
    """
    lines = []
    for a in alerts:
        bits = [f"id {a['id']}", f"“{a['query']}”", f"every {a['interval']:.0f}min"]
        if a.get("priority"):
            bits.append("PRIORITY")
        if a.get("min_price"):
            bits.append(f"floor ${a['min_price']:,.0f}")
        bits.append(f"{a.get('alerts_sent', 0)} alerts ever")
        bits.append("never matched" if a.get("days_since_match") is None
                    else f"last match {a['days_since_match']}d ago")
        lines.append(" | ".join(bits))
    prompt = ("Alerts:\n" + "\n".join(lines) + "\n\n"
              + (f"What they asked for: {instruction.strip()}\n\n" if instruction.strip() else "")
              + "Propose the intervals.")
    out = _parse_json(generate(prompt, system=_INTERVAL_SYSTEM, max_tokens=1200))
    if not isinstance(out, dict):
        return {"reply": "Couldn't work out a plan — try saying it differently.", "changes": []}
    out.setdefault("reply", "")
    ch = out.get("changes")
    out["changes"] = ch if isinstance(ch, list) else []
    return out
