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

# Global minimum price for LISTED (Buy-It-Now) cards in alerts. Auctions are exempt.
LISTED_MIN_PRICE = 2000


def min_interval_for(n_active: int) -> float:
    """Smallest per-alert check interval (minutes) that keeps total scheduled
    eBay calls under the daily budget for `n_active` active alerts. With few
    alerts this is small (so user-chosen intervals win); with many it grows to
    automatically space checks out so the budget lasts all day."""
    if n_active <= 0:
        return 0.0
    return float(math.ceil(n_active * 1440 / SCHEDULED_DAILY_BUDGET))


_SEASON_RE = re.compile(r"(20\d{2})\s*[-/]\s*(\d{2,4})")

# Sport/league words eBay titles usually omit — don't require them in the match,
# so typing "NBA Jokic" still works (the player implies the sport).
_IGNORE_WORDS = {
    "nba", "nfl", "mlb", "nhl", "wnba", "mls", "ufc", "mma", "pga",
    "basketball", "football", "baseball", "hockey", "soccer", "golf",
    # generic card-category words sellers usually replace with the specific parallel name
    "insert", "inserts", "parallel", "parallels", "card", "cards",
}


def _season_regex(start: str, end: str):
    """Regex matching a season written any common way: '2025-26', '2025-2026',
    '2025/26', or even a bare '2025' — but NOT a different adjacent year like the
    2025 inside '2024-2025'."""
    end2 = end[-2:]
    end_full = int(start[:2] + end2)
    if end_full <= int(start):
        end_full += 100  # e.g. 1999-00 -> 2000
    return re.compile(rf"(?<![\d-]){start}(?:[-/](?:{end2}|{end_full}))?(?!\d)")


def _ebay_keywords(q: str) -> str:
    """Turn a saved-search query into permissive eBay search keywords. eBay matches
    keywords literally, so we: collapse a season range to the start year (2025-2026
    -> 2025, which eBay matches against '2025-26' titles), drop '/N' serial tokens,
    and remove ignored generic/sport words. The strict per-listing filter still
    enforces the real season, serial, and words."""
    s = q or ""
    s = re.sub(r"(20\d{2})\s*[-/]\s*\d{2,4}", r"\1", s)  # 2025-2026 / 2025-26 -> 2025
    s = re.sub(r"/\s*\d+", " ", s)                        # drop /5 serial tokens
    toks = [t for t in s.split() if t.lower() not in _IGNORE_WORDS]
    return re.sub(r"\s+", " ", " ".join(toks)).strip()


def passes_filters(s, listing) -> bool:
    """Strict post-filter on the listing title. eBay's search returns loosely
    related listings (not just exact matches), so we only alert when EVERY word
    the user typed is present in the title — no 'similar' cards. We keep words of
    2+ chars (including numbers like '10', '99', 'rc') so e.g. a 'PSA 10' search
    won't match a PSA 9, and only drop single-char noise. The print run ('/N') is
    enforced too. Seasons are matched format-agnostically (2025-2026 == 2025-26)."""
    title = (listing.get("title") if isinstance(listing, dict) else listing) or ""
    t = title.lower()

    # Enforce the exact serial print run, e.g. "/10" — but not "/100" or "/150"
    # (so a "numbered to 10" alert won't match a /100 card). Matches "/10",
    # "06/10", "/010", not "/100".
    if s.numbered_to and not re.search(rf"/0*{s.numbered_to}(?!\d)", title):
        return False

    query = (getattr(s, "query", "") or "").lower()

    # Season-aware: if the query names a season, the title must contain it in some
    # common format. Drop it from the plain word check so the two years aren't
    # each required literally (a "2025-26" title has no standalone "2026").
    m = _SEASON_RE.search(query)
    if m:
        if not _season_regex(m.group(1), m.group(2)).search(t):
            return False
        query = query[:m.start()] + " " + query[m.end():]

    for word in re.split(r"[^a-z0-9]+", query):
        if len(word) >= 2 and word not in _IGNORE_WORDS and word not in t:
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
    # Include eBay auctions. Price is filtered in code (below) so auctions — whose
    # current bid starts low — aren't dropped by the min price. Use cleaned keywords
    # so eBay returns matches regardless of season format ("2025-26" vs "2025-2026").
    listings = await search_cards(_ebay_keywords(q), None, None, limit=10, include_auctions=True)

    # Global floor: listed (Buy-It-Now) cards must be at least $2000. Auctions are
    # exempt (a low current bid can still climb). A higher per-alert min still wins.
    mn = max(search.min_price or 0, LISTED_MIN_PRICE)
    mx = search.max_price
    seen = set()
    deduped = []
    for l in listings:
        if not passes_filters(search, l):
            continue
        price = l.get("price") or 0
        is_auction = l.get("is_auction")
        # Fixed-price listings respect the price range; auctions are EXEMPT from the
        # minimum (a low current bid can still climb), but still honor a max if set.
        if not is_auction:
            if price < mn:
                continue
            if mx and price > mx:
                continue
        else:
            if mx and price > mx:
                continue
        if is_auction and l.get("title"):
            l["title"] = "🔨 [Auction] " + l["title"]
        eid = l.get("external_id")
        if eid in seen:
            continue
        seen.add(eid)
        deduped.append(l)
    return "ebay", deduped
