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

# Global minimum price for LISTED (Buy-It-Now) cards in alerts. Auctions are
# judged by avg sold price >= this instead of current bid.
LISTED_MIN_PRICE = 1000

# Only alert on listings posted within this many hours (eBay itemCreationDate).
MAX_LISTING_AGE_HOURS = 24


def listed_recently(created, hours: int = MAX_LISTING_AGE_HOURS) -> bool:
    """True if the eBay listing was posted within `hours`. Missing/unparseable
    date -> False (we only alert on confirmed-recent listings)."""
    if not created:
        return False
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() <= hours * 3600
    except Exception:
        return False


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

# Common seller misspellings for hard-to-spell names. Only consulted when an
# alert has `catch_misspellings` on: the name word then ALSO matches any of these
# spellings in the title. eBay's own search is typo-tolerant and surfaces these
# listings, but the strict exact-spelling rule would otherwise reject them.
NAME_VARIANTS = {
    "wembanyama": ("wembanyma", "wembenyama", "wenbanyama", "wembanama", "wembanyana", "wembanyamma", "wembanyamma"),
    "antetokounmpo": ("antetokoumpo", "antetokuonmpo", "antetokounpo", "antetkounmpo", "antentokounmpo", "antetokounmpo"),
    "giannis": ("gianis", "giannnis"),
    "gilgeous": ("gilgeaus", "gilgious", "gigleous", "gilgeus"),
    "doncic": ("doncis", "donic", "doncici", "doncc", "dončić"),
    "jokic": ("jokick", "jocik", "jokik", "jokc", "jokić"),
    "edgecombe": ("edgecomb", "edgecome", "edgcombe", "edgecombre"),
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


# Map a sport/league word in the query to eBay's "Sport" item-aspect value, so a
# search that names a sport is restricted to that sport's cards (no cross-sport bleed).
_SPORT_ASPECTS = {
    "basketball": "Basketball", "nba": "Basketball", "wnba": "Basketball",
    "baseball": "Baseball", "mlb": "Baseball",
    "football": "Football", "nfl": "Football",
    "hockey": "Hockey", "nhl": "Hockey",
    "soccer": "Soccer", "fifa": "Soccer",
}


def detect_sport(text) -> str:
    """Return eBay's Sport aspect (e.g. 'Basketball') if the text names a sport/league,
    else None. Lets an 'NBA ...' search only return basketball cards."""
    words = set(re.split(r"[^a-z]+", (text or "").lower()))
    for kw, aspect in _SPORT_ASPECTS.items():
        if kw in words:
            return aspect
    return None


def _ebay_keywords(q: str) -> str:
    """Turn a saved-search query into permissive eBay search keywords. eBay matches
    keywords literally, so we: collapse a season range to the start year (2025-2026
    -> 2025, which eBay matches against '2025-26' titles), drop '/N' serial tokens,
    and remove ignored generic/sport words. The strict per-listing filter still
    enforces the real season, serial, and words."""
    s = q or ""
    s = _jp_to_english(s)                                 # リザードン -> charizard (US eBay is English)
    s = re.sub(r"(20\d{2})\s*[-/]\s*\d{2,4}", r"\1", s)  # 2025-2026 / 2025-26 -> 2025
    s = re.sub(r"/\s*\d+", " ", s)                        # drop /5 serial tokens
    toks = [t for t in s.split() if t.lower() not in _IGNORE_WORDS]
    return re.sub(r"\s+", " ", " ".join(toks)).strip()


# CJK = Chinese/Japanese/Korean. These scripts have no spaces between words, so
# the ASCII word-splitter drops them. We match contiguous CJK runs as substrings
# (e.g. a "リザードン" search must appear literally in the title). Covers Hiragana,
# Katakana (full + half-width), and CJK ideographs (kanji/hanzi).
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]+")

# Japanese term -> English/romaji aliases. US eBay lists most Japanese cards in
# English/romaji, so a Japanese search (リザードン) should also match "Charizard".
# The eBay search is translated to the first (English) alias so it returns results;
# matching then accepts the Japanese OR any alias. Extend as needed.
JP_ALIASES = {
    "ポケモンカード": ["pokemon card", "pokemon"],
    "ポケモン": ["pokemon"],
    "リザードン": ["charizard", "lizardon"],
    "ピカチュウ": ["pikachu"],
    "ミュウツー": ["mewtwo"],
    "ミュウ": ["mew"],
    "ルギア": ["lugia"],
    "レックウザ": ["rayquaza"],
    "ホウオウ": ["ho-oh", "hooh"],
    "イーブイ": ["eevee"],
    "ブラッキー": ["umbreon"],
    "エーフィ": ["espeon"],
    "ニンフィア": ["sylveon"],
    "リーフィア": ["leafeon"],
    "グレイシア": ["glaceon"],
    "シャワーズ": ["vaporeon"],
    "サンダース": ["jolteon"],
    "ブースター": ["flareon"],
    "ゲンガー": ["gengar"],
    "カメックス": ["blastoise"],
    "フシギバナ": ["venusaur"],
    "ミミッキュ": ["mimikyu"],
    "ギャラドス": ["gyarados"],
    "ルカリオ": ["lucario"],
    "ゾロアーク": ["zoroark"],
    "ガブリアス": ["garchomp"],
    "カイリュー": ["dragonite"],
    "ドラパルト": ["dragapult"],
    "サーナイト": ["gardevoir"],
    "リザード": ["charmeleon"],
    "ヒトカゲ": ["charmander"],
    "ナンジャモ": ["iono"],
    "リコ": ["liko"],
    "マリィ": ["marnie"],
    "ボスの指令": ["boss's orders"],
    "プロモ": ["promo"],
    "がんばリーリエ": ["lillie"],
    "リーリエ": ["lillie"],
    "アセロラ": ["acerola"],
    "ピカチュウカードゲーム": ["pikachu"],
}
# Longer keys first so substring replacement is greedy (ポケモンカード before ポケモン).
_JP_KEYS_BY_LEN = sorted(JP_ALIASES.keys(), key=len, reverse=True)


def _jp_to_english(text: str) -> str:
    """Replace known Japanese terms with their English alias (for the eBay search,
    since US eBay is English). Unknown Japanese is left as-is."""
    for k in _JP_KEYS_BY_LEN:
        if k in text:
            text = text.replace(k, " " + JP_ALIASES[k][0] + " ")
    return re.sub(r"\s+", " ", text).strip()


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

    # Serial typed in the KEYWORDS (e.g. "... /5") is enforced like the structured
    # print-run field — the title must actually be numbered to it. The leading
    # space/start guard means a season like "2025/26" isn't mistaken for a serial.
    for sm in re.finditer(r"(?:^|\s)/\s*(\d+)\b", query):
        if not re.search(rf"/0*{sm.group(1)}(?!\d)", title):
            return False

    # Season-aware: if the query names a season, the title must contain it in some
    # common format. Drop it from the plain word check so the two years aren't
    # each required literally (a "2025-26" title has no standalone "2026").
    m = _SEASON_RE.search(query)
    if m:
        if not _season_regex(m.group(1), m.group(2)).search(t):
            return False
        query = query[:m.start()] + " " + query[m.end():]

    catch = bool(getattr(s, "catch_misspellings", False))
    for word in re.split(r"[^a-z0-9]+", query):
        if len(word) < 2 or word in _IGNORE_WORDS or word in t:
            continue
        # Misspelling tolerance: a hard-to-spell name also matches its common
        # misspellings, but only when the alert opts in via catch_misspellings.
        if catch and word in NAME_VARIANTS and any(v in t for v in NAME_VARIANTS[word]):
            continue
        return False

    # Japanese/Chinese/Korean: each contiguous CJK run in the query must appear in
    # the title — OR its English/romaji alias does (US eBay titles Japanese cards in
    # English). So "リザードン" matches a title with リザードン, "charizard", or
    # "lizardon". Also satisfied if a known Japanese sub-term's alias is present.
    for run in _CJK_RE.findall(query):
        if run in t:
            continue
        aliases = list(JP_ALIASES.get(run, []))
        for k in _JP_KEYS_BY_LEN:               # sub-terms within an unspaced run
            if k in run:
                aliases += JP_ALIASES[k]
        if aliases and any(a in t for a in aliases):
            continue
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


def classify_health(s, listings) -> dict:
    """Shared alert-health classifier for the linter and the daily scan. Given a
    search-like object and the eBay listings for its keywords, returns
    {status, messages, suggestions, stats}. status is 'ok' | 'narrow' | 'dead'."""
    titles = [(l.get("title") or "").lower() for l in listings]
    q = (getattr(s, "query", "") or "").lower()
    m = _SEASON_RE.search(q)
    if m:
        q = q[:m.start()] + " " + q[m.end():]
    words = [w for w in re.split(r"[^a-z0-9]+", q) if len(w) >= 2 and w not in _IGNORE_WORDS]
    missing = [w for w in words if not any(w in t for t in titles)]
    passed = [l for l in listings if passes_filters(s, l)]
    floor = max(getattr(s, "min_price", None) or 0, LISTED_MIN_PRICE)
    priced = [l for l in passed if l.get("is_auction") or (l.get("price") or 0) >= floor]

    rev = {mis: canon for canon, variants in NAME_VARIANTS.items() for mis in variants}
    msgs, sugg, status = [], [], "ok"
    for w in words:
        if w in rev:
            sugg.append(f"“{w}” looks misspelled — try “{rev[w]}”.")

    if not listings:
        status = "dead"
        msgs.append("eBay returns no results for these keywords — likely a typo or a term sellers don't use in titles.")
    elif not passed:
        status = "dead"
        if missing:
            msgs.append("This won't match: no listing title contains " + ", ".join(f"“{w}”" for w in missing) + ".")
        else:
            msgs.append("eBay has listings, but no single title contains all your terms together — too restrictive to match.")
        if any(w == "base" for w in words):
            sugg.append("Drop the word “base” — titles almost never include it.")
        if re.search(r"/\s*\d+", getattr(s, "query", "") or ""):
            sugg.append("A “/N” serial typed in the keywords forces that number into the title — usually drop it.")
    elif not priced:
        status = "narrow"
        msgs.append(f"{len(passed)} matches, but all are under ${floor:.0f} right now — it will only alert when one lists at or above your minimum.")
    else:
        msgs.append(f"Looks good — {len(passed)} live matches, {len(priced)} at/above ${floor:.0f}.")

    if len(listings) >= 40 and status == "ok":
        msgs.append("Heads up: broad (50+ results). Fine with newest-first sorting + hourly checks, but a more specific search is more precise.")
    for w in words:
        if w in NAME_VARIANTS and not getattr(s, "catch_misspellings", False):
            sugg.append(f"Consider turning on “catch misspellings” — “{w}” is often misspelled by sellers.")
            break

    return {"status": status, "messages": msgs, "suggestions": sugg,
            "stats": {"results": len(listings), "matches": len(passed), "priced": len(priced)}}


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
    # Auctions are opt-in per alert (off by default) — they don't have a real price
    # floor, so broad alerts would flood. Cleaned keywords so eBay returns matches
    # regardless of season format ("2025-26" vs "2025-2026").
    inc_auctions = bool(getattr(search, "include_auctions", False))
    sport = detect_sport(q)  # NBA/MLB/etc. in the query -> restrict eBay to that sport
    listings = await search_cards(_ebay_keywords(q), None, None, limit=50, include_auctions=inc_auctions, sport=sport)

    # Global floor: listed (Buy-It-Now) cards must be at least $1000. Auctions are
    # exempt (a low current bid can still climb). A higher per-alert min still wins.
    mn = max(search.min_price or 0, LISTED_MIN_PRICE)
    mx = search.max_price
    seen = set()
    deduped = []
    for l in listings:
        if not passes_filters(search, l):
            continue
        # Only alert on cards posted within the last 24h — no old listings.
        if not listed_recently(l.get("created_at")):
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
        if is_auction and l.get("title") and not str(l["title"]).startswith("🔨"):
            l = {**l, "title": "🔨 [Auction] " + l["title"]}  # copy, don't mutate cached dict
        eid = l.get("external_id")
        if eid in seen:
            continue
        seen.add(eid)
        deduped.append(l)
    return "ebay", deduped
