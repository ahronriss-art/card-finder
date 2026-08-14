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
# eBay's published Browse limit is 5000/day, confirmed live via the Developer
# Analytics rate_limit endpoint. Sit just under it rather than well under: the
# old 4500 left 500 calls unused every day while alerts were being stretched to
# fit. sync_real_quota() keeps the counter honest, so the margin can be thin.
DAILY_CALL_CAP = 4850

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


async def sync_real_quota() -> dict:
    """Ask eBay how much Browse quota is actually left, and correct our counter.

    The local count only knows about calls this process made. The limit is per
    APPLICATION — every process, every environment and every script sharing
    these credentials draws on the same 5000, so the local number drifts low and
    the app can blow the real limit while believing it has room. Reading the
    truth costs nothing: the analytics endpoint is not itself a Browse call.
    """
    try:
        token = await _get_token()
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(
                "https://api.ebay.com/developer/analytics/v1_beta/rate_limit/",
                headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            return {"ok": False, "error": f"{r.status_code}"}
        for api in r.json().get("rateLimits", []):
            for res in api.get("resources", []):
                if res.get("name") != "buy.browse":
                    continue
                for rate in res.get("rates", []):
                    limit, remaining = rate.get("limit"), rate.get("remaining")
                    if limit is None or remaining is None:
                        continue
                    used = int(limit) - int(remaining)
                    # Never lower the count — a stale reading must not hand back
                    # budget we have already spent since eBay measured it.
                    _budget_available()          # roll the day over first
                    _usage["count"] = max(_usage["count"], used)
                    return {"ok": True, "limit": int(limit), "remaining": int(remaining),
                            "used": used, "reset": rate.get("reset")}
        return {"ok": False, "error": "buy.browse not in response"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


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


async def get_item_detail(url_or_id: str) -> dict:
    """Everything about ONE listing that alert matching depends on.

    get_item_by_url() returns the display fields; this returns the fields that
    decide whether an alert could have fired — when it was listed (the freshness
    gate and the per-alert cursor), auction vs fixed price (the price floor is
    auction-exempt), and the Sport aspect (alerts scope eBay by it). Also
    resolves ebay.io/ebay.us share links, which is what a phone actually copies.
    """
    import re
    raw = (url_or_id or "").strip()
    if re.fullmatch(r"\d{9,}", raw):
        item_id = raw
    else:
        if re.search(r"ebay\.(io|us)/", raw):
            try:                       # share link -> the real listing URL
                async with httpx.AsyncClient(timeout=12, follow_redirects=False) as c:
                    r = await c.get(raw, headers={"User-Agent": "Mozilla/5.0"})
                raw = r.headers.get("location") or raw
            except Exception:
                pass
        m = (re.search(r"/itm/(?:[^/]*/)?(\d{9,})", raw) or re.search(r"[?&]item=(\d{9,})", raw)
             or re.search(r"(\d{9,})", raw))
        if not m:
            return {"error": "That doesn't look like an eBay listing link."}
        item_id = m.group(1)

    if not _budget_available():
        return {"error": "eBay's daily call budget is used up — try again tomorrow."}
    token = await _get_token()
    _usage["count"] += 1
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.ebay.com/buy/browse/v1/item/v1|{item_id}|0",
                headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
            )
        if resp.status_code == 404:
            return {"error": f"eBay has no listing {item_id} — it may have been removed."}
        if resp.status_code >= 400:
            return {"error": f"eBay returned {resp.status_code} for that listing."}
        d = resp.json()
    except Exception as e:
        return {"error": f"Couldn't reach eBay ({type(e).__name__})."}

    def money(v):
        try:
            return float((v or {}).get("value"))
        except (TypeError, ValueError):
            return None

    opts = d.get("buyingOptions") or []
    aspects = {a.get("name"): a.get("value") for a in (d.get("localizedAspects") or [])}
    # An ended listing (sold, or pulled) leaves eBay's SEARCH index while getItem
    # still serves it. Worth knowing: no search can find it any more, so nothing
    # about search proves anything about how it behaved while it was live.
    ended = False
    if d.get("itemEndDate"):
        try:
            from datetime import datetime as _dt, timezone as _tz
            ended = _dt.fromisoformat(str(d["itemEndDate"]).replace("Z", "+00:00")) <= _dt.now(_tz.utc)
        except ValueError:
            pass
    return {
        "ended": ended,
        "item_id": item_id,
        "title": d.get("title"),
        # A pure auction has no `price` — the live number is currentBidPrice.
        "price": money(d.get("price")) or money(d.get("currentBidPrice")),
        "is_auction": "AUCTION" in opts and "FIXED_PRICE" not in opts,
        "buying_options": opts,
        "created_at": d.get("itemCreationDate"),
        "end_date": d.get("itemEndDate"),
        "category_id": d.get("categoryId"),
        "sport": aspects.get("Sport"),
        "seller": (d.get("seller") or {}).get("username"),
        "image_url": (d.get("image") or {}).get("imageUrl"),
        "url": d.get("itemWebUrl") or f"https://www.ebay.com/itm/{item_id}",
    }


async def is_item_retrievable(q: str, item_id: str, created_at: str = None, sport: str = None,
                              include_auctions: bool = False) -> dict:
    """Does eBay's SEARCH return this listing for these keywords?

    The question no other check can answer: a listing eBay never returns can't
    be filtered, priced or alerted on, and nothing downstream leaves a trace of
    it.

    Answering it needs care. Results come back newest-first, 50 per page, so a
    plain search only proves whether the card is among the 50 newest — a
    day-old listing is absent from those either way, which would make every
    older card look unretrievable. Instead we pin the search to a narrow window
    around the moment the card was listed: if eBay matches it at all, it is on
    the first page of that window. Without a listing date we fall back to the
    newest page and say so, rather than claiming a false negative.
    """
    if not _budget_available():
        return {"ok": False, "error": "eBay's daily call budget is used up."}
    token = await _get_token()
    opts = "FIXED_PRICE|AUCTION" if include_auctions else "FIXED_PRICE"
    filt = f"buyingOptions:{{{opts}}}"
    windowed = False
    if created_at:
        try:
            from datetime import datetime as _dt, timedelta as _td
            c = _dt.fromisoformat(str(created_at).replace("Z", "+00:00"))
            lo = (c - _td(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
            hi = (c + _td(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
            filt += f",itemStartDate:[{lo}..{hi}]"
            windowed = True
        except ValueError:
            pass
    params = {"q": q, "limit": "200", "sort": "newlyListed", "filter": filt,
              "category_ids": "261328" if sport else "212"}
    if sport:
        params["aspect_filter"] = f"categoryId:261328,Sport:{{{sport}}}"
    _usage["count"] += 1
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://api.ebay.com/buy/browse/v1/item_summary/search", params=params,
                headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        data = resp.json()
    except Exception:
        return {"ok": False, "error": "Couldn't reach eBay."}
    if data.get("errors"):
        return {"ok": False, "error": "eBay wouldn't run that search right now."}
    items = data.get("itemSummaries") or []
    found = any(str(item_id) in str(i.get("itemId")) for i in items)
    out = {"ok": True, "found": found, "results": data.get("total"),
           "scanned": len(items), "windowed": windowed, "conclusive": True}
    if found or not windowed:
        return out

    # "Not found" is only meaningful if the window itself is sound. eBay's
    # itemStartDate isn't always the creation timestamp we filtered on (a revised
    # listing can move it), and a window that doesn't actually contain the card
    # would frame a healthy alert as broken. Control: the same window with NO
    # keywords. If the card isn't even there, the measurement is wrong — say so
    # instead of blaming the keywords.
    try:
        from datetime import datetime as _dt, timedelta as _td
        c = _dt.fromisoformat(str(created_at).replace("Z", "+00:00"))
        ctl = dict(params)
        ctl.pop("q", None)
        lo = (c - _td(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        hi = (c + _td(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ctl["filter"] = f"buyingOptions:{{{opts}}},itemStartDate:[{lo}..{hi}]"
        _usage["count"] += 1
        async with httpx.AsyncClient(timeout=20) as client:
            cr = await client.get(
                "https://api.ebay.com/buy/browse/v1/item_summary/search", params=ctl,
                headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
        cd = cr.json()
        in_control = any(str(item_id) in str(i.get("itemId"))
                         for i in (cd.get("itemSummaries") or []))
        out["conclusive"] = bool(in_control)
        out["control_results"] = cd.get("total")
    except Exception:
        out["conclusive"] = False
    return out


async def _do_search(token: str, q: str, min_price, max_price, limit: int, include_auctions: bool = False, auctions_only: bool = False, sport: str = None, seller: str = None, offset: int = 0):
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
    if offset:
        params["offset"] = str(offset)
    if (q or "").strip():
        params["q"] = q  # omit q for seller-only watches (category+seller filter is enough)
    if sport:
        params["aspect_filter"] = f"categoryId:261328,Sport:{{{sport}}}"
    return await _ebay_get(token, params)


_inflight: dict = {}   # key -> in-progress task, so parallel callers share one call


async def search_cards(query: str, min_price=None, max_price=None, limit: int = 50, include_auctions: bool = False, auctions_only: bool = False, sport: str = None, seller: str = None, cover_since: str = None, max_pages: int = 1):
    """Cached, de-duplicated eBay search.

    The alert scan fetches many searches at once, so two alerts sharing keywords
    would otherwise fire two identical calls simultaneously — the result cache
    only helps once a call has already finished. Concurrent callers with the
    same key await the same task instead, which matters while the daily budget
    sits at ~94% committed."""
    key = (str(query).strip().lower(), min_price, max_price, limit, include_auctions,
           auctions_only, sport, seller, cover_since, max_pages)
    hit = _search_cache.get(key)
    if hit and time.time() < hit[0]:
        return hit[1]
    task = _inflight.get(key)
    if task is not None:
        return await task
    import asyncio as _asyncio
    task = _asyncio.ensure_future(_search_cards_uncached(
        query, min_price, max_price, limit, include_auctions, auctions_only,
        sport, seller, cover_since, max_pages))
    _inflight[key] = task
    try:
        return await task
    finally:
        _inflight.pop(key, None)


async def _search_cards_uncached(query: str, min_price=None, max_price=None, limit: int = 50, include_auctions: bool = False, auctions_only: bool = False, sport: str = None, seller: str = None, cover_since: str = None, max_pages: int = 1):
    """Search eBay, newest first. Call search_cards(), not this.

    `cover_since` (ISO timestamp) + `max_pages` turn on adaptive paging: one page
    of 50 is all most queries ever need, but a hot release can post 50 listings
    in under half an hour, so a single page silently truncates everything older
    than that — cards posted between two checks were never seen at all. When the
    oldest listing on a page is still NEWER than `cover_since` (the last time
    this alert ran), there are unseen listings past the page edge, so we fetch
    the next one. Quiet queries stop after page 1 and cost exactly one call.
    """
    # Serve from cache when possible — this is what de-dups the same card watched
    # by many users and avoids re-calling eBay every cycle.
    key = (str(query).strip().lower(), min_price, max_price, limit, include_auctions, auctions_only, sport, seller, cover_since, max_pages)
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

    # Adaptive paging: keep walking back while the page we just read is entirely
    # newer than the point we need to cover, i.e. the listings we care about run
    # off the bottom edge. `_page_covers` fails safe — an unparseable/absent date
    # stops paging rather than looping to the cap on every call.
    if cover_since and max_pages > 1:
        for page in range(1, max_pages):
            if len(results) < 50 * page or _page_covers(results, cover_since):
                break
            more = await _do_search(token, query, min_price, max_price, limit,
                                    include_auctions, auctions_only, sport, seller,
                                    offset=50 * page)
            if more.get("errors"):
                print(f"eBay paging stopped for '{query}' at page {page + 1}: {more['errors']}")
                break
            batch = _shape_results(more)
            if not batch:
                break
            results += batch

    _search_cache[key] = (time.time() + SEARCH_TTL, results)
    return results


def _page_covers(results: list, cover_since: str) -> bool:
    """True if the oldest listing we've pulled is at or older than `cover_since`
    — meaning the window is fully covered and there's nothing left to page for."""
    import datetime as _dt
    try:
        cutoff = _dt.datetime.fromisoformat(str(cover_since).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    oldest = None
    for r in results:
        c = r.get("created_at")
        if not c:
            continue
        try:
            d = _dt.datetime.fromisoformat(str(c).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if oldest is None or d < oldest:
            oldest = d
    return True if oldest is None else oldest <= cutoff


def _summary_price(item: dict) -> float:
    """What this listing currently costs, from a Browse item_summary.

    A pure auction has `price: null` and carries its money in `currentBidPrice`
    instead — so reading `price` alone scored every no-Buy-It-Now auction as $0.
    That was invisible while auctions were exempt from the price floor, and
    started silently dropping all of them the moment the floor began applying to
    auctions too (a Curry /5 SSP sitting at $2,325 with 16 bids read as $0).

    Auction+BIN listings carry both; take the larger so a listing is never
    under-valued into being filtered out by its own price floor.
    """
    best = 0.0
    for field in ("price", "currentBidPrice"):
        try:
            v = float((item.get(field) or {}).get("value"))
        except (TypeError, ValueError):
            continue
        best = max(best, v)
    return best


def _shape_results(data: dict) -> list:
    """Map eBay Browse itemSummaries into our listing dicts."""
    results = []
    for item in data.get("itemSummaries", []):
        bo = item.get("buyingOptions", []) or []
        results.append({
            "source": "ebay",
            "external_id": item.get("itemId", ""),
            "title": item.get("title", ""),
            "price": _summary_price(item),
            "is_auction": "AUCTION" in bo,
            "bid_count": item.get("bidCount"),
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


async def get_sold_history(query: str, limit: int = 20, allow_active: bool = False):
    """Recent sold comps for a card, from the best source available:
      1) eBay Marketplace Insights — real sold prices + dates (needs Limited
         Release approval; auto-skipped until this app is granted the scope).
      2) 130point.com — public sold aggregator (best-effort stopgap).
      3) eBay Browse active listings — ASKING prices, not sales. Only returned
         when the caller passes allow_active=True.

    Tier 3 is opt-in because it was doing real harm by default. Every row has
    always carried comp_type in {'sold','active'}, but not one of the thirteen
    call sites checked it, so asking prices were averaged into "market value"
    everywhere — Deal Check, Card Prices, Portfolio, the MCP tools and alerts.
    That is what priced a Curry /5 off [$3, $1,400, $10,999, $425, $70] and
    labelled a Cooper Flagg flyer "1567% above market". Returning nothing is
    strictly better than returning a confident wrong number.

    Cached for SOLD_TTL."""
    key = (str(query).strip().lower(), bool(allow_active))
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

    # 3) Active-listing proxy — only if the caller has said it can cope with
    # asking prices and will label them as such.
    if not sold and allow_active:
        sold = await _sold_from_browse_active(query, limit)

    sold = sold or []
    _sold_cache[key] = (time.time() + SOLD_TTL, sold)
    return sold
