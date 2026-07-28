"""Two-way sync between the master_shops table and a Google Sheet.

Reads/writes through a Google service account (gspread). Config from env:
  MASTER_SHEET_ID     - the spreadsheet id (from its URL)
  MASTER_SHEET_TAB    - worksheet/tab name (default "Shops")
  GOOGLE_SA_JSON_B64  - base64 of the service-account JSON key

`record_id` (the sheet's 'Record ID', e.g. R-0001) is the join key. Sheet-owned
columns (MASTER_SHEET_MAP) flow both ways; site-owned columns (contacted,
contact_name, contact_phone, call_notes, contacted_by, active) live only in the
DB and are never written to the sheet. Column positions are resolved by HEADER
name each run, so the sheet can add/reorder columns without breaking sync.

Nothing here runs until sync_enabled() is true (env configured).
"""
import os
import json
import base64
import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select

from database import MasterShop, MASTER_SHEET_MAP, MASTER_NUMERIC

SHEET_ID = os.getenv("MASTER_SHEET_ID", "")
SHEET_TAB = os.getenv("MASTER_SHEET_TAB", "Shops")
_SA_ENV = "GOOGLE_SA_JSON_B64"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def sync_enabled() -> bool:
    """True only when both the sheet id and the service-account key are set."""
    return bool(os.getenv("MASTER_SHEET_ID") and os.getenv(_SA_ENV))


# ---------------------------------------------------------------- gspread glue
def _client():
    import gspread
    from google.oauth2.service_account import Credentials
    raw = os.getenv(_SA_ENV, "")
    if not raw:
        raise RuntimeError(f"{_SA_ENV} not set")
    info = json.loads(base64.b64decode(raw))
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def _ws():
    sh = _client().open_by_key(os.getenv("MASTER_SHEET_ID", SHEET_ID))
    try:
        return sh.worksheet(os.getenv("MASTER_SHEET_TAB", SHEET_TAB))
    except Exception:
        return sh.sheet1


def _norm(h) -> str:
    return str(h or "").strip().lower()


def _context(ws):
    """(all_rows, header_row_index, {attr: 0-based col index}). Header row is the
    one containing 'record id' or 'shop name' — tolerant of intro rows above it."""
    rows = ws.get_all_values()
    hdr_i = 0
    for i, row in enumerate(rows):
        low = [_norm(c) for c in row]
        if "record id" in low or "shop name" in low:
            hdr_i = i
            break
    headers = [_norm(c) for c in rows[hdr_i]] if rows else []
    attr_col = {}
    for ci, h in enumerate(headers):
        attr = MASTER_SHEET_MAP.get(h)
        if attr and attr not in attr_col:      # first matching column wins
            attr_col[attr] = ci
    return rows, hdr_i, attr_col


def _coerce(attr: str, val: str):
    """Sheet cell (string) -> python value for the DB."""
    s = (val or "").strip()
    if attr in MASTER_NUMERIC:
        if not s:
            return None
        try:
            n = float(s.replace(",", ""))
            return int(n) if attr in ("num_reviews", "confidence_score") else n
        except ValueError:
            return None
    return s or None


def _fmt(val) -> str:
    """Python value -> sheet cell string."""
    if val is None:
        return ""
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


# ------------------------------------------------------------------- pull (sheet -> db)
async def pull_sync(replace: bool = False) -> dict:
    """Read the whole sheet and upsert into master_shops by record_id. Sheet rows
    with no Record ID get one assigned and written back so both sides stay keyed.
    Site-owned columns are preserved. When `replace` is true, master_shops rows
    whose record_id is no longer in the sheet are deleted (use when switching to a
    different sheet). Returns a summary."""
    if not sync_enabled():
        return {"ok": False, "reason": "sync not configured", "at": None}

    def _read():
        ws = _ws()
        rows, hdr_i, attr_col = _context(ws)
        parsed, backfill = [], []
        for ri in range(hdr_i + 1, len(rows)):
            row = rows[ri]
            rec = {attr: (row[ci] if ci < len(row) else "") for attr, ci in attr_col.items()}
            name = (rec.get("name") or "").strip()
            if not name or name.upper().startswith("EXAMPLE"):
                continue  # skip the yellow template row and blanks
            rid = (rec.get("record_id") or "").strip()
            if not rid:
                rid = "R-" + uuid.uuid4().hex[:10]
                rec["record_id"] = rid
                if "record_id" in attr_col:
                    backfill.append((ri + 1, attr_col["record_id"] + 1, rid))  # 1-based
            rec["_row"] = ri + 1
            parsed.append(rec)
        if backfill:
            import gspread
            ws.update_cells([gspread.cell.Cell(r, c, v) for r, c, v in backfill])
        return parsed

    parsed = await asyncio.to_thread(_read)

    from database import AsyncSessionLocal
    created = updated = deleted = 0
    seen_ids = set()
    async with AsyncSessionLocal() as db:
        for rec in parsed:
            rid = rec["record_id"]
            seen_ids.add(rid)
            shop = (await db.execute(select(MasterShop).where(MasterShop.record_id == rid))).scalar_one_or_none()
            if not shop:
                shop = MasterShop(record_id=rid)
                db.add(shop)
                created += 1
            else:
                updated += 1
            for attr, val in rec.items():
                if attr.startswith("_") or attr == "record_id":
                    continue
                setattr(shop, attr, _coerce(attr, val))
            shop.sheet_row = rec["_row"]
            shop.synced_at = datetime.utcnow()
        if replace:
            stale = (await db.execute(select(MasterShop).where(MasterShop.record_id.notin_(seen_ids)))).scalars().all()
            for s in stale:
                await db.delete(s)
            deleted = len(stale)
        await db.commit()

    return {"ok": True, "created": created, "updated": updated, "deleted": deleted,
            "total": len(parsed), "at": datetime.utcnow().isoformat()}


# ------------------------------------------------------------------- push (db -> sheet)
def _row_values_for(shop: dict, attr_col: dict, width: int) -> list:
    """Build a full sheet row (list of cell strings) for a shop, filling only the
    sheet-owned columns we know; other columns left blank for a fresh append."""
    row = [""] * width
    for attr, ci in attr_col.items():
        if ci < width:
            row[ci] = _fmt(shop.get(attr))
    return row


async def push_shop(shop: dict) -> dict:
    """Write one shop's SHEET-OWNED fields back to its sheet row (by sheet_row or
    record_id). If it isn't in the sheet yet, append it. `shop` is a plain dict of
    MasterShop attributes. No-op when sync isn't configured."""
    if not sync_enabled():
        return {"ok": False, "reason": "sync not configured"}

    def _write():
        import gspread
        ws = _ws()
        rows, hdr_i, attr_col = _context(ws)
        width = len(rows[hdr_i]) if rows else max(attr_col.values(), default=0) + 1
        rid = (shop.get("record_id") or "").strip()

        # locate the row: prefer the record_id column, else the stored sheet_row
        target = None
        rid_col = attr_col.get("record_id")
        if rid and rid_col is not None:
            for ri in range(hdr_i + 1, len(rows)):
                cell = rows[ri][rid_col] if rid_col < len(rows[ri]) else ""
                if (cell or "").strip() == rid:
                    target = ri + 1
                    break
        if target is None and shop.get("sheet_row"):
            target = int(shop["sheet_row"])

        if target is None:
            # not in the sheet yet -> append a new row
            ws.append_row(_row_values_for(shop, attr_col, width), value_input_option="USER_ENTERED")
            return {"ok": True, "action": "appended", "record_id": rid}

        cells = []
        for attr, ci in attr_col.items():
            cells.append(gspread.cell.Cell(target, ci + 1, _fmt(shop.get(attr))))
        if cells:
            ws.update_cells(cells, value_input_option="USER_ENTERED")
        return {"ok": True, "action": "updated", "row": target, "record_id": rid}

    return await asyncio.to_thread(_write)


async def append_shop(shop: dict) -> dict:
    """Append a site-created shop as a new sheet row, assigning a record_id if it
    has none. Returns {record_id, row}. No-op when sync isn't configured."""
    if not sync_enabled():
        return {"ok": False, "reason": "sync not configured", "record_id": shop.get("record_id")}
    if not shop.get("record_id"):
        shop["record_id"] = "R-" + uuid.uuid4().hex[:10]

    def _write():
        ws = _ws()
        rows, hdr_i, attr_col = _context(ws)
        width = len(rows[hdr_i]) if rows else max(attr_col.values(), default=0) + 1
        ws.append_row(_row_values_for(shop, attr_col, width), value_input_option="USER_ENTERED")
        return {"ok": True, "record_id": shop["record_id"], "row": len(rows) + 1}

    return await asyncio.to_thread(_write)
