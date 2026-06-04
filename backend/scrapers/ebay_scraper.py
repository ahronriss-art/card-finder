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


async def search_cards(query: str, min_price=None, max_price=None, limit: int = 50):
    token = await _get_token()
    params = {
        "q": f"{query} card",
        "category_ids": "212",
        "limit": str(min(limit, 50)),
        "sort": "newlyListed",
        "filter": "buyingOptions:{FIXED_PRICE}",
    }
    if min_price:
        params["filter"] = params["filter"] + f",price:[{min_price}]"
    if max_price:
        params["filter"] = params["filter"] + f",price:[..{max_price}]"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.ebay.com/buy/browse/v1/item_summary/search",
            headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            params=params,
        )
        data = resp.json()

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
    params = {
        "q": f"{query} card",
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
        data = resp.json()

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
