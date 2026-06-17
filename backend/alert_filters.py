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


import re


def passes_filters(s, listing) -> bool:
    """Strict post-filter on the listing title. eBay's search returns loosely
    related listings (not just exact matches), so we require every meaningful
    word from the saved search's free-text query to actually appear in the title
    — otherwise we'd alert on the wrong card. The print run ('/N') is enforced
    too; brand/insert/number ride on the keywords so we don't wrongly drop
    matches when sellers format titles differently."""
    title = (listing.get("title") if isinstance(listing, dict) else listing) or ""
    t = title.lower()

    if s.numbered_to and f"/{s.numbered_to}" not in title:
        return False

    query = (getattr(s, "query", "") or "").lower()
    # Require each query word of 3+ chars to be present (skips noise like "10", "rc").
    for word in re.split(r"[^a-z0-9]+", query):
        if len(word) >= 3 and word not in t:
            return False
    return True


def passes_deal_threshold(search, src, analysis) -> bool:
    """When a saved search sets `deal_threshold_pct` (N), only alert on eBay
    listings priced at least N% below the recent market average. Auctions carry
    no market comp, so the threshold doesn't apply to them. If we can't establish
    a market price (no sold data), suppress — the user asked for confirmed deals,
    so a listing we can't price-check shouldn't slip through."""
    threshold = getattr(search, "deal_threshold_pct", None)
    if not threshold or src != "ebay":
        return True
    pct = (analysis or {}).get("pct_vs_market")
    if pct is None:
        return False
    return pct <= -abs(threshold)


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

    # Dedup by external_id and apply the strict post-filter so we only alert on
    # listings that actually match the exact query.
    seen = set()
    deduped = []
    for l in listings:
        if not passes_filters(search, l):
            continue
        eid = l.get("external_id")
        if eid in seen:
            continue
        seen.add(eid)
        deduped.append(l)
    return "ebay", deduped
