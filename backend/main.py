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
from agents.price_analyst import analyze_deal
from agents.misspelling_finder import generate_misspellings
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

    listings, sold = await asyncio.gather(
        search_cards(query, req.min_price, req.max_price),
        get_sold_history(query),
    )

    enriched = []
    for listing in listings:
        analysis = analyze_deal(listing, sold)
        enriched.append({**listing, "analysis": analysis})

    return {
        "listings": enriched,
        "sold_history": sold[:10],
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


@app.post("/search-misspellings")
async def search_misspellings(req: SearchRequest):
    """Search eBay for misspelled versions of the query to find hidden deals."""
    misspellings = generate_misspellings(req.query)
    if not misspellings:
        return {"listings": [], "misspellings_tried": []}

    if USE_MOCK:
        mock_results = []
        for ms in misspellings[:3]:
            mock_results.append({
                "source": "ebay",
                "external_id": f"mock-ms-{hash(ms)}",
                "title": f"{ms} Rookie Card PSA 9 (Misspelled Listing)",
                "price": 420.00,
                "listing_url": "https://ebay.com",
                "seller_name": "cardseller",
                "condition": "Graded",
                "is_sold": False,
                "misspelled": True,
                "misspelling_used": ms,
                "analysis": {"verdict": "great_deal", "avg_sold_price": 867.0, "pct_vs_market": -51.6,
                             "summary": "Misspelled listing — fewer buyers will find this, so it may sell for less.", "sample_size": 5},
            })
        return {"listings": mock_results, "misspellings_tried": misspellings}

    all_listings = []
    sold = await get_sold_history(req.query)

    for misspelling in misspellings:
        listings = await search_cards(misspelling, limit=5)
        for listing in listings:
            analysis = analyze_deal(listing, sold)
            all_listings.append({
                **listing,
                "misspelled": True,
                "misspelling_used": misspelling,
                "analysis": analysis,
            })

    return {"listings": all_listings, "misspellings_tried": misspellings}


@app.get("/health")
async def health():
    return {"status": "ok"}
