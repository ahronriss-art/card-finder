from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, Numeric, Numeric
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./cardfinder.db")

engine = create_async_engine(DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=True)
    phone = Column(String, unique=True, nullable=True)
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


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
