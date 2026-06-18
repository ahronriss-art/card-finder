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
import math

# eBay calls/day reserved for scheduled alert checks (the rest of the ~4500
# daily safety cap is left for sold-history, the search page, etc.).
SCHEDULED_DAILY_BUDGET = 3000


def min_interval_for(n_active: int) -> float:
    """Smallest per-alert check interval (minutes) that keeps total scheduled
    eBay calls under the daily budget for `n_active` active alerts. With few
    alerts this is small (so user-chosen intervals win); with many it grows to
    automatically space checks out so the budget lasts all day."""
    if n_active <= 0:
        return 0.0
    return float(math.ceil(n_active * 1440 / SCHEDULED_DAILY_BUDGET))


_SEASON_RE = re.compile(r"(20\d{2})\s*[-/]\s*(\d{2,4})")


def _season_forms(start: str, end: str) -> list:
    """All common ways a season can be written, given a 'start-end' pair, e.g.
    2025 + 26/2026 -> ['2025-26', '2025-2026', '2025/26', '2025/2026']."""
    end2 = end[-2:]
    end_full = int(start[:2] + end2)
    if end_full <= int(start):
        end_full += 100  # e.g. 1999-00 -> 2000
    return [f"{start}-{end2}", f"{start}-{end_full}", f"{start}/{end2}", f"{start}/{end_full}"]


def passes_filters(s, listing) -> bool:
    """Strict post-filter on the listing title. eBay's search returns loosely
    related listings (not just exact matches), so we only alert when EVERY word
    the user typed is present in the title — no 'similar' cards. We keep words of
    2+ chars (including numbers like '10', '99', 'rc') so e.g. a 'PSA 10' search
    won't match a PSA 9, and only drop single-char noise. The print run ('/N') is
    enforced too. Seasons are matched format-agnostically (2025-2026 == 2025-26)."""
    title = (listing.get("title") if isinstance(listing, dict) else listing) or ""
    t = title.lower()

    if s.numbered_to and f"/{s.numbered_to}" not in title:
        return False

    query = (getattr(s, "query", "") or "").lower()

    # Season-aware: if the query names a season, the title must contain it in some
    # common format. Drop it from the plain word check so the two years aren't
    # each required literally (a "2025-26" title has no standalone "2026").
    m = _SEASON_RE.search(query)
    if m:
        if not any(form in t for form in _season_forms(m.group(1), m.group(2))):
            return False
        query = query[:m.start()] + " " + query[m.end():]

    for word in re.split(r"[^a-z0-9]+", query):
        if len(word) >= 2 and word not in t:
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
