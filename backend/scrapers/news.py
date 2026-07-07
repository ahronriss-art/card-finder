"""Card-world news feed, aggregated from Google News RSS.

Most card-news sites block bots, but Google News RSS is server-fetchable and
aggregates dozens of outlets. We run a few category queries (general / auctions /
pulls / releases), merge, de-dupe, and sort by recency. Cached ~30 min.
"""
from __future__ import annotations
import re
import time
import html as _html
from email.utils import parsedate_to_datetime

import httpx

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# (category, query). Ordered so the general feed leads.
_QUERIES = [
    ("news", "sports cards trading cards"),
    ("auctions", "sports card auction sold record"),
    ("pulls", "sports card rare pull pack"),
    ("releases", "Topps Panini Bowman card release"),
    ("grading", "PSA BGS card grading"),
]

_cache: dict = {}
_TTL = 30 * 60  # 30 minutes


def _rss_url(query: str, days: int = 14) -> str:
    from urllib.parse import quote
    return (f"https://news.google.com/rss/search?q={quote(query)}+when:{days}d"
            f"&hl=en-US&gl=US&ceid=US:en")


def _parse_feed(xml: str, category: str) -> list:
    out = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        tm = re.search(r"<title>(.*?)</title>", item, re.S)
        lm = re.search(r"<link>(.*?)</link>", item, re.S)
        dm = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        sm = re.search(r"<source[^>]*>(.*?)</source>", item, re.S)
        if not tm or not lm:
            continue
        title = _html.unescape(tm.group(1)).strip()
        source = _html.unescape(sm.group(1)).strip() if sm else ""
        # Google News titles end with " - Source"; drop it for a clean headline.
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()
        ts = 0.0
        iso = None
        if dm:
            try:
                d = parsedate_to_datetime(dm.group(1).strip())
                ts = d.timestamp()
                iso = d.isoformat()
            except Exception:
                pass
        out.append({
            "title": title, "url": _html.unescape(lm.group(1)).strip(),
            "source": source, "published": iso, "category": category, "_ts": ts,
        })
    return out


async def fetch_card_news() -> list:
    """Return recent card-world news [{title, url, source, published, category}],
    newest first, de-duped. Cached ~30 min. Returns [] on total failure."""
    hit = _cache.get("news")
    if hit and time.time() < hit[0]:
        return hit[1]

    items, seen = [], set()
    async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                 headers={"User-Agent": _UA}) as client:
        for category, query in _QUERIES:
            try:
                r = await client.get(_rss_url(query))
                if r.status_code != 200:
                    continue
                for it in _parse_feed(r.text, category):
                    key = it["title"].lower()[:80]
                    if key in seen or len(it["title"]) < 12:
                        continue
                    seen.add(key)
                    items.append(it)
            except Exception:
                continue

    items.sort(key=lambda x: x["_ts"], reverse=True)
    for it in items:
        it.pop("_ts", None)
    items = items[:60]
    if items:
        _cache["news"] = (time.time() + _TTL, items)
    return items
