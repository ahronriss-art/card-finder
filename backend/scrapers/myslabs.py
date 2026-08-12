"""MySlabs listings — peer-to-peer graded slabs, a third alert source.

Server-rendered HTML, so no JS engine is needed: one GET returns ~72 listings
with title, price and id. There is no API.

MySlabs rate-limits hard — a handful of quick requests already returns 429 — so
this caches aggressively and every alert sharing a query shares one fetch. It
is deliberately the least frequent of the three sources.

Listings carry NO published date, so the "recently listed" window that eBay and
Fanatics use can't apply. The per-search alert_seen dedup covers it instead: a
slab alerts the first time an alert sees it and never again.
"""
import asyncio
import re
import time

import httpx

SITE = "https://myslabs.com"
SEARCH = SITE + "/search/all/"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Long, because they 429 quickly and their inventory turns over slowly compared
# with eBay. One fetch per query per half hour is plenty.
SEARCH_TTL = 1800
_cache: dict = {}
_inflight: dict = {}

# Their own listing blocks. \b matters: it keeps slab_item_img and
# slab_item_img_inside, which sit INSIDE each block, from splitting it further.
_BLOCK = re.compile(r'class="slab_item\b')
_ID = re.compile(r"/slab/view/(\d+)/")
_TITLE = re.compile(r'class="slab-title">\s*(.*?)\s*</div>', re.S)
_PRICE = re.compile(r'class="item-price">\s*\$([\d,\.]+)')
_IMG = re.compile(r'data-src="([^"]+)"')


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _parse(html: str) -> list:
    out, seen = [], set()
    for block in _BLOCK.split(html)[1:]:
        mid, mt, mp = _ID.search(block), _TITLE.search(block), _PRICE.search(block)
        if not (mid and mt and mp):
            continue
        sid = mid.group(1)
        if sid in seen:
            continue
        seen.add(sid)
        try:
            price = float(mp.group(1).replace(",", ""))
        except ValueError:
            continue
        img = _IMG.search(block)
        out.append({
            "source": "myslabs",
            "external_id": f"ms|{sid}",
            "title": _clean(mt.group(1)),
            "price": price,
            "is_auction": False,       # the default tab is buy-it-now / offers
            "created_at": None,        # not published; see the module docstring
            "end_date": None,
            "listing_url": f"{SITE}/slab/view/{sid}/",
            "image_url": img.group(1).replace("&amp;", "&") if img else None,
            "seller_name": "MySlabs",
            "condition": None,
            "is_sold": False,
        })
    return out


async def _fetch(query: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                                     headers={"User-Agent": UA}) as client:
            r = await client.get(SEARCH, params={"q": query})
        if r.status_code == 429:
            print(f"myslabs rate-limited on {query!r}; backing off")
            return []
        if r.status_code != 200:
            print(f"myslabs {r.status_code} for {query!r}")
            return []
        return _parse(r.text)
    except Exception as e:
        print(f"myslabs failed for {query!r}: {type(e).__name__}: {e}")
        return []


async def search_cards(query: str, limit: int = 50) -> list:
    """Live MySlabs listings for `query`. Never raises — returns [] on failure so
    a MySlabs outage can't take the eBay half of an alert down."""
    q = (query or "").strip()
    if not q:
        return []
    key = q.lower()
    hit = _cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1][:limit]

    # Coalesce: with alerts fetched in parallel, several sharing a query would
    # otherwise fire simultaneous identical requests at a host that 429s fast.
    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(_fetch(q))
        _inflight[key] = task
        try:
            rows = await task
        finally:
            _inflight.pop(key, None)
        _cache[key] = (time.time() + SEARCH_TTL, rows)
    else:
        rows = await task
    return rows[:limit]
