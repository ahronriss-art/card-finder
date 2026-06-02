import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


async def search_alt(query: str, limit: int = 10) -> list[dict]:
    """Search ALT marketplace for graded card listings."""
    url = f"https://www.alt.com/search?q={query.replace(' ', '%20')}"
    results = []

    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("[class*='card'], [class*='listing'], [class*='item']")[:limit]

            for card in cards:
                try:
                    title = card.select_one("[class*='title'], [class*='name'], h2, h3")
                    price = card.select_one("[class*='price'], [class*='ask']")
                    link = card.select_one("a")
                    image = card.select_one("img")

                    if title and price:
                        href = link["href"] if link else ""
                        listing_url = f"https://www.alt.com{href}" if href.startswith("/") else href or url
                        results.append({
                            "source": "alt",
                            "external_id": f"alt-{hash(title.get_text())}",
                            "title": title.get_text(strip=True),
                            "price": _parse_price(price.get_text()),
                            "listing_url": listing_url,
                            "image_url": image.get("src") if image else None,
                            "seller_name": "ALT Marketplace",
                            "condition": "Graded",
                            "is_sold": False,
                        })
                except Exception:
                    continue
    except Exception as e:
        print(f"ALT scrape error: {e}")

    return results


def _parse_price(text: str) -> float:
    try:
        return float("".join(c for c in text if c.isdigit() or c == "."))
    except Exception:
        return 0.0
