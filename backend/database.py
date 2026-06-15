from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, Numeric, Numeric
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

_RAW_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./cardfinder.db")
DATABASE_URL = _RAW_DATABASE_URL

# Render/Neon/etc. provide "postgres://..." — convert to the async driver format
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Hosted Postgres (Neon, Supabase, …) put libpq params like ?sslmode=require in the
# URL, which asyncpg rejects. Strip them and enable SSL explicitly so any free
# Postgres connection string works by just setting DATABASE_URL.
_connect_args = {}
if "asyncpg" in DATABASE_URL:
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    needs_ssl = "sslmode" in _RAW_DATABASE_URL
    parts = urlsplit(DATABASE_URL)
    kept = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("sslmode", "channel_binding")]
    DATABASE_URL = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
    if needs_ssl:
        # ssl for hosted Postgres; statement_cache_size=0 so asyncpg works through
        # Neon/Supabase connection poolers (PgBouncer transaction mode).
        _connect_args = {"ssl": True, "statement_cache_size": 0}

engine = create_async_engine(DATABASE_URL, connect_args=_connect_args)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=True)
    phone = Column(String, unique=True, nullable=True)
    carrier = Column(String, nullable=True)  # for free email-to-SMS texts
    alert_method = Column(String, default="email")  # "email", "sms", or "both"
    created_at = Column(DateTime, default=datetime.utcnow)


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    query = Column(String)
    sport = Column(String, nullable=True)
    min_price = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)
    numbered_to = Column(Integer, nullable=True)  # serial print run, e.g. 99 for /99
    brand = Column(String, nullable=True)        # Topps, Bowman, Panini Prizm, …
    insert_type = Column(String, nullable=True)  # Refractor, Gold, Black, Cherry Blossom, …
    card_number = Column(String, nullable=True)  # e.g. 150 -> "#150"
    year = Column(String, nullable=True)         # e.g. 2023
    exclude = Column(String, nullable=True)      # words to exclude, e.g. "reprint lot"
    source = Column(String, default="ebay")      # "ebay" listings or "auction" (Goldin live lots)
    dry_spell_months = Column(Integer, nullable=True)  # auction: only alert if no sale in N months
    check_interval_minutes = Column(Float, default=15.0)
    last_checked_at = Column(DateTime, nullable=True)
    alert_method = Column(String, default="both")  # "email", "sms", or "both"
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AppFlag(Base):
    __tablename__ = "app_flags"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)


class CardListing(Base):
    __tablename__ = "card_listings"
    id = Column(Integer, primary_key=True)
    source = Column(String)          # "ebay", "comc", etc.
    external_id = Column(String)
    title = Column(String)
    price = Column(Float)
    condition = Column(String, nullable=True)
    sport = Column(String, nullable=True)
    player = Column(String, nullable=True)
    year = Column(String, nullable=True)
    card_set = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    listing_url = Column(String)
    seller_name = Column(String, nullable=True)
    seller_contact = Column(String, nullable=True)
    is_sold = Column(Boolean, default=False)
    sold_price = Column(Float, nullable=True)
    sold_at = Column(DateTime, nullable=True)
    listed_at = Column(DateTime, default=datetime.utcnow)
    raw_data = Column(Text, nullable=True)


class CardShop(Base):
    __tablename__ = "card_shops"
    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)
    website = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    full_address = Column(String, nullable=True)
    city = Column(String, nullable=True, index=True)
    state = Column(String, nullable=True, index=True)
    rating = Column(Float, nullable=True)
    reviews = Column(Integer, nullable=True)
    email = Column(String, nullable=True)
    instagram = Column(String, nullable=True)
    tiktok = Column(String, nullable=True)
    whatnot = Column(String, nullable=True)
    contact_way = Column(String, nullable=True)
    contacted = Column(String, nullable=True)
    topps_fanatics = Column(String, nullable=True)
    tcg_account = Column(String, nullable=True)
    buys_wholesale = Column(String, nullable=True)
    willing_to_wholesale = Column(String, nullable=True)
    collectors = Column(String, nullable=True)
    shop_type = Column(String, default="shop")      # "shop" | "whatnot_breaker"
    notes = Column(Text, nullable=True)            # running free-text log
    update_log = Column(Text, nullable=True)        # JSON history of AI updates
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Fields the AI update box / manual edits may write to (keeps routes & prompts in sync)
SHOP_EDITABLE_FIELDS = [
    "name", "website", "phone", "full_address", "city", "state", "rating", "reviews",
    "email", "instagram", "tiktok", "whatnot", "contact_way", "contacted",
    "topps_fanatics", "tcg_account", "buys_wholesale", "willing_to_wholesale",
    "collectors", "notes",
]


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns)
    await seed_shops()


def _ensure_columns(conn):
    """Add columns added after a table was first created (lightweight migration
    for the already-deployed Postgres / local SQLite). Idempotent."""
    from sqlalchemy import inspect, text
    insp = inspect(conn)
    existing = {c["name"] for c in insp.get_columns("card_shops")}
    if "shop_type" not in existing:
        conn.execute(text("ALTER TABLE card_shops ADD COLUMN shop_type VARCHAR"))
        conn.execute(text("UPDATE card_shops SET shop_type = 'shop' WHERE shop_type IS NULL"))

    saved_cols = {c["name"] for c in insp.get_columns("saved_searches")}
    if "numbered_to" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN numbered_to INTEGER"))
    for col in ("brand", "insert_type", "card_number", "year", "exclude"):
        if col not in saved_cols:
            conn.execute(text(f"ALTER TABLE saved_searches ADD COLUMN {col} VARCHAR"))
    if "source" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN source VARCHAR"))
        conn.execute(text("UPDATE saved_searches SET source = 'ebay' WHERE source IS NULL"))
    if "dry_spell_months" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN dry_spell_months INTEGER"))


async def seed_shops():
    """Insert any shops from shops_seed.json that aren't already in the DB.
    Idempotent — matches on (name, full_address) so it tops up existing
    databases (local SQLite or Render Postgres) without duplicating or
    overwriting your edits."""
    import json
    from sqlalchemy import select

    seed_path = os.path.join(os.path.dirname(__file__), "data", "shops_seed.json")
    if not os.path.exists(seed_path):
        return

    with open(seed_path) as f:
        shops = json.load(f)
    valid = {c.name for c in CardShop.__table__.columns}

    async with AsyncSessionLocal() as session:
        rows = await session.execute(select(CardShop.name, CardShop.full_address))
        existing = {(n or "").lower().strip() + "|" + (a or "").lower().strip() for n, a in rows.all()}
        added = 0
        for rec in shops:
            key = (rec.get("name") or "").lower().strip() + "|" + (rec.get("full_address") or "").lower().strip()
            if key in existing:
                continue
            existing.add(key)
            data = {k: v for k, v in rec.items() if k in valid}
            session.add(CardShop(**data))
            added += 1
        if added:
            await session.commit()
            print(f"Seeded {added} new card shops")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
