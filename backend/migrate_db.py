"""One-time data migration: copy ALL rows from one Postgres to another.

Use it to move off Render's expiring free Postgres onto Neon (or any Postgres)
without losing your users, alerts, shop edits, etc.

Usage (from backend/, with the venv active):
    python migrate_db.py "<SOURCE_URL>" "<DEST_URL>"

  SOURCE_URL = your current Render *External* Database URL
               (Render dashboard -> card-finder-db -> Connect -> External)
  DEST_URL   = your new Neon connection string
               (looks like postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require)

It creates the schema on the destination (from the app's models), then copies
every table. Safe to re-run — it clears each destination table first.
"""
import asyncio
import sys
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from database import Base  # all table definitions live here


def _to_async(url: str):
    """Normalize a Postgres URL to the asyncpg driver + SSL connect args."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    needs_ssl = "sslmode" in url
    p = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(p.query) if k not in ("sslmode", "channel_binding")]
    url = urlunsplit((p.scheme, p.netloc, p.path, urlencode(kept), p.fragment))
    return url, ({"ssl": True} if needs_ssl else {})


async def main(src_raw: str, dst_raw: str):
    su, sa = _to_async(src_raw)
    du, da = _to_async(dst_raw)
    src = create_async_engine(su, connect_args=sa)
    dst = create_async_engine(du, connect_args=da)

    # 1) Build the schema on the destination from the app's models.
    print("Creating schema on destination…")
    async with dst.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2) Copy each table (only the columns the models define, so it's robust).
    for table in Base.metadata.sorted_tables:
        name = table.name
        cols = [c.name for c in table.columns]
        collist = ", ".join(f'"{c}"' for c in cols)

        async with src.connect() as sc:
            rows = (await sc.execute(text(f'SELECT {collist} FROM "{name}"'))).mappings().all()

        async with dst.begin() as dc:
            await dc.execute(text(f'DELETE FROM "{name}"'))  # idempotent re-runs
            if rows:
                placeholders = ", ".join(f":{c}" for c in cols)
                stmt = text(f'INSERT INTO "{name}" ({collist}) VALUES ({placeholders})')
                for r in rows:
                    await dc.execute(stmt, dict(r))
        print(f"  {name}: copied {len(rows)} rows")

    # 3) Reset id sequences so new inserts don't collide with copied PKs.
    async with dst.begin() as dc:
        for table in Base.metadata.sorted_tables:
            try:
                await dc.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1))"
                ))
            except Exception:
                pass  # table has no serial 'id' (e.g. app_flags)

    await src.dispose()
    await dst.dispose()
    print("Done. Now set DATABASE_URL on Render to the Neon URL and redeploy.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python migrate_db.py \"<SOURCE_URL>\" \"<DEST_URL>\"")
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
