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

# eBay calls/day reserved for scheduled alert checks. Pushed close to the ~4500
# daily safety cap so the Chrome Update alerts run as fast as the quota allows;
# the ~300 that remain cover sold-history, the search page and card lookup. If
# those start reporting "daily budget reached", this is the number to lower.
SCHEDULED_DAILY_BUDGET = 4200

# Default minimum price for an alert, applied to fixed-price listings and to an
# auction's current bid alike. Nothing under this ever alerts unless the alert
# sets its own lower min_price.
LISTED_MIN_PRICE = 1000


def listed_floor(search) -> float:
    """The price floor this alert actually enforces on listed (Buy-It-Now) cards.

    An alert that sets its own min_price gets exactly that number — including
    below the global default, so a niche where the good cards trade under the
    default (scarce serials in a set the market underprices) can still be watched. Alerts
    that set nothing fall back to LISTED_MIN_PRICE, which is what keeps a broad
    search from flooding. Previously this was a max() of the two, so a per-alert
    minimum could only ever raise the floor, never lower it."""
    mn = getattr(search, "min_price", None)
    return float(mn) if mn else float(LISTED_MIN_PRICE)

# Only alert on listings posted within this many hours (eBay itemCreationDate).
# 48h = "the last couple of days" — a wider cushion so a recent listing isn't
# missed. The gap-aware window in gather_alert_listings widens this further after
# an outage; the per-search alert_seen dedup keeps it from re-alerting seen cards.
MAX_LISTING_AGE_HOURS = 48

# Most pages of 50 one alert check will pull when a busy query outruns a single
# page. Only spent when the listings actually run past the page edge, so quiet
# alerts still cost one call; this caps the worst case on release night.
MAX_SEARCH_PAGES = 5


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
    automatically space checks out so the budget lasts all day.

    This assumes every alert runs at the SAME rate. When alerts have different
    intervals (a fast lane for the ones that actually match, slow for the rest),
    use plan_intervals instead — this function can't express that."""
    if n_active <= 0:
        return 0.0
    return float(math.ceil(n_active * 1440 / SCHEDULED_DAILY_BUDGET))


# Never check faster than the scheduler heartbeat — a smaller number just burns
# quota on cycles that can't happen anyway. Keep in step with _ALERT_INTERVAL_S.
MIN_CHECK_INTERVAL = 3.0


def plan_intervals(wanted: dict, budget: int = SCHEDULED_DAILY_BUDGET,
                   priority: frozenset = frozenset()) -> dict:
    """Turn each unique search's REQUESTED interval into an affordable one.

    `wanted` maps a unique-search key -> requested interval in minutes. One eBay
    call serves every alert sharing a key, so cost is summed per key, not per
    alert: a key checked every N minutes costs 1440/N calls a day.

    If the plan fits the budget it's returned untouched, so a deliberate fast
    lane stays fast. If it doesn't, intervals are stretched to fit — but keys in
    `priority` (new-release watches) are held at their requested rate and the
    whole stretch is absorbed by everyone else. A fresh release is the one case
    where being minutes late means the card is gone, so those alerts are the
    last thing that should slow down when the budget gets tight.

    Non-priority keys are never stretched past a day — past that an alert is
    effectively off, and silently disabling it is worse than overspending a
    little. If priority alone exceeds the budget, priority keys stretch among
    themselves (nothing else can give)."""
    if not wanted:
        return {}
    safe = {k: max(float(v or 60.0), MIN_CHECK_INTERVAL) for k, v in wanted.items()}
    planned = sum(1440.0 / v for v in safe.values())
    if planned <= budget:
        return safe

    prio = {k: v for k, v in safe.items() if k in priority}
    rest = {k: v for k, v in safe.items() if k not in priority}
    prio_cost = sum(1440.0 / v for v in prio.values())

    # Priority can't be paid for even alone -> stretch priority, park the rest.
    if not rest or prio_cost >= budget:
        stretch = max(prio_cost / float(budget), 1.0) if prio else planned / float(budget)
        out = {k: v * stretch for k, v in (prio or safe).items()}
        out.update({k: 1440.0 for k in rest})
        return out

    rest_cost = sum(1440.0 / v for v in rest.values())
    stretch = rest_cost / (float(budget) - prio_cost)
    out = dict(prio)
    out.update({k: min(v * stretch, 1440.0) for k, v in rest.items()})
    return out


_SEASON_RE = re.compile(r"(20\d{2})\s*[-/]\s*(\d{2,4})")

# Sport/league words eBay titles usually omit — don't require them in the match,
# so typing "NBA Jokic" still works (the player implies the sport).
_IGNORE_WORDS = {
    "nba", "nfl", "mlb", "nhl", "wnba", "mls", "ufc", "mma", "pga",
    "basketball", "football", "baseball", "hockey", "soccer", "golf",
    # generic card-category words sellers usually replace with the specific parallel name
    "insert", "inserts", "parallel", "parallels", "card", "cards",
}

# Common seller misspellings for hard-to-spell names. Always consulted: the name
# word ALSO matches any of these spellings in the title. eBay's own search is
# typo-tolerant and surfaces these listings, but the strict exact-spelling rule
# would otherwise reject them.
NAME_VARIANTS = {
    "wembanyama": ("wembanyma", "wembenyama", "wenbanyama", "wembanama", "wembanyana", "wembanyamma", "wembanyamma"),
    "antetokounmpo": ("antetokoumpo", "antetokuonmpo", "antetokounpo", "antetkounmpo", "antentokounmpo", "antetokounmpo"),
    "giannis": ("gianis", "giannnis"),
    "gilgeous": ("gilgeaus", "gilgious", "gigleous", "gilgeus"),
    "doncic": ("doncis", "donic", "doncici", "doncc", "dončić"),
    "jokic": ("jokick", "jocik", "jokik", "jokc", "jokić"),
    "edgecombe": ("edgecomb", "edgecome", "edgcombe", "edgecombre"),
    # not a name, but the same tolerance helps: sellers drop the trailing "r" or
    # otherwise fumble this word constantly (e.g. "Red Lava Refracto 3/5").
    "refractor": ("refracto", "refracter", "refractator", "refracator", "reftractor", "refrator", "refractr"),
}


def _within_edits(a: str, b: str, max_edits: int) -> bool:
    """True if `a` and `b` are within `max_edits` Levenshtein edits. Bounded DP
    with an early-exit when a whole row exceeds the budget, so it stays cheap on
    the short strings we feed it."""
    la, lb = len(a), len(b)
    if abs(la - lb) > max_edits:
        return False
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ca = a[i - 1]
        best = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if cur[j] < best:
                best = cur[j]
        if best > max_edits:
            return False
        prev = cur
    return prev[lb] <= max_edits


def _fuzzy_edit_budget(word: str) -> int:
    """How many typos we tolerate in a query word, by length. Short words share
    too many near-neighbours (gold/bold, kobe/kope) so they get 0 — only longer,
    distinctive words earn a budget. Numbers/grades never reach here."""
    n = len(word)
    if n < 6:
        return 0
    if n <= 9:
        return 1
    return 2


def _fuzzy_in_title(word: str, title_tokens) -> bool:
    """True if some title token is a plausible misspelling of `word` (within its
    edit budget). Only alphabetic words qualify — anything with a digit (serials,
    grades like 'psa10', years) must match exactly, never fuzzily."""
    if not word.isalpha():
        return False
    budget = _fuzzy_edit_budget(word)
    if budget == 0:
        return False
    for tok in title_tokens:
        if len(tok) < 4 or not tok.isalpha():
            continue
        if abs(len(tok) - len(word)) > budget:
            continue
        if _within_edits(word, tok, budget):
            return True
    return False


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

    title_tokens = [w for w in re.split(r"[^a-z0-9]+", t) if w]
    for word in re.split(r"[^a-z0-9]+", query):
        if len(word) < 2 or word in _IGNORE_WORDS or word in t:
            continue
        # Misspelling tolerance: a query word also matches a plausible seller
        # typo in the title. Applied to EVERY search — this is purely additive
        # (it only rescues a near-miss, never rejects), so no listing is lost to
        # a title typo. Two layers: (1) a curated variant list for phonetic/
        # hard-to-spell cases beyond simple edit distance, then (2) a general
        # edit-distance fallback for any longish word. Always on for every
        # alert — there is no toggle.
        if word in NAME_VARIANTS and any(v in t for v in NAME_VARIANTS[word]):
            continue
        if _fuzzy_in_title(word, title_tokens):
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
    floor = listed_floor(s)
    priced = [l for l in passed if (l.get("price") or 0) >= floor]

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
    # No "turn on catch misspellings" suggestion any more — misspelling tolerance
    # is unconditional for every alert (see passes_filters), so there is nothing
    # left to switch on.

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

    # Page back far enough to cover everything posted since this alert last ran.
    # A busy release query can push 50 listings in half an hour, so a single page
    # of 50 quietly drops whatever posted before the page edge — the cards would
    # never be seen at all, not merely seen late. Cheap in the normal case: one
    # page already covers a quiet query, and a priority alert running every few
    # minutes never needs a second call.
    from datetime import datetime as _dtm, timedelta as _td
    _lc = getattr(search, "last_checked_at", None)
    cover_from = (_lc - _td(minutes=10)) if _lc else (_dtm.utcnow() - _td(hours=MAX_LISTING_AGE_HOURS))
    listings = await search_cards(_ebay_keywords(q), None, None, limit=50,
                                  include_auctions=inc_auctions, sport=sport,
                                  cover_since=cover_from.isoformat() + "Z",
                                  max_pages=MAX_SEARCH_PAGES)

    # The 24h gate below reads created_at (eBay's itemCreationDate). listed_recently()
    # fails closed, so if that field ever disappears from the Browse response every
    # alert silently drops to zero with nothing to show for it. Check the raw batch —
    # before any filtering — so a systemic field outage is distinguishable from a
    # normal quiet stretch where listings simply aren't recent.
    if listings:
        n_no_date = sum(1 for l in listings if not l.get("created_at"))
        if n_no_date == len(listings):
            print(f"ALERT WARNING: all {len(listings)} eBay listings for {q!r} are missing "
                  "created_at — the 24h freshness gate will drop every one of them. "
                  "Check that itemCreationDate is still in the Browse response.")
        elif n_no_date > len(listings) // 2:
            print(f"ALERT WARNING: {n_no_date}/{len(listings)} eBay listings for {q!r} "
                  "are missing created_at — alerts may be suppressed.")

    # Price floor for listed (Buy-It-Now) cards: the alert's own min_price if it
    # sets one, else the $1000 default. Auctions are exempt (a low current bid can
    # still climb).
    mn = listed_floor(search)
    mx = search.max_price
    seen = set()
    deduped = []
    # Age window: normally 24h, but if this search hasn't been checked in longer
    # than that (e.g. the service was down for a day), widen the window to cover
    # the gap so listings posted during the outage still alert instead of aging
    # out permanently. The eBay item-id dedup (CardListing) prevents re-alerting
    # anything already seen; a 7-day cap avoids a flood after a long dormancy.
    from datetime import datetime as _dt
    window_h = MAX_LISTING_AGE_HOURS
    lca = getattr(search, "last_checked_at", None)
    if lca:
        gap_h = (_dt.utcnow() - lca).total_seconds() / 3600
        window_h = min(max(MAX_LISTING_AGE_HOURS, gap_h + 2), 7 * 24)
    for l in listings:
        if not passes_filters(search, l):
            continue
        # Only alert on cards posted within the (gap-aware) window — no old listings.
        if not listed_recently(l.get("created_at"), window_h):
            continue
        price = l.get("price") or 0
        is_auction = l.get("is_auction")
        # Both fixed-price and auction listings respect the price range, judged on
        # the listing's OWN price (current bid for an auction). Auctions used to be
        # exempt from the minimum here and gated instead on the avg sold price of
        # the alert's query — but that compared a rare parallel against the base
        # cards the broad query returns ($104 avg for "Moments In Time"), so real
        # four-figure auctions were dropped. The current bid is the honest number.
        # An auction that starts under the floor isn't recorded in CardListing, so
        # it stays eligible and alerts on a later cycle once the bid crosses it.
        if price < mn:
            continue
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
