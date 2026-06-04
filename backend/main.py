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
import anthropic as _anthropic
_claude = _anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
from alerts import send_alert
from mock_data import MOCK_LISTINGS, MOCK_SOLD

USE_MOCK = False  # Browse API active


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
    check_interval_minutes: float = 15.0
    alert_method: str = "both"


# --- Routes ---

@app.post("/users")
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    if not data.email and not data.phone:
        raise HTTPException(400, "Email or phone required")
    user = User(email=data.email, phone=data.phone, alert_method=data.alert_method)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": user.id, "email": user.email, "phone": user.phone, "alert_method": user.alert_method}


@app.put("/users/{user_id}")
async def update_user(user_id: int, data: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if data.email: user.email = data.email
    if data.phone: user.phone = data.phone
    user.alert_method = data.alert_method
    await db.commit()
    return {"id": user.id, "email": user.email, "phone": user.phone, "alert_method": user.alert_method}


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
        check_interval_minutes=req.check_interval_minutes,
        alert_method=req.alert_method,
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
    return [{"id": s.id, "query": s.query, "sport": s.sport, "check_interval_minutes": s.check_interval_minutes, "alert_method": s.alert_method} for s in searches]


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


class ChatRequest(BaseModel):
    message: str
    history: list = []

@app.post("/chat")
async def chat(req: ChatRequest):
    """AI chatbot that helps write messages to card sellers/buyers."""
    system = """You are a sports card buying/selling expert assistant. Your job is to help users write clear, polite, and effective messages to eBay sellers or buyers.

When asked to write a message, always:
1. Write a ready-to-send message they can copy/paste
2. Keep it short, friendly, and professional
3. Be specific and direct
4. Format the message clearly, separated from any explanation

You can help with: making offers, negotiating prices, asking about condition, bundling deals, responding to offers, asking about shipping, requesting more photos, and any other buyer/seller communication."""

    history = []
    for msg in req.history[-6:]:
        history.append({"role": msg["role"], "content": msg["text"]})
    history.append({"role": "user", "content": req.message})

    try:
        response = _claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=system,
            messages=history,
        )
        reply = response.content[0].text
    except Exception as e:
        reply = f"Sorry, I couldn't generate a message right now. Error: {str(e)}"

    return {"reply": reply}


@app.post("/run-alert-check")
async def run_alert_check(db: AsyncSession = Depends(get_db)):
    """Check all active saved searches and send alerts for new listings.
    Triggered by the GitHub Actions cron every few minutes."""
    from datetime import datetime

    result = await db.execute(select(SavedSearch).where(SavedSearch.active == True))
    searches = result.scalars().all()

    checked = 0
    alerts_sent = 0

    for search in searches:
        # Respect each search's interval
        if search.last_checked_at:
            elapsed = (datetime.utcnow() - search.last_checked_at).total_seconds() / 60
            if elapsed < (search.check_interval_minutes or 15):
                continue

        query = f"{search.sport} {search.query}" if search.sport else search.query
        # First check ever? Seed the baseline silently (don't alert on existing listings)
        is_first_check = search.last_checked_at is None
        try:
            listings = await search_cards(query, search.min_price, search.max_price, limit=10)
        except Exception:
            continue
        search.last_checked_at = datetime.utcnow()
        checked += 1

        user_result = await db.execute(select(User).where(User.id == search.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            continue

        for listing in listings:
            ext_id = listing.get("external_id")
            existing = await db.execute(
                select(CardListing).where(
                    CardListing.external_id == ext_id,
                    CardListing.source == "ebay",
                )
            )
            if existing.scalar_one_or_none():
                continue

            db.add(CardListing(
                source="ebay", external_id=ext_id,
                title=listing.get("title"), price=listing.get("price"),
                listing_url=listing.get("listing_url"), image_url=listing.get("image_url"),
                seller_name=listing.get("seller_name"), condition=listing.get("condition"),
            ))

            # Only alert on genuinely new listings, not the initial baseline
            if not is_first_check:
                sold = await get_sold_history(query, limit=10)
                analysis = analyze_deal(listing, sold)
                send_alert(user, listing, analysis, method=search.alert_method)
                alerts_sent += 1

    await db.commit()
    return {"checked": checked, "alerts_sent": alerts_sent}


@app.get("/health")
async def health():
    return {"status": "ok"}
