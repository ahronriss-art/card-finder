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
