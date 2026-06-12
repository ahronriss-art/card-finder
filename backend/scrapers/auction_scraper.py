"""Best-effort auction-house sales lookups for the Auctions tab.

Reality check (verified June 2026): scraping PSA Auction Prices Realized and
Goldin directly from a datacenter IP (Render) is almost always blocked — PSA
returns HTTP 403 (Cloudflare/bot detection) and Goldin serves a keyless JS
shell with no data in the HTML. We still *attempt* both (fast-fail, short
timeout) so they light up automatically if a proxy/residential egress is ever
added, but the live workhorse is eBay via the Browse API (credentials already
configured). Every source reports a clear status so the UI can be honest about
where the numbers came from.
"""
import re
import asyncio
import httpx
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _parse_price(text: str):
    if not text:
        return None
    m = re.search(r"[\d,]+(?:\.\d{2})?", text.replace("$", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


async def psa_apr_sales(query: str, limit: int = 15) -> dict:
    """PSA Auction Prices Realized — aggregates Goldin/Heritage/eBay sold for
    graded cards. Usually 403 from a server; returns status so the UI is honest."""
    url = "https://www.psacard.com/auctionprices/search"
    try:
        async with httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) as c:
            r = await c.get(url, params={"q": query})
    except Exception:
        return {"name": "PSA APR", "status": "error", "sales": []}

    if r.status_code == 403 or r.status_code == 429:
        return {"name": "PSA APR", "status": "blocked", "sales": []}
    if r.status_code != 200:
        return {"name": "PSA APR", "status": f"http {r.status_code}", "sales": []}

    # If PSA ever serves real HTML to us, pull whatever sale rows we can find.
    sales = []
    try:
        soup = BeautifulSoup(r.text, "html.parser")
        for row in soup.select("table tr")[1:limit + 1]:
            cells = [c.get_text(strip=True) for c in row.select("td")]
            if len(cells) < 2:
                continue
            price = next((_parse_price(c) for c in cells if _parse_price(c)), None)
            date = next((c for c in cells if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", c)), "")
            if price:
                sales.append({
                    "source": "psa", "auction_house": "PSA APR",
                    "title": query, "sold_price": price, "sold_at": date,
                    "grade": "", "listing_url": str(r.url), "image_url": None,
                })
    except Exception:
        pass
    return {"name": "PSA APR", "status": "ok" if sales else "no data", "sales": sales}


# Goldin's site is a keyless SPA, but its frontend calls these internal APIs
# (reverse-engineered from the client bundle). No auth, no bot-block.
#   /api/lots      -> LIVE auction lots (current bids)
#   /api/lots_v2   -> richer search; {"search":{...,"show_only":"Sold"}} returns
#                     COMPLETED SALES with final price + sale date (sold history).
GOLDIN_LIVE_URL = "https://d1wu47wucybvr3.cloudfront.net/api/lots"
GOLDIN_SEARCH_URL = "https://d1wu47wucybvr3.cloudfront.net/api/lots_v2"
GOLDIN_ITEM_BASE = "https://goldin.co/item/"
# Company, an optional word descriptor (EX, NM-MT, VG, GEM MT…), then the numeric
# grade — so "PSA EX 5", "PSA NM-MT 8" and "PSA 5" all normalize to "PSA 5".
_GRADE_RE = re.compile(
    r"\b(PSA|BGS|SGC|CGC|BVG)\b[\sA-Za-z./-]{0,14}?\b(10|[1-9](?:\.5)?|AUTH(?:ENTIC)?)\b",
    re.I,
)


def extract_grade(title: str) -> str:
    """Normalize a grading label to 'COMPANY NUMBER' (e.g. 'PSA 5'), or '' if none.
    Ignores word descriptors so 'PSA EX 5' == 'PSA 5'."""
    m = _GRADE_RE.search(title or "")
    if not m:
        return ""
    company = m.group(1).upper()
    num = m.group(2).upper()
    if num.startswith("AUTH"):
        num = "AUTH"
    return f"{company} {num}"


def _goldin_headers():
    return {**HEADERS, "Content-Type": "application/json", "Origin": "https://goldin.co"}


def _goldin_row(lot: dict, status: str) -> dict:
    title = lot.get("title") or ""
    gm = _GRADE_RE.search(title)
    slug = lot.get("meta_slug")
    price = lot.get("current_price")
    return {
        "source": "goldin",
        "auction_house": "Goldin",
        "status": status,  # "sold" or "live auction"
        "title": title,
        "sold_price": float(price) if price else None,
        "sold_at": (lot.get("end_timestamp") or "")[:10],  # sale date / auction end
        "bids": lot.get("number_of_bids"),
        "grade": gm.group(0).upper() if gm else "",
        "listing_url": (GOLDIN_ITEM_BASE + slug) if slug else "https://goldin.co",
        "image_url": None,
    }


async def _goldin_sold(query: str, limit: int) -> list:
    """Completed Goldin sales (final price + date) via lots_v2 show_only=Sold."""
    body = {"search": {"queryType": "Search", "keyword": query, "from": 0,
                       "size": min(limit, 20), "show_only": "Sold"}}
    async with httpx.AsyncClient(timeout=12, headers=_goldin_headers(), follow_redirects=True) as c:
        r = await c.post(GOLDIN_SEARCH_URL, json=body)
    if r.status_code != 200:
        return []
    lots = (r.json().get("searchalgolia") or {}).get("lots") or []
    rows = [_goldin_row(l, "sold") for l in lots if l.get("current_price")]
    # newest sales first
    rows.sort(key=lambda x: x.get("sold_at") or "", reverse=True)
    return rows[:limit]


async def _goldin_live(query: str, limit: int) -> list:
    """Currently-open Goldin auction lots via /api/lots."""
    body = {"queryType": "All", "keyword": query, "from": 0, "size": min(limit, 20)}
    async with httpx.AsyncClient(timeout=12, headers=_goldin_headers(), follow_redirects=True) as c:
        r = await c.post(GOLDIN_LIVE_URL, json=body)
    if r.status_code != 200:
        return []
    lots = (r.json().get("body") or {}).get("lots") or []
    return [_goldin_row(l, "live auction") for l in lots[:limit] if l.get("current_price")]


async def goldin_sales(query: str, limit: int = 15) -> dict:
    """Goldin via its internal APIs: completed sales (sold history, with dates)
    plus any lots currently up for auction. Sold rows lead; live lots follow."""
    try:
        sold, live = await asyncio.gather(
            _goldin_sold(query, limit),
            _goldin_live(query, max(3, limit // 2)),
            return_exceptions=True,
        )
    except Exception:
        return {"name": "Goldin", "status": "error", "sales": []}
    sold = sold if isinstance(sold, list) else []
    live = live if isinstance(live, list) else []
    sales = (sold + live)[:limit + 5]
    return {"name": "Goldin", "status": "ok" if sales else "no data",
            "sales": sales, "sold_count": len(sold), "live_count": len(live)}
