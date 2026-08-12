"""Fanatics Collect (PWCC + Goldin) listings, via their public Algolia index.

Their own site searches through Algolia with a search-only key shipped in the
page bundle — public by design — so this is a real API rather than scraping:
no HTML parsing, no headless browser, no IP blocking, and nothing that expires.
The GraphQL endpoint behind the site refuses introspection and only fetches
listings by id, so it is no use for searching.

Results are shaped exactly like ebay_scraper's so the alert filters, dedup and
emails treat both sources identically.
"""
import time
import datetime
import urllib.parse

import httpx

ALGOLIA_APP_ID = "3XT9C4X62I"
ALGOLIA_SEARCH_KEY = "68bfdf930418fb22629fd72031025e6e"   # search-only, public
ALGOLIA_INDEX = "prod_item_state_v1"
ALGOLIA_URL = (f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/"
               f"{ALGOLIA_INDEX}/query")

SITE = "https://www.fanaticscollect.com"

# The index holds 4.4M rows including 1M sold lots and non-sports categories.
# Both filters matter: without them an alert sees closed auctions and Pokémon.
BASE_FILTERS = 'status:Live AND categoryParent:"Sports Cards"'

SEARCH_TTL = 300          # 5 min — the index updates continuously
_cache: dict = {}


def _iso(ts):
    """Algolia stores timestamps as unix seconds; the filters want ISO."""
    try:
        return datetime.datetime.utcfromtimestamp(int(ts)).isoformat() + "Z"
    except (TypeError, ValueError, OSError):
        return None


def _first_image(hit) -> str:
    imgs = hit.get("images") or {}
    for slot in ("primary", "secondary"):
        got = imgs.get(slot)
        if isinstance(got, dict):
            for size in ("medium", "large", "small"):
                if got.get(size):
                    return got[size]
    return None


def _listing_url(hit) -> str:
    """A link that lands a human on the lot.

    Fanatics has no guessable canonical per-listing path — every shape built
    from listingId, lotNumber or uuid returns 404 — so this points at their
    search for the exact title, scoped to the right marketplace, which does
    find it.
    """
    mkt = (hit.get("marketplace") or "").upper()
    q = urllib.parse.quote((hit.get("title") or "")[:120])
    kind = mkt if mkt in ("WEEKLY", "PREMIER", "FIXED") else "FIXED"
    return f"{SITE}/marketplace?type={kind}&query={q}"


def _shape(hit) -> dict:
    mkt = (hit.get("marketplace") or "").upper()
    is_auction = mkt in ("WEEKLY", "PREMIER") or bool(hit.get("auctionEndDatetime"))
    # currentPrice tracks the bid on auctions and the ask on fixed price; fall
    # back through the others so a lot is never scored at $0 the way eBay
    # auctions were before currentBidPrice was handled.
    price = 0.0
    for key in ("currentPrice", "currentBid", "startingBid"):
        try:
            v = float(hit.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if v:
            price = v
            break
    return {
        "source": "fanatics",
        # Namespaced so it can never collide with an eBay item id in alert_seen.
        "external_id": f"fc|{hit.get('objectID')}",
        "title": hit.get("title") or "",
        "price": price,
        "is_auction": is_auction,
        "created_at": _iso(hit.get("listedAt") or hit.get("createdAt")),
        "end_date": _iso(hit.get("auctionEndDatetime")),
        "listing_url": _listing_url(hit),
        "image_url": _first_image(hit),
        "seller_name": hit.get("auctionName") or "Fanatics Collect",
        "condition": (f"{hit.get('gradingService')} {hit.get('grade')}".strip()
                      if hit.get("grade") else None),
        "is_sold": False,
        "bid_count": hit.get("bidCount"),
    }


async def search_cards(query: str, limit: int = 50, include_auctions: bool = True) -> list:
    """Live Fanatics Collect listings matching `query`.

    Never raises: a bad response returns [] so a Fanatics outage can't take an
    eBay alert down with it.
    """
    q = (query or "").strip()
    if not q:
        return []
    key = (q.lower(), limit, include_auctions)
    hit = _cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1]

    filters = BASE_FILTERS
    if not include_auctions:
        filters += " AND marketplace:FIXED"
    params = urllib.parse.urlencode({
        "query": q,
        "hitsPerPage": min(int(limit), 100),
        "filters": filters,
        # Algolia requires EVERY word by default, so "Topps Chrome Update
        # Stephen Curry" returned nothing while "Stephen Curry" returned 2,841.
        # Retrying with the words optional matches how eBay behaves and how
        # _ebay_keywords already works: fetch permissively, then let
        # passes_filters enforce the words strictly against the title.
        "removeWordsIfNoResults": "allOptional",
    })
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                ALGOLIA_URL,
                headers={"X-Algolia-API-Key": ALGOLIA_SEARCH_KEY,
                         "X-Algolia-Application-Id": ALGOLIA_APP_ID,
                         "Content-Type": "application/json"},
                json={"params": params})
        if r.status_code != 200:
            print(f"fanatics search {r.status_code} for {q!r}: {r.text[:120]}")
            return []
        hits = r.json().get("hits") or []
    except Exception as e:
        print(f"fanatics search failed for {q!r}: {type(e).__name__}: {e}")
        return []

    out = [_shape(h) for h in hits if h.get("title")]
    _cache[key] = (time.time() + SEARCH_TTL, out)
    return out
