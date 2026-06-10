"""One-time: convert the 'Final' sheet of Sports Card Shop.xlsx into shops_seed.json.

Maps columns by header name (robust to reordering), cleans values, dedupes on
(name, full_address), and writes backend/data/shops_seed.json which the app uses
to seed the database on first startup (works for both SQLite and Render Postgres).
"""
import json
import os
import openpyxl

XLSX = os.environ.get("SHOPS_XLSX", "/Users/ahronriss/Downloads/Sports Card Shop.xlsx")
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "shops_seed.json")

# header text in the sheet  ->  field name in our model
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


def clean(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        # drop leftover spreadsheet formulas
        if v.startswith("="):
            return None
        return v or None
    return v


def main():
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb["Final"]
    rows = list(ws.iter_rows(values_only=True))
    header = [(h or "").strip().lower() if isinstance(h, str) else h for h in rows[0]]

    # build index -> field
    col_field = {}
    for idx, h in enumerate(header):
        if isinstance(h, str) and h in HEADER_MAP:
            col_field[idx] = HEADER_MAP[h]
    # column J (index 9) is an unnamed "contacted?" status flag (e.g. "yes(Mike)")
    col_field.setdefault(9, "contacted")

    shops = []
    seen = set()
    for r in rows[1:]:
        rec = {}
        for idx, field in col_field.items():
            if idx < len(r):
                rec[field] = clean(r[idx])
        name = rec.get("name")
        if not name:
            continue
        # numeric coercion
        for nf in ("rating", "reviews"):
            if isinstance(rec.get(nf), str):
                try:
                    rec[nf] = float(rec[nf])
                except ValueError:
                    rec[nf] = None
        if rec.get("reviews") is not None:
            rec["reviews"] = int(rec["reviews"])
        key = (name.lower(), (rec.get("full_address") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        shops.append(rec)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(shops, f, indent=1, ensure_ascii=False)
    print(f"Wrote {len(shops)} shops to {os.path.abspath(OUT)}")
    # quick stats
    states = {}
    for s in shops:
        states[s.get("state")] = states.get(s.get("state"), 0) + 1
    print("Top states:", sorted(states.items(), key=lambda x: -x[1])[:8])


if __name__ == "__main__":
    main()
