"""Shared LLM helper using Groq's free API (OpenAI-compatible)."""
import os
import json
import re
import httpx

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


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
        "Examples:\n"
        '"top rated shops in Florida" -> {"state":"Florida","sort":"rating"}\n'
        '"shops I haven\'t contacted with over 100 reviews" -> {"contacted":"no","min_reviews":100}\n'
        '"who has a topps account and wants to wholesale" -> {"topps_fanatics":true,"willing_to_wholesale":true}'
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
        for f in ("city", "state", "rating", "reviews", "email", "phone",
                  "topps_fanatics", "willing_to_wholesale", "contacted"):
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
