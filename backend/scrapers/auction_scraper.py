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


async def goldin_sales(query: str, limit: int = 15) -> dict:
    """Goldin past results — best-effort. The site is a keyless SPA, so plain
    HTTP almost never yields data; reported honestly via status."""
    url = "https://goldin.co/search"
    try:
        async with httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) as c:
            r = await c.get(url, params={"query": query})
    except Exception:
        return {"name": "Goldin", "status": "error", "sales": []}

    if r.status_code in (403, 429):
        return {"name": "Goldin", "status": "blocked", "sales": []}
    if r.status_code != 200:
        return {"name": "Goldin", "status": f"http {r.status_code}", "sales": []}

    # SPA shell — no data in HTML. Detect that and say so rather than pretend.
    if "__NEXT_DATA__" not in r.text and "application/json" not in r.text:
        return {"name": "Goldin", "status": "no data (JS-only)", "sales": []}
    return {"name": "Goldin", "status": "no data", "sales": []}
