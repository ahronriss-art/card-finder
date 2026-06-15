"""Compose a saved alert's structured filters into an eBay search query, and
post-filter the returned listings. Shared by worker.py and the in-app checker
so both build the exact same search."""


def build_query(s) -> str:
    """Build the eBay keyword string from a SavedSearch's fields."""
    parts = []
    if getattr(s, "year", None):
        parts.append(str(s.year).strip())
    if s.sport:
        parts.append(s.sport)
    if getattr(s, "brand", None):
        parts.append(str(s.brand).strip())
    if s.query:
        parts.append(s.query)
    if getattr(s, "insert_type", None):
        parts.append(str(s.insert_type).strip())
    if getattr(s, "card_number", None):
        num = str(s.card_number).strip().lstrip("#")
        if num:
            parts.append(f"#{num}")
    if s.numbered_to:
        parts.append(f"/{s.numbered_to}")
    q = " ".join(p for p in parts if p)
    # eBay supports -word to exclude terms
    if getattr(s, "exclude", None):
        for w in str(s.exclude).replace(",", " ").split():
            w = w.lstrip("-").strip()
            if w:
                q += f" -{w}"
    return q.strip()


def passes_filters(s, title) -> bool:
    """Strict post-filter on the listing title. Only the print run is enforced
    here (it's reliable as '/N'); brand/insert/number ride on the keywords so we
    don't wrongly drop matches when sellers format titles differently."""
    t = title or ""
    if s.numbered_to and f"/{s.numbered_to}" not in t:
        return False
    return True


async def gather_alert_listings(search):
    """Return (source, listings) for a saved alert. source='ebay' for normal
    listing alerts; source='goldin' for auction alerts (live Goldin lots), which
    optionally skip cards that sold within `dry_spell_months`."""
    q = build_query(search)
    src = getattr(search, "source", None) or "ebay"

    if src == "auction":
        from datetime import datetime, timedelta
        from scrapers import auction_scraper
        g = await auction_scraper.goldin_sales(q)
        live = [l for l in g.get("sales", []) if l.get("status") == "live auction"]

        # Most recent completed Goldin sale (for the dry-spell check + alert line)
        sold_rows = [s for s in g.get("sales", []) if s.get("status") == "sold" and s.get("sold_at")]
        last = max(sold_rows, key=lambda s: s["sold_at"]) if sold_rows else None

        dry = getattr(search, "dry_spell_months", None)
        if dry and live and last:
            try:
                newest = datetime.strptime(last["sold_at"][:10], "%Y-%m-%d")
                if newest >= datetime.utcnow() - timedelta(days=30 * int(dry)):
                    live = []  # sold recently → not a dry-spell opportunity
            except Exception:
                pass

        listings = []
        for l in live:
            ends = l.get("sold_at")
            listings.append({
                "external_id": l.get("listing_url") or l.get("title"),
                "title": (l.get("title") or "")[:90] + (f" — auction ends {ends}" if ends else ""),
                "price": l.get("sold_price") or 0,
                "listing_url": l.get("listing_url"),
                "image_url": None,
                "last_sold_price": (last or {}).get("sold_price"),
                "last_sold_at": (last or {}).get("sold_at"),
            })
        return "goldin", listings

    from scrapers.ebay_scraper import search_cards
    listings = await search_cards(q, search.min_price, search.max_price, limit=10)
    listings = [l for l in listings if passes_filters(search, l.get("title"))]
    return "ebay", listings
