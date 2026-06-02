import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def search_cardladder(query: str, limit: int = 10) -> list[dict]:
    """Search CardLadder for card price data and recent sales."""
    url = f"https://www.cardladder.com/cards/search?q={query.replace(' ', '+')}"
    results = []

    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select(".card-result, .search-result, [class*='card-item']")[:limit]

            for card in cards:
                try:
                    title = card.select_one("[class*='title'], h3, h4")
                    price = card.select_one("[class*='price'], [class*='value']")
                    link = card.select_one("a")

                    if title:
                        listing_url = f"https://www.cardladder.com{link['href']}" if link and link.get("href", "").startswith("/") else (link["href"] if link else url)
                        results.append({
                            "source": "cardladder",
                            "external_id": f"cl-{hash(title.get_text())}",
                            "title": title.get_text(strip=True),
                            "price": _parse_price(price.get_text() if price else ""),
                            "listing_url": listing_url,
                            "seller_name": "CardLadder",
                            "is_sold": False,
                        })
                except Exception:
                    continue
    except Exception as e:
        print(f"CardLadder scrape error: {e}")

    return results


async def get_cardladder_sales(query: str, limit: int = 10) -> list[dict]:
    """Get recent card sales from CardLadder."""
    url = f"https://www.cardladder.com/cards/search?q={query.replace(' ', '+')}"
    sold = []

    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")

            sale_items = soup.select("[class*='sale'], [class*='transaction'], [class*='sold']")[:limit]
            for item in sale_items:
                price_el = item.select_one("[class*='price']")
                date_el = item.select_one("[class*='date'], time")
                title_el = item.select_one("[class*='title'], span, p")
                if price_el:
                    sold.append({
                        "source": "cardladder",
                        "sold_price": _parse_price(price_el.get_text()),
                        "sold_at": date_el.get_text(strip=True) if date_el else None,
                        "title": title_el.get_text(strip=True) if title_el else query,
                        "is_sold": True,
                    })
    except Exception as e:
        print(f"CardLadder sales error: {e}")

    return sold


def _parse_price(text: str) -> float:
    try:
        return float("".join(c for c in text if c.isdigit() or c == "."))
    except Exception:
        return 0.0
