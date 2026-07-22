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
_insights_token_cache = {"token": None, "expires_at": 0}
_insights_enabled = None  # None = untried, True = authorized, False = scope not granted (skip)

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

# Marketplace Insights = the ONLY eBay API with real sold-price history. It's a
# Limited Release (approval-gated at developer.ebay.com); until this app is
# granted the scope, the token request fails and we fall back to other sources.
INSIGHTS_SCOPE = "https://api.ebay.com/oauth/api_scope/buy.marketplace.insights"
MARKETPLACE_INSIGHTS_URL = "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search"

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


def seed_usage(day: str, count: int) -> None:
    """Restore today's running call count after a process restart (the live
    counter is in-memory, so without this a redeploy would reset it to 0).
    Only seeds if `day` is still the current Pacific day, and never lowers a
    count already accumulated in this process."""
    if day == _pacific_day():
        _usage["day"] = day
        _usage["count"] = max(_usage["count"], int(count or 0))


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


async def get_item_by_url(url: str) -> dict:
    """Fetch a single eBay listing's title + price from its URL (Browse getItem).
    Returns {title, price, image_url, url} or None if it can't be resolved."""
    import re
    m = re.search(r"/itm/(?:[^/]*/)?(\d{9,})", url or "") or re.search(r"[?&]item=(\d{9,})", url or "")
    if not m or not _budget_available():
        return None
    item_id = m.group(1)
    token = await _get_token()
    _usage["count"] += 1
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.ebay.com/buy/browse/v1/item/v1|{item_id}|0",
                headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            )
            if resp.status_code >= 400:
                return None
            d = resp.json()
    except Exception:
        return None
    price = None
    try:
        price = float((d.get("price") or {}).get("value"))
    except (TypeError, ValueError):
        pass
    img = (d.get("image") or {}).get("imageUrl")
    return {"title": d.get("title"), "price": price, "image_url": img,
            "url": d.get("itemWebUrl") or url}


async def _do_search(token: str, q: str, min_price, max_price, limit: int, include_auctions: bool = False, auctions_only: bool = False, sport: str = None, seller: str = None):
    opts = "AUCTION" if auctions_only else ("FIXED_PRICE|AUCTION" if include_auctions else "FIXED_PRICE")
    filt = f"buyingOptions:{{{opts}}}"
    if seller:
        filt += f",sellers:{{{seller}}}"
    # Only push a price filter to eBay for pure fixed-price searches. When auctions
    # are included we filter price in code so auctions (low current bid) aren't dropped.
    if not include_auctions and not auctions_only:
        if min_price:
            filt += f",price:[{min_price}]"
        if max_price:
            filt += f",price:[..{max_price}]"
    params = {
        # When a sport is specified, scope to Trading Card Singles + the Sport aspect
        # so e.g. an NBA search never returns MLB/baseball cards.
        "category_ids": "261328" if sport else "212",
        "limit": str(min(limit, 50)),
        "sort": "newlyListed",
        "filter": filt,
    }
    if (q or "").strip():
        params["q"] = q  # omit q for seller-only watches (category+seller filter is enough)
    if sport:
        params["aspect_filter"] = f"categoryId:261328,Sport:{{{sport}}}"
    return await _ebay_get(token, params)


async def search_cards(query: str, min_price=None, max_price=None, limit: int = 50, include_auctions: bool = False, auctions_only: bool = False, sport: str = None, seller: str = None):
    # Serve from cache when possible — this is what de-dups the same card watched
    # by many users and avoids re-calling eBay every cycle.
    key = (str(query).strip().lower(), min_price, max_price, limit, include_auctions, auctions_only, sport, seller)
    hit = _search_cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1]

    token = await _get_token()

    # Try the query as-is first
    data = await _do_search(token, query, min_price, max_price, limit, include_auctions, auctions_only, sport, seller)

    # Seller-only watch: don't run the no-result query fallbacks (they'd drop the
    # seller scope); just return whatever the seller currently has.
    if seller:
        if data.get("errors"):
            return []
        results = _shape_results(data)
        _search_cache[key] = (time.time() + SEARCH_TTL, results)
        return results

    # If eBay returned an error (rate limit / budget cap), stop — retrying with
    # fallback queries only burns more quota. Don't cache errors.
    if data.get("errors"):
        print(f"eBay search skipped for '{query}': {data['errors']}")
        return []

    # Fallback 1: clean out card-numbers / symbols
    if not data.get("itemSummaries"):
        cleaned = _clean_query(query)
        if cleaned and cleaned != query:
            data = await _do_search(token, cleaned, min_price, max_price, limit, include_auctions, auctions_only, sport)

    # Fallback 2: use just the first 6 words (player + set)
    if not data.get("itemSummaries") and not data.get("errors"):
        words = _clean_query(query).split()
        if len(words) > 6:
            data = await _do_search(token, " ".join(words[:6]), min_price, max_price, limit, include_auctions, auctions_only, sport)

    if data.get("errors"):
        return []

    results = _shape_results(data)
    _search_cache[key] = (time.time() + SEARCH_TTL, results)
    return results


def _shape_results(data: dict) -> list:
    """Map eBay Browse itemSummaries into our listing dicts."""
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
            "end_date": item.get("itemEndDate"),         # when an auction ends (ISO)
            "listing_url": item.get("itemWebUrl", ""),
            "image_url": item.get("image", {}).get("imageUrl"),
            "seller_name": item.get("seller", {}).get("username"),
            "condition": item.get("condition"),
            "is_sold": False,
        })
    return results


async def _get_insights_token():
    """OAuth token scoped for the Marketplace Insights API (sold comps). Returns
    None if the scope isn't granted to this app yet, so callers fall back to
    other sources. Once we learn the scope is denied we stop asking (per process)
    to avoid a wasted token round-trip on every lookup."""
    global _insights_enabled
    if _insights_enabled is False:
        return None
    if _insights_token_cache["token"] and time.time() < _insights_token_cache["expires_at"] - 60:
        return _insights_token_cache["token"]
    credentials = base64.b64encode(f"{APP_ID}:{CERT_ID}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.ebay.com/identity/v1/oauth2/token",
                headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "client_credentials", "scope": INSIGHTS_SCOPE},
            )
            data = resp.json()
    except Exception as e:
        print(f"insights token error: {e}")
        return None
    tok = data.get("access_token")
    if not tok:
        # invalid_scope => app not approved for Marketplace Insights yet.
        _insights_enabled = False
        print(f"Marketplace Insights not authorized ({data.get('error')}); using fallback sold sources.")
        return None
    _insights_enabled = True
    _insights_token_cache["token"] = tok
    _insights_token_cache["expires_at"] = time.time() + data.get("expires_in", 7200)
    return tok


async def _sold_from_insights(q: str, limit: int):
    """Real eBay sold comps via Marketplace Insights. Returns None on
    not-authorized/error (caller should fall back); [] means authorized but no
    sales found."""
    token = await _get_insights_token()
    if not token or not _budget_available():
        return None
    _usage["count"] += 1
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                MARKETPLACE_INSIGHTS_URL,
                headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
                params={"q": q, "category_ids": "212", "limit": str(min(limit, 50)),
                        "filter": "buyingOptions:{FIXED_PRICE|AUCTION}"},
            )
            if resp.status_code >= 400:
                print(f"insights search {resp.status_code} for '{q}'")
                return None
            data = resp.json()
    except Exception as e:
        print(f"insights search error: {e}")
        return None
    sold = []
    for item in data.get("itemSales", []) or []:
        try:
            price = float((item.get("lastSoldPrice") or {}).get("value"))
        except (TypeError, ValueError):
            continue
        if not price:
            continue
        sold.append({
            "source": "ebay_insights",
            "external_id": item.get("itemId", ""),
            "title": item.get("title", ""),
            "sold_price": price,
            "listing_url": item.get("itemWebUrl", ""),
            "image_url": (item.get("image") or {}).get("imageUrl"),
            "sold_at": item.get("lastSoldDate", ""),
            "is_sold": True,
            "comp_type": "sold",
        })
    sold.sort(key=lambda s: s.get("sold_at") or "", reverse=True)  # most-recent first
    return sold


def _parse_130point_date(text: str) -> str:
    """'Date: Mon 20 Jul 2026 11:52:30 GMT' -> ISO 'YYYY-MM-DDTHH:MM:SS'. Falls
    back to the raw string if 130point's date format shifts."""
    import datetime as _dt
    t = (text or "").replace("Date:", "").strip()
    for fmt in ("%a %d %b %Y %H:%M:%S %Z", "%a %d %b %Y %H:%M:%S"):
        try:
            return _dt.datetime.strptime(t, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return t


async def _sold_from_130point(q: str, limit: int):
    """Best-effort sold comps from 130point.com's public sales tool (aggregates
    recent eBay sold + auction results). Stopgap until Marketplace Insights is
    approved. Parses the .salesTable that 130point's backend returns: each sale
    is a <tr data-rowid data-price data-currency> with the title in #titleText,
    the sale date in #dateText, and the thumbnail in #imgCol. Any failure -> []."""
    import re
    try:
        from bs4 import BeautifulSoup
        async with httpx.AsyncClient(
            timeout=25, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0", "Origin": "https://130point.com",
                     "Referer": "https://130point.com/sales/", "X-Requested-With": "XMLHttpRequest"},
        ) as client:
            resp = await client.post("https://back.130point.com/sales/",
                                     data={"query": q, "type": "2"})
        if resp.status_code >= 400:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"130point error: {e}")
        return []

    sold = []
    for row in soup.select("tr[data-rowid]"):
        # Keep comps in one currency so the average is meaningful for a USD tool.
        if (row.get("data-currency") or "").upper() != "USD":
            continue
        try:
            price = float(row.get("data-price"))
        except (TypeError, ValueError):
            continue
        if not price:
            continue
        link = row.select_one("#titleText a")
        title = link.get_text(strip=True) if link else ""
        url = link.get("href", "") if link else ""
        m = re.search(r"/itm/(\d{9,})", url)
        item_id = m.group(1) if m else (url[:200] if url else "")
        img_el = row.select_one("#imgCol img")
        img = img_el.get("src") if img_el else None
        if img:  # bump the 150px thumb to a usable size
            img = img.replace("s-l150", "s-l500").replace("s-l140", "s-l500")
        date_el = row.select_one("#dateText")
        sold_at = _parse_130point_date(date_el.get_text(" ", strip=True)) if date_el else ""
        sold.append({
            "source": "130point",
            "external_id": item_id,
            "title": title,
            "sold_price": price,
            "listing_url": url,
            "image_url": img,
            "sold_at": sold_at,
            "is_sold": True,
            "comp_type": "sold",
        })
        if len(sold) >= limit:
            break
    sold.sort(key=lambda s: s.get("sold_at") or "", reverse=True)  # most-recent first
    return sold


async def _sold_from_browse_active(query: str, limit: int):
    """Last-resort proxy: current active BIN listings (NOT sold). Lowest active
    asks are an upper bound on market value. Tagged comp_type='active' so callers
    and the UI never present these as confirmed sales."""
    listings = await search_cards(query, limit=limit)
    comps = []
    for l in listings:
        price = l.get("price") or 0
        if l.get("is_auction") or not price:
            continue
        comps.append({
            "source": "ebay_active",
            "external_id": l.get("external_id", ""),
            "title": l.get("title", ""),
            "sold_price": price,
            "listing_url": l.get("listing_url", ""),
            "image_url": l.get("image_url"),
            "sold_at": l.get("created_at", ""),
            "is_sold": False,
            "comp_type": "active",
        })
    comps.sort(key=lambda s: s.get("sold_at") or "", reverse=True)
    return comps


async def get_sold_history(query: str, limit: int = 20):
    """Recent sold comps for a card, from the best source available:
      1) eBay Marketplace Insights — real sold prices + dates (needs Limited
         Release approval; auto-skipped until this app is granted the scope).
      2) 130point.com — public sold aggregator (best-effort stopgap).
      3) eBay Browse active listings — a weak proxy (tagged comp_type='active').
    Cached for SOLD_TTL. Every item carries comp_type in {'sold','active'} so
    callers can distinguish confirmed sales from active-listing proxies."""
    key = str(query).strip().lower()
    hit = _sold_cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1]

    # 1) Marketplace Insights (real sold data)
    sold = await _sold_from_insights(query, limit)
    if not sold and _insights_enabled:
        cleaned = _clean_query(query)
        if cleaned and cleaned != query:
            sold = await _sold_from_insights(cleaned, limit)

    # 2) 130point stopgap
    if not sold:
        sold = await _sold_from_130point(query, limit)

    # 3) Active-listing proxy
    if not sold:
        sold = await _sold_from_browse_active(query, limit)

    sold = sold or []
    _sold_cache[key] = (time.time() + SOLD_TTL, sold)
    return sold
