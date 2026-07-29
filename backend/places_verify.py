"""Verify a shop against Google Places: is it real, still open, and what are its
current rating/phone/website/hours. Used to triage the New Shops List so a human
only has to manually check the ones Google can't resolve.

Needs env GOOGLE_PLACES_API_KEY (enable "Places API" on the GCP project). Dormant
until that's set.
"""
import os
import re
import httpx

KEY_ENV = "GOOGLE_PLACES_API_KEY"
_FIND = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
_DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"


def places_enabled() -> bool:
    return bool(os.getenv(KEY_ENV))


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


async def verify_shop(shop: dict) -> dict:
    """Look one shop up on Google Places. Returns a verdict + fresh fields.
    verdict ∈ {open, closed, temp_closed, not_found, uncertain, error, disabled}."""
    key = os.getenv(KEY_ENV)
    if not key:
        return {"verdict": "disabled"}
    name = (shop.get("name") or "").strip()
    loc = " ".join(x for x in [shop.get("street_address"), shop.get("city"),
                               shop.get("state"), shop.get("zip_code")] if x)
    query = f"{name} {loc}".strip()
    if not query:
        return {"verdict": "not_found"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
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
        "verdict": verdict, "matched_name": matched, "google_status": status,
        "rating": info.get("rating"), "reviews": info.get("user_ratings_total"),
        "phone": info.get("formatted_phone_number"), "website": info.get("website"),
        "hours": hours, "address": info.get("formatted_address"),
        "place_id": pid, "maps_url": maps_url,
    }
