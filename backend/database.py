from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, Numeric, Numeric
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./cardfinder.db")

# Render provides Postgres URLs as "postgres://..." — convert to async driver format
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL)
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
    await seed_shops()


async def seed_shops():
    """Load shops_seed.json into the DB once, if the table is empty.
    Works for both SQLite (local) and Postgres (Render)."""
    import json
    from sqlalchemy import select, func

    seed_path = os.path.join(os.path.dirname(__file__), "data", "shops_seed.json")
    if not os.path.exists(seed_path):
        return

    async with AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(CardShop))
        if count and count > 0:
            return
        with open(seed_path) as f:
            shops = json.load(f)
        valid = {c.name for c in CardShop.__table__.columns}
        for rec in shops:
            data = {k: v for k, v in rec.items() if k in valid}
            session.add(CardShop(**data))
        await session.commit()
        print(f"Seeded {len(shops)} card shops")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
