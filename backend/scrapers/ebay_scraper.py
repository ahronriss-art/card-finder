import httpx
import os
from datetime import datetime
from typing import Optional

EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")
EBAY_BASE_URL = "https://svcs.ebay.com/services/search/FindingService/v1"


async def search_cards(query: str, min_price: Optional[float] = None, max_price: Optional[float] = None, limit: int = 50):
    """Search active eBay listings for sports cards."""
    params = {
        "OPERATION-NAME": "findItemsByKeywords",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "keywords": f"{query} sports card",
        "categoryId": "212",  # Sports Trading Cards category
        "paginationInput.entriesPerPage": str(limit),
        "sortOrder": "StartTimeNewest",
        "itemFilter(0).name": "ListingType",
        "itemFilter(0).value": "FixedPrice",
    }

    if min_price:
        params["itemFilter(1).name"] = "MinPrice"
        params["itemFilter(1).value"] = str(min_price)
    if max_price:
        idx = 2 if min_price else 1
        params[f"itemFilter({idx}).name"] = "MaxPrice"
        params[f"itemFilter({idx}).value"] = str(max_price)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(EBAY_BASE_URL, params=params)
        data = resp.json()

    results = []
    try:
        items = data["findItemsByKeywordsResponse"][0]["searchResult"][0].get("item", [])
        for item in items:
            listing = {
                "source": "ebay",
                "external_id": item["itemId"][0],
                "title": item["title"][0],
                "price": float(item["sellingStatus"][0]["currentPrice"][0]["__value__"]),
                "listing_url": item["viewItemURL"][0],
                "image_url": item.get("galleryURL", [None])[0],
                "seller_name": item.get("sellerInfo", [{}])[0].get("sellerUserName", [None])[0],
                "condition": item.get("condition", [{}])[0].get("conditionDisplayName", [None])[0],
                "listed_at": item.get("listingInfo", [{}])[0].get("startTime", [None])[0],
                "is_sold": False,
            }
            results.append(listing)
    except (KeyError, IndexError):
        pass

    return results


async def get_sold_history(query: str, limit: int = 20):
    """Get recently sold eBay listings to determine market value."""
    params = {
        "OPERATION-NAME": "findCompletedItems",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "keywords": f"{query} sports card",
        "categoryId": "212",
        "paginationInput.entriesPerPage": str(limit),
        "sortOrder": "EndTimeSoonest",
        "itemFilter(0).name": "SoldItemsOnly",
        "itemFilter(0).value": "true",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(EBAY_BASE_URL, params=params)
        data = resp.json()

    sold = []
    try:
        items = data["findCompletedItemsResponse"][0]["searchResult"][0].get("item", [])
        for item in items:
            sold.append({
                "source": "ebay",
                "external_id": item["itemId"][0],
                "title": item["title"][0],
                "sold_price": float(item["sellingStatus"][0]["currentPrice"][0]["__value__"]),
                "listing_url": item["viewItemURL"][0],
                "image_url": item.get("galleryURL", [None])[0],
                "sold_at": item.get("listingInfo", [{}])[0].get("endTime", [None])[0],
                "is_sold": True,
            })
    except (KeyError, IndexError):
        pass

    return sold
