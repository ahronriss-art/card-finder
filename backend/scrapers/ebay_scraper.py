import httpx
import base64
import os
import time
import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

APP_ID = os.getenv("EBAY_APP_ID", "")
CERT_ID = os.getenv("EBAY_CERT_ID", "")

_token_cache = {"token": None, "expires_at": 0}

# --- Quota protection ----------------------------------------------------
# eBay's Browse API allows ~5000 calls/day (shared across the whole app and
# resetting at midnight Pacific). We protect that budget three ways:
#   1. Cache search/sold results so repeated or identical queries (incl. the
#      same card watched by multiple users) don't each hit eBay.
#   2. A daily safety cap that gracefully stops calling eBay before the real
#      limit, so we degrade (slightly stale results) instead of hard-erroring.
SEARCH_TTL = 600          # 10 min: reuse identical search results within this window
SOLD_TTL = 6 * 3600       # 6 h: sold prices move slowly
DAILY_CALL_CAP = 4500     # stay safely under eBay's ~5000/day

_search_cache: dict = {}  # key -> (expires_at, results)
_sold_cache: dict = {}    # query -> (expires_at, results)
_usage = {"day": "", "count": 0}


def _pacific_day() -> str:
    # Approx Pacific date (UTC-8) so our counter resets no earlier than eBay's.
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=8)).strftime("%Y-%m-%d")


def _budget_available() -> bool:
    day = _pacific_day()
    if _usage["day"] != day:
        _usage["day"] = day
        _usage["count"] = 0
    return _usage["count"] < DAILY_CALL_CAP


def usage_status() -> dict:
    """Current day's eBay call count vs the safety cap (for diagnostics)."""
    _budget_available()  # refresh day rollover
    return {"day": _usage["day"], "calls": _usage["count"], "cap": DAILY_CALL_CAP,
            "remaining": max(0, DAILY_CALL_CAP - _usage["count"])}


async def _get_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    credentials = base64.b64encode(f"{APP_ID}:{CERT_ID}".encode()).decode()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
        )
        data = resp.json()
        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 7200)
    return _token_cache["token"]


def _clean_query(query: str) -> str:
    """Remove characters that break eBay search and trim length."""
    import re
    cleaned = re.sub(r"#\S+", "", query)          # remove #card-numbers
    cleaned = re.sub(r"[^\w\s\-/]", " ", cleaned)  # strip odd symbols
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


_BUDGET_ERROR = {"errors": [{"errorId": 0, "domain": "LOCAL",
                             "message": "Daily eBay call budget reached (local safety cap)"}]}


async def _ebay_get(token: str, params: dict) -> dict:
    """One Browse API search call, counted against the daily budget."""
    if not _budget_available():
        return _BUDGET_ERROR
    _usage["count"] += 1
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params=params,
        )
        return resp.json()


async def _do_search(token: str, q: str, min_price, max_price, limit: int, include_auctions: bool = False):
    opts = "FIXED_PRICE|AUCTION" if include_auctions else "FIXED_PRICE"
    filt = f"buyingOptions:{{{opts}}}"
    # Only push a price filter to eBay for pure fixed-price searches. When auctions
    # are included we filter price in code so auctions (low current bid) aren't dropped.
    if not include_auctions:
        if min_price:
            filt += f",price:[{min_price}]"
        if max_price:
            filt += f",price:[..{max_price}]"
    return await _ebay_get(token, {
        "q": q,
        "category_ids": "212",
        "limit": str(min(limit, 50)),
        "sort": "newlyListed",
        "filter": filt,
    })


async def search_cards(query: str, min_price=None, max_price=None, limit: int = 50, include_auctions: bool = False):
    # Serve from cache when possible — this is what de-dups the same card watched
    # by many users and avoids re-calling eBay every cycle.
    key = (str(query).strip().lower(), min_price, max_price, limit, include_auctions)
    hit = _search_cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1]

    token = await _get_token()

    # Try the query as-is first
    data = await _do_search(token, query, min_price, max_price, limit, include_auctions)

    # If eBay returned an error (rate limit / budget cap), stop — retrying with
    # fallback queries only burns more quota. Don't cache errors.
    if data.get("errors"):
        print(f"eBay search skipped for '{query}': {data['errors']}")
        return []

    # Fallback 1: clean out card-numbers / symbols
    if not data.get("itemSummaries"):
        cleaned = _clean_query(query)
        if cleaned and cleaned != query:
            data = await _do_search(token, cleaned, min_price, max_price, limit, include_auctions)

    # Fallback 2: use just the first 6 words (player + set)
    if not data.get("itemSummaries") and not data.get("errors"):
        words = _clean_query(query).split()
        if len(words) > 6:
            data = await _do_search(token, " ".join(words[:6]), min_price, max_price, limit, include_auctions)

    if data.get("errors"):
        return []

    results = []
    for item in data.get("itemSummaries", []):
        bo = item.get("buyingOptions", []) or []
        results.append({
            "source": "ebay",
            "external_id": item.get("itemId", ""),
            "title": item.get("title", ""),
            "price": float(item.get("price", {}).get("value", 0)),
            "is_auction": "AUCTION" in bo,
            "created_at": item.get("itemCreationDate"),  # when the listing was posted (ISO)
            "listing_url": item.get("itemWebUrl", ""),
            "image_url": item.get("image", {}).get("imageUrl"),
            "seller_name": item.get("seller", {}).get("username"),
            "condition": item.get("condition"),
            "is_sold": False,
        })
    _search_cache[key] = (time.time() + SEARCH_TTL, results)
    return results


async def get_sold_history(query: str, limit: int = 20):
    key = str(query).strip().lower()
    hit = _sold_cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1]

    token = await _get_token()

    async def _sold(q):
        return await _ebay_get(token, {
            "q": q,
            "category_ids": "212",
            "limit": str(min(limit, 50)),
            "filter": "buyingOptions:{FIXED_PRICE},soldItems:true",
        })

    data = await _sold(query)
    if data.get("errors"):
        return []
    if not data.get("itemSummaries"):
        cleaned = _clean_query(query)
        if cleaned and cleaned != query:
            data = await _sold(cleaned)
    if data.get("errors"):
        return []

    sold = []
    for item in data.get("itemSummaries", []):
        price = float(item.get("price", {}).get("value", 0))
        if price:
            sold.append({
                "source": "ebay",
                "external_id": item.get("itemId", ""),
                "title": item.get("title", ""),
                "sold_price": price,
                "listing_url": item.get("itemWebUrl", ""),
                "image_url": item.get("image", {}).get("imageUrl"),
                "sold_at": item.get("itemEndDate", ""),
                "is_sold": True,
            })
    _sold_cache[key] = (time.time() + SOLD_TTL, sold)
    return sold
