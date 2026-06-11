"""One-way sync from the live Google Sheet (the 'Final' tab) into card_shops.

The sheet is published as CSV (link-viewable). We map columns by header,
then UPSERT by (name, full_address): existing shops get any non-empty sheet
cells applied (never blanked), and rows not yet in the DB are inserted.
This means edits you make on the website are preserved unless the sheet has
a value for that exact field.
"""
import csv
import io
import os
import httpx
from sqlalchemy import select

from database import CardShop

SHEET_ID = os.getenv("SHEET_ID", "1t6oyf3VWtOBFxfFk-dB8G7zFjtPOcY1om4NkosDYmgE")
SHEET_GID = os.getenv("SHEET_GID", "1352272092")  # the 'Final' tab
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={SHEET_GID}"

# sheet header (lowercased) -> CardShop field
HEADER_MAP = {
    "shop name": "name",
    "website": "website",
    "phone": "phone",
    "full_address": "full_address",
    "city": "city",
    "state": "state",
    "rating": "rating",
    "reviews": "reviews",
    "email": "email",
    "contact way": "contact_way",
    "tiktok handle": "tiktok",
    "whatnot handle": "whatnot",
    "direct account with topps/fanatics": "topps_fanatics",
    "buy from wholesalers": "buys_wholesale",
    "direct account with tcg": "tcg_account",
    "willing to wholesale with our wholesale department?": "willing_to_wholesale",
    "collectors they've been selling with": "collectors",
}
# "Instagram Links" is a spreadsheet formula mirroring the unnamed status
# column, so we skip it. Column index 9 (blank header) is the contacted flag.
CONTACTED_COL = 9


def _clean(v):
    if v is None:
        return None
    v = str(v).strip()
    if not v or v.startswith("="):
        return None
    return v


def _parse_csv(text: str) -> list[dict]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    header = [(h or "").strip().lower() for h in rows[0]]
    col_field = {i: HEADER_MAP[h] for i, h in enumerate(header) if h in HEADER_MAP}
    col_field.setdefault(CONTACTED_COL, "contacted")

    out = []
    for r in rows[1:]:
        rec = {}
        for i, field in col_field.items():
            if i < len(r):
                rec[field] = _clean(r[i])
        name = rec.get("name")
        if not name:
            continue
        for nf in ("rating", "reviews"):
            if rec.get(nf) is not None:
                try:
                    rec[nf] = int(float(rec[nf])) if nf == "reviews" else float(rec[nf])
                except ValueError:
                    rec[nf] = None
        out.append(rec)
    return out


async def sync_from_sheet(session) -> dict:
    """Fetch the sheet and upsert into the DB. Returns a summary dict."""
    resp = httpx.get(CSV_URL, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    records = _parse_csv(resp.text)
    if not records:
        return {"checked": 0, "added": 0, "updated": 0, "fields_changed": 0}

    valid = {c.name for c in CardShop.__table__.columns}

    result = await session.execute(select(CardShop))
    shops = result.scalars().all()
    by_key = {}
    for s in shops:
        key = (s.name or "").lower().strip() + "|" + (s.full_address or "").lower().strip()
        by_key.setdefault(key, s)

    added = updated = fields_changed = 0
    for rec in records:
        key = (rec.get("name") or "").lower().strip() + "|" + (rec.get("full_address") or "").lower().strip()
        existing = by_key.get(key)
        if existing is None:
            data = {k: v for k, v in rec.items() if k in valid and v is not None}
            data["shop_type"] = "shop"
            new_shop = CardShop(**data)
            session.add(new_shop)
            by_key[key] = new_shop
            added += 1
            continue
        # apply only non-empty sheet cells that differ — never blank existing data
        changed_here = False
        for field, value in rec.items():
            if field not in valid or value is None or value == "":
                continue
            if getattr(existing, field, None) != value:
                setattr(existing, field, value)
                fields_changed += 1
                changed_here = True
        if changed_here:
            updated += 1

    await session.commit()
    return {"checked": len(records), "added": added, "updated": updated, "fields_changed": fields_changed}
