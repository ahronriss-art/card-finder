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


# Goldin's site is a keyless SPA, but its frontend calls this internal lots API
# (reverse-engineered from the client bundle). It returns LIVE auction lots —
# current bids, not completed sales — with no auth and no bot-block.
GOLDIN_LOTS_URL = "https://d1wu47wucybvr3.cloudfront.net/api/lots"
GOLDIN_ITEM_BASE = "https://goldin.co/item/"
_GRADE_RE = re.compile(r"\b(PSA|BGS|SGC|CGC)\s*([0-9]+(?:\.5)?|Authentic|Auth)\b", re.I)


async def goldin_sales(query: str, limit: int = 15) -> dict:
    """Live Goldin auction lots via the internal /api/lots endpoint. These are
    OPEN auctions (current bid), not completed sales — each row is marked
    status='live auction' so the UI/AI describe them correctly."""
    body = {"queryType": "All", "keyword": query, "from": 0, "size": min(limit, 20)}
    headers = {**HEADERS, "Content-Type": "application/json", "Origin": "https://goldin.co"}
    try:
        async with httpx.AsyncClient(timeout=10, headers=headers, follow_redirects=True) as c:
            r = await c.post(GOLDIN_LOTS_URL, json=body)
    except Exception:
        return {"name": "Goldin", "status": "error", "sales": []}

    if r.status_code in (403, 429):
        return {"name": "Goldin", "status": "blocked", "sales": []}
    if r.status_code != 200:
        return {"name": "Goldin", "status": f"http {r.status_code}", "sales": []}

    try:
        lots = (r.json().get("body") or {}).get("lots") or []
    except Exception:
        return {"name": "Goldin", "status": "error", "sales": []}

    sales = []
    for lot in lots[:limit]:
        price = lot.get("current_price")
        title = lot.get("title") or query
        gm = _GRADE_RE.search(title)
        slug = lot.get("meta_slug")
        sales.append({
            "source": "goldin",
            "auction_house": "Goldin",
            "status": "live auction",
            "title": title,
            "sold_price": float(price) if price else None,
            "sold_at": (lot.get("end_timestamp") or "")[:10],  # auction END date
            "bids": lot.get("number_of_bids"),
            "grade": gm.group(0).upper() if gm else "",
            "listing_url": (GOLDIN_ITEM_BASE + slug) if slug else "https://goldin.co",
            "image_url": None,
        })
    return {"name": "Goldin", "status": "ok" if sales else "no data", "sales": sales}
