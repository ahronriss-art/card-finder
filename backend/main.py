from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel
from typing import Optional
import asyncio
from contextlib import asynccontextmanager

import os
from database import init_db, get_db, User, SavedSearch, CardListing
from scrapers.ebay_scraper import search_cards, get_sold_history
from scrapers.cardladder_scraper import search_cardladder, get_cardladder_sales
from scrapers.alt_scraper import search_alt
from agents.price_analyst import analyze_deal
from alerts import send_alert
from mock_data import MOCK_LISTINGS, MOCK_SOLD

USE_MOCK = True  # switch to False once eBay key is active


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(title="Card Finder API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Schemas ---

class UserCreate(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    alert_method: str = "email"


class SearchRequest(BaseModel):
    query: str
    sport: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None


class SaveSearchRequest(BaseModel):
    user_id: int
    query: str
    sport: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None


# --- Routes ---

@app.post("/users")
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    if not data.email and not data.phone:
        raise HTTPException(400, "Email or phone required")
    user = User(email=data.email, phone=data.phone, alert_method=data.alert_method)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "email": user.email, "phone": user.phone}


@app.post("/search")
async def search(req: SearchRequest):
    """Search for cards and return listings with price analysis."""
    if USE_MOCK:
        enriched = []
        for listing in MOCK_LISTINGS:
            analysis = analyze_deal(listing, MOCK_SOLD)
            enriched.append({**listing, "analysis": analysis})
        return {"listings": enriched, "sold_history": MOCK_SOLD[:10], "total": len(enriched), "mock": True}

    query = req.query
    if req.sport:
        query = f"{req.sport} {query}"

    ebay_listings, sold, cl_listings, alt_listings, cl_sold = await asyncio.gather(
        search_cards(query, req.min_price, req.max_price),
        get_sold_history(query),
        search_cardladder(query),
        search_alt(query),
        get_cardladder_sales(query),
    )

    all_sold = sold + cl_sold
    all_listings = ebay_listings + cl_listings + alt_listings

    enriched = []
    for listing in all_listings:
        analysis = analyze_deal(listing, all_sold)
        enriched.append({**listing, "analysis": analysis})

    return {
        "listings": enriched,
        "sold_history": all_sold[:10],
        "total": len(enriched),
    }


@app.get("/sold-history")
async def sold_history(query: str, sport: Optional[str] = None):
    """Get recently sold cards to show market value."""
    q = f"{sport} {query}" if sport else query
    sold = await get_sold_history(q, limit=30)
    prices = [s["sold_price"] for s in sold if s.get("sold_price")]
    avg = round(sum(prices) / len(prices), 2) if prices else None
    return {"sold": sold, "avg_price": avg, "count": len(sold)}


@app.post("/saved-searches")
async def save_search(req: SaveSearchRequest, db: AsyncSession = Depends(get_db)):
    search = SavedSearch(
        user_id=req.user_id,
        query=req.query,
        sport=req.sport,
        min_price=req.min_price,
        max_price=req.max_price,
    )
    db.add(search)
    await db.commit()
    await db.refresh(search)
    return {"id": search.id, "query": search.query}


@app.get("/saved-searches/{user_id}")
async def get_saved_searches(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SavedSearch).where(SavedSearch.user_id == user_id, SavedSearch.active == True)
    )
    searches = result.scalars().all()
    return [{"id": s.id, "query": s.query, "sport": s.sport} for s in searches]


@app.delete("/saved-searches/{search_id}")
async def delete_search(search_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SavedSearch).where(SavedSearch.id == search_id))
    search = result.scalar_one_or_none()
    if not search:
        raise HTTPException(404, "Search not found")
    search.active = False
    await db.commit()
    return {"deleted": True}


@app.get("/health")
async def health():
    return {"status": "ok"}
