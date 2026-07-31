"""Is a shop real, still open, and what are its current rating/phone/website/hours?

Two checkers, used as a chain by `verify_shop_full`:
  1. Google Places — authoritative (`business_status: CLOSED_PERMANENTLY`), needs
     GOOGLE_PLACES_API_KEY (enable "Places API" on the GCP project).
  2. Claude with web search — the fallback for the shops Google can't resolve
     (not_found / uncertain), or for everything when Places isn't configured.
     Needs ANTHROPIC_API_KEY.

Each checker is dormant until its key is set, so the chain degrades to whichever
one is available.
"""
import json
import os
import re
import httpx

KEY_ENV = "GOOGLE_PLACES_API_KEY"
_FIND = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
_DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"

# Claude only gets to auto-close a shop when it says it's this sure. Below it the
# verdict is downgraded to "uncertain" so a human looks instead.
AI_CLOSE_CONFIDENCE = 0.8


def places_enabled() -> bool:
    return bool(os.getenv(KEY_ENV))


def ai_enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _location(shop: dict) -> str:
    """Best address string we have — master shops store the parts, card_shops the whole."""
    parts = [shop.get("street_address") or shop.get("full_address"),
             shop.get("city"), shop.get("state"), shop.get("zip_code")]
    out = []
    for p in parts:
        p = str(p or "").strip()
        # full_address usually already contains the city/state/zip — don't repeat them.
        if p and _norm(p) not in _norm(" ".join(out)):
            out.append(p)
    return " ".join(out)


async def verify_shop(shop: dict) -> dict:
    """Look one shop up on Google Places. Returns a verdict + fresh fields.
    verdict ∈ {open, closed, temp_closed, not_found, uncertain, error, disabled}."""
    key = os.getenv(KEY_ENV)
    if not key:
        return {"verdict": "disabled"}
    name = (shop.get("name") or "").strip()
    query = f"{name} {_location(shop)}".strip()
    if not query:
        return {"verdict": "not_found"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            # A place_id from a previous check skips the (billed) text search.
            cand, pid = {}, (shop.get("place_id") or "").strip() or None
            if not pid:
                r = await c.get(_FIND, params={
                    "input": query, "inputtype": "textquery",
                    "fields": "place_id,name,business_status,rating,user_ratings_total,formatted_address",
                    "key": key})
                d = r.json()
                if d.get("status") not in ("OK", "ZERO_RESULTS"):
                    return {"verdict": "error", "google_status": d.get("status"), "error": d.get("error_message")}
                cands = d.get("candidates") or []
                if not cands:
                    return {"verdict": "not_found"}
                cand = cands[0]
                pid = cand.get("place_id")
            det = {}
            if pid:
                r2 = await c.get(_DETAILS, params={
                    "place_id": pid,
                    "fields": "name,business_status,rating,user_ratings_total,"
                              "formatted_phone_number,website,opening_hours,formatted_address",
                    "key": key})
                det = (r2.json().get("result") or {})
    except Exception as e:
        return {"verdict": "error", "error": str(e)[:200]}

    # A stored place_id that no longer resolves: drop it and search by name instead.
    if not det and not cand and shop.get("place_id"):
        return await verify_shop({**shop, "place_id": None})

    info = {**cand, **det}
    status = info.get("business_status") or "OPERATIONAL"
    matched = info.get("name") or ""
    # Loose name-match guard so a wrong nearby business doesn't get trusted.
    a, b = set(_norm(name).split()), set(_norm(matched).split())
    overlap = len(a & b)
    name_ok = bool(a) and (overlap >= 2 or overlap / max(1, len(a)) >= 0.5
                           or _norm(matched) in _norm(name) or _norm(name) in _norm(matched))

    if status == "CLOSED_PERMANENTLY":
        verdict = "closed"
    elif status == "CLOSED_TEMPORARILY":
        verdict = "temp_closed"
    elif not name_ok:
        verdict = "uncertain"
    else:
        verdict = "open"

    hours = "; ".join((info.get("opening_hours") or {}).get("weekday_text", [])) or None
    maps_url = f"https://www.google.com/maps/place/?q=place_id:{pid}" if pid else None
    return {
        "verdict": verdict, "source": "google",
        "matched_name": matched, "google_status": status,
        "rating": info.get("rating"), "reviews": info.get("user_ratings_total"),
        "phone": info.get("formatted_phone_number"), "website": info.get("website"),
        "hours": hours, "address": info.get("formatted_address"),
        "place_id": pid, "maps_url": maps_url,
    }


_AI_SYSTEM = (
    "You check two things about a specific trading-card / collectibles shop: whether it is "
    "still in business, and whether it sells SPORTS cards.\n"
    "Search the web for the shop by name and address: its Google listing, its own site, "
    "its Facebook/Instagram, and any local news or posts about it closing.\n"
    "Decide one verdict:\n"
    '  "closed"     - solid evidence it shut down for good (a listing marked permanently '
    "closed, an announcement that it closed, a news story, a landlord/relocation notice "
    "saying the location is gone).\n"
    '  "open"       - solid evidence it is still operating (recent posts, current hours, '
    "recent reviews, an active store page).\n"
    '  "temp_closed" - closed for now but says it is coming back (remodel, seasonal, illness).\n'
    '  "not_found"  - the web has nothing about a shop by this name at this location.\n'
    '  "uncertain"  - you found something but cannot tell whether it is still open, or you '
    "cannot tell whether what you found is the same business.\n"
    "Being wrong about a closure is worse than being unsure: if the evidence is old, "
    "indirect, or about a different location of the same chain, answer \"uncertain\". "
    "A shop with no recent activity online is NOT evidence of closure.\n"
    "Then answer whether it sells sports cards (baseball/basketball/football/hockey/soccer "
    "singles, wax, or memorabilia):\n"
    '  "yes"     - it clearly does: sports cards named on its site or listings, sports-card '
    "categories, breaks, or a sports-card category on its Google/Yelp listing.\n"
    '  "no"      - it clearly does NOT: it is Pokemon/Magic/TCG-only, comics-only, a games '
    "or hobby store with no sports-card offering, or something else entirely.\n"
    '  "unknown" - you cannot tell from what you found.\n'
    "A shop selling both TCG and sports is a \"yes\". Only answer \"no\" when you actually "
    "saw what it sells and sports cards were not part of it.\n"
    "Reply with ONLY a JSON object, no prose and no code fence:\n"
    '{"verdict": "...", "confidence": 0.0-1.0, "evidence": "one sentence naming what you '
    'found and where", "sells_sports_cards": "yes|no|unknown", "products": "one short phrase '
    'on what it sells", "phone": null or "...", "website": null or "...", "hours": null or "..."}'
)


def _first_json(text: str):
    """Pull the first JSON object out of a reply (tolerates a stray code fence)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


async def ai_verify_shop(shop: dict) -> dict:
    """Ask Claude (with web search) whether this shop is still open. Fallback for the
    shops Google Places can't resolve. Same verdict vocabulary as `verify_shop`."""
    if not ai_enabled():
        return {"verdict": "disabled"}
    name = (shop.get("name") or "").strip()
    if not name:
        return {"verdict": "not_found"}
    known = {k: shop.get(k) for k in ("phone", "website", "instagram", "facebook") if shop.get(k)}
    prompt = (f"Shop name: {name}\n"
              f"Address: {_location(shop) or '(unknown)'}\n"
              + "".join(f"{k.title()}: {v}\n" for k, v in known.items())
              + "\nIs this shop still in business?")
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        resp = await client.messages.create(
            model="claude-opus-5",
            max_tokens=4000,
            system=_AI_SYSTEM,
            output_config={"effort": "low"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        return {"verdict": "error", "error": str(e)[:200]}

    if resp.stop_reason == "refusal":
        return {"verdict": "error", "error": "refused"}
    text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    parsed = _first_json(text)
    if not isinstance(parsed, dict):
        return {"verdict": "uncertain", "source": "ai", "evidence": text[:300]}

    verdict = str(parsed.get("verdict") or "uncertain").strip().lower()
    if verdict not in ("open", "closed", "temp_closed", "not_found", "uncertain"):
        verdict = "uncertain"
    try:
        confidence = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    # Only a confident AI closure counts as a closure; otherwise send it to a human.
    if verdict == "closed" and confidence < AI_CLOSE_CONFIDENCE:
        verdict = "uncertain"
    sports = str(parsed.get("sells_sports_cards") or "unknown").strip().lower()
    if sports not in ("yes", "no", "unknown"):
        sports = "unknown"
    return {
        "verdict": verdict, "source": "ai", "confidence": confidence,
        "evidence": str(parsed.get("evidence") or "")[:500],
        "sells_sports_cards": sports,
        "products": str(parsed.get("products") or "")[:300],
        "phone": parsed.get("phone"), "website": parsed.get("website"),
        "hours": parsed.get("hours"),
    }


async def verify_shop_full(shop: dict, need_products: bool = False) -> dict:
    """Google Places first; hand the ones it can't settle to the AI checker.

    Places can only answer open/closed, so `need_products=True` (we still don't know
    whether this shop sells sports cards) runs the AI pass even when Places was
    conclusive — that question has no other source."""
    res = await verify_shop(shop) if places_enabled() else {"verdict": "disabled"}
    settled = res.get("verdict") in ("open", "closed", "temp_closed")
    # A closed shop's product mix is moot — don't pay for a search to find it out.
    if res.get("verdict") == "closed":
        need_products = False
    if (settled and not need_products) or not ai_enabled():
        return res
    ai = await ai_verify_shop(shop)
    if ai.get("verdict") not in ("open", "closed", "temp_closed", "not_found", "uncertain"):
        return res  # AI errored — Google's answer, such as it is, still stands

    if settled:
        # Google already answered open/closed and it outranks the AI there. Take only
        # what Google can't tell us.
        return {**res, "sells_sports_cards": ai.get("sells_sports_cards"),
                "products": ai.get("products"), "ai_verdict": ai.get("verdict")}
    # Google couldn't settle it — the AI's verdict stands, keeping Google's extras
    # (place_id, rating, maps url) alongside.
    merged = {k: v for k, v in res.items() if k not in ("verdict", "source")}
    return {**merged, **{k: v for k, v in ai.items() if v is not None}, "google": res.get("verdict")}
