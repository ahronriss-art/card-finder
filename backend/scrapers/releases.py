"""Auto-import the upcoming card-release calendar from ChecklistInsider.

ChecklistInsider's /release-calendar page is server-fetchable (unlike Topps/
Beckett, which block bots) and — crucially — puts EXPLICIT ISO dates in the
static HTML (`datetime="2026-07-01..."`) grouped by month, so there's no
year-guessing. We parse product + date straight from the markup (no AI needed).
Degrades gracefully: any parse hiccup yields fewer rows, never a crash.
"""
from __future__ import annotations
import re
import html as _html
from datetime import date, datetime

import httpx

SOURCE_URL = "https://www.checklistinsider.com/release-calendar"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

_SPORTS = [
    ("Basketball", "Basketball"), ("Baseball", "Baseball"), ("Football", "Football"),
    ("Hockey", "Hockey"), ("Soccer", "Soccer"), ("UFC", "UFC"), ("Wrestling", "Wrestling"),
    ("Golf", "Golf"), ("Pokemon", "Pokemon"), ("Marvel", "Entertainment"),
    ("Star Trek", "Entertainment"), ("Star Wars", "Entertainment"), ("WWE", "Wrestling"),
    ("F1", "Racing"), ("Racing", "Racing"), ("Multi-Sport", "Multi-Sport"),
]
_BRANDS = ["Topps", "Bowman", "Panini", "Upper Deck", "Leaf", "Rittenhouse",
           "Fanatics", "Donruss", "Sage", "Wild Card"]


def _clean_name(name: str) -> str:
    name = _html.unescape(name or "").strip()
    # ChecklistInsider suffixes every title with these — strip for a clean product.
    name = re.sub(r"\s+(Checklist Guide|Checklist and Review|Checklists and Review|"
                  r"Set Review and Checklist|Checklist|Guide|Review)\s*$", "", name, flags=re.I).strip()
    name = re.sub(r"\s+(Sealed|Hobby|Retail)?\s*(box|thumb).*$", "", name, flags=re.I).strip()
    return re.sub(r"\s+", " ", name)


def _detect_sport(name: str):
    low = name.lower()
    for kw, sport in _SPORTS:
        if kw.lower() in low:
            return sport
    return None


def _detect_brand(name: str):
    for b in _BRANDS:
        if b.lower() in name.lower():
            return b
    # else first token that isn't a year
    for tok in name.split():
        if not re.match(r"^(19|20)\d\d", tok) and len(tok) > 2:
            return tok
    return None


def _parse(doc: str, upcoming_only: bool = True) -> list:
    today = date.today()
    out, seen = [], set()
    for block in doc.split("release-date-stamp")[1:]:
        dm = re.search(r'datetime="(\d{4})-(\d{2})-(\d{2})', block)
        if not dm:
            continue
        y, mo, d = (int(x) for x in dm.groups())
        try:
            dt = date(y, mo, d)
        except ValueError:
            continue
        if upcoming_only and dt < today:
            continue
        am = re.search(r'alt="([^"]{4,140})"', block)
        slug = re.search(r'checklistinsider\.com/([a-z0-9-]+)"', block)
        raw = am.group(1) if am else (slug.group(1).replace("-", " ").title() if slug else "")
        name = _clean_name(raw)
        if not name:
            continue
        key = (name.lower(), dt.isoformat())
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "product": name,
            "release_date": dt.isoformat(),
            "date_text": dt.strftime("%b %-d, %Y"),
            "sport": _detect_sport(name),
            "brand": _detect_brand(name),
        })
    out.sort(key=lambda r: r["release_date"])
    return out


async def fetch_upcoming_releases(upcoming_only: bool = True) -> list:
    """Return [{product, release_date(ISO), date_text, sport, brand}] for upcoming
    card releases, soonest first. Raises on a failed fetch so the caller can 502."""
    async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                                 headers={"User-Agent": _UA}) as client:
        resp = await client.get(SOURCE_URL)
        resp.raise_for_status()
    return _parse(resp.text, upcoming_only=upcoming_only)
