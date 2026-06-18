import httpx
import base64
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

APP_ID = os.getenv("EBAY_APP_ID", "")
CERT_ID = os.getenv("EBAY_CERT_ID", "")

_token_cache = {"token": None, "expires_at": 0}


async def _get_token() -> str:
    import time
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
    # Drop card-number tokens like #CPA-JDE and stray symbols
    import re
    cleaned = re.sub(r"#\S+", "", query)          # remove #card-numbers
    cleaned = re.sub(r"[^\w\s\-/]", " ", cleaned)  # strip odd symbols
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


async def _do_search(token: str, q: str, min_price, max_price, limit: int):
    filt = "buyingOptions:{FIXED_PRICE}"
    if min_price:
        filt += f",price:[{min_price}]"
    if max_price:
        filt += f",price:[..{max_price}]"
    params = {
        "q": q,
        "category_ids": "212",
        "limit": str(min(limit, 50)),
        "sort": "newlyListed",
        "filter": filt,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params=params,
        )
        return resp.json()


async def search_cards(query: str, min_price=None, max_price=None, limit: int = 50):
    token = await _get_token()

    # Try the query as-is first
    data = await _do_search(token, query, min_price, max_price, limit)

    # If eBay returned an error (e.g. rate limit), stop — retrying with fallback
    # queries only burns more quota and digs the hole deeper.
    if data.get("errors"):
        print(f"eBay search error for '{query}': {data['errors']}")
        return []

    # Fallback 1: clean out card-numbers / symbols
    if not data.get("itemSummaries"):
        cleaned = _clean_query(query)
        if cleaned and cleaned != query:
            data = await _do_search(token, cleaned, min_price, max_price, limit)

    # Fallback 2: use just the first 6 words (player + set)
    if not data.get("itemSummaries") and not data.get("errors"):
        words = _clean_query(query).split()
        if len(words) > 6:
            data = await _do_search(token, " ".join(words[:6]), min_price, max_price, limit)

    results = []
    for item in data.get("itemSummaries", []):
        results.append({
            "source": "ebay",
            "external_id": item.get("itemId", ""),
            "title": item.get("title", ""),
            "price": float(item.get("price", {}).get("value", 0)),
            "listing_url": item.get("itemWebUrl", ""),
            "image_url": item.get("image", {}).get("imageUrl"),
            "seller_name": item.get("seller", {}).get("username"),
            "condition": item.get("condition"),
            "is_sold": False,
        })
    return results


async def get_sold_history(query: str, limit: int = 20):
    token = await _get_token()

    async def _sold(q):
        params = {
            "q": q,
            "category_ids": "212",
            "limit": str(min(limit, 50)),
            "filter": "buyingOptions:{FIXED_PRICE},soldItems:true",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.ebay.com/buy/browse/v1/item_summary/search",
                headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
                params=params,
            )
            return resp.json()

    data = await _sold(query)
    if data.get("errors"):
        return []
    if not data.get("itemSummaries"):
        cleaned = _clean_query(query)
        if cleaned and cleaned != query:
            data = await _sold(cleaned)

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
    return sold
