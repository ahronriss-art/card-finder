from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from pydantic import BaseModel
from typing import Optional
import asyncio
import json
from datetime import datetime
from contextlib import asynccontextmanager

import os
from database import init_db, get_db, User, SavedSearch, CardListing, CardShop, SHOP_EDITABLE_FIELDS
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
    asyncio.create_task(_run_sheet_sync())  # best-effort sync on startup, non-blocking
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
    carrier: Optional[str] = None
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
    numbered_to: Optional[int] = None
    check_interval_minutes: float = 15.0
    alert_method: str = "both"


class UpdateSearchRequest(BaseModel):
    query: str
    sport: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    numbered_to: Optional[int] = None
    check_interval_minutes: float = 15.0
    alert_method: str = "both"


# --- Routes ---

@app.post("/users")
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    if not data.email and not data.phone:
        raise HTTPException(400, "Email or phone required")

    # If a user with this email or phone already exists, update & reuse it (don't error)
    existing = None
    if data.email:
        r = await db.execute(select(User).where(User.email == data.email))
        existing = r.scalar_one_or_none()
    if not existing and data.phone:
        r = await db.execute(select(User).where(User.phone == data.phone))
        existing = r.scalar_one_or_none()

    if existing:
        if data.email: existing.email = data.email
        if data.phone: existing.phone = data.phone
        if data.carrier is not None: existing.carrier = data.carrier
        existing.alert_method = data.alert_method
        await db.commit()
        await db.refresh(existing)
        user = existing
    else:
        user = User(email=data.email, phone=data.phone, carrier=data.carrier, alert_method=data.alert_method)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return {"id": user.id, "email": user.email, "phone": user.phone, "carrier": user.carrier, "alert_method": user.alert_method}


@app.put("/users/{user_id}")
async def update_user(user_id: int, data: UserCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if data.email: user.email = data.email
    if data.phone: user.phone = data.phone
    if data.carrier is not None: user.carrier = data.carrier
    user.alert_method = data.alert_method
    await db.commit()
    return {"id": user.id, "email": user.email, "phone": user.phone, "carrier": user.carrier, "alert_method": user.alert_method}


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
        numbered_to=req.numbered_to,
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
    return [{"id": s.id, "query": s.query, "sport": s.sport, "min_price": s.min_price, "max_price": s.max_price, "numbered_to": s.numbered_to, "check_interval_minutes": s.check_interval_minutes, "alert_method": s.alert_method} for s in searches]


@app.put("/saved-searches/{search_id}")
async def update_search(search_id: int, req: UpdateSearchRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SavedSearch).where(SavedSearch.id == search_id))
    search = result.scalar_one_or_none()
    if not search:
        raise HTTPException(404, "Search not found")
    # Full overwrite: the edit form always sends the complete state, so a None
    # here means the user cleared that filter (e.g. removed the price range).
    search.query = req.query
    search.sport = req.sport
    search.min_price = req.min_price
    search.max_price = req.max_price
    search.numbered_to = req.numbered_to
    search.check_interval_minutes = req.check_interval_minutes
    search.alert_method = req.alert_method
    # Re-baseline on next run so edits take effect cleanly without alert spam.
    search.last_checked_at = None
    await db.commit()
    return {"updated": True}


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

    # Build a single prompt including recent history (Gemini handles plain text)
    convo = ""
    for msg in req.history[-6:]:
        role = "User" if msg["role"] == "user" else "Assistant"
        convo += f"{role}: {msg['text']}\n"
    convo += f"User: {req.message}"

    try:
        import ai
        reply = ai.generate(convo, system=system, max_tokens=500)
    except Exception as e:
        reply = f"Sorry, I couldn't generate a message right now. Error: {str(e)}"

    return {"reply": reply}


@app.get("/run-alert-check")
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
        if search.numbered_to:
            query = f"{query} /{search.numbered_to}"
        # First check ever? Seed the baseline silently (don't alert on existing listings)
        is_first_check = search.last_checked_at is None
        try:
            listings = await search_cards(query, search.min_price, search.max_price, limit=10)
        except Exception:
            continue
        # Strict: only keep cards actually stamped with the requested print run
        if search.numbered_to:
            token = f"/{search.numbered_to}"
            listings = [l for l in listings if token in (l.get("title") or "")]
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

    # One-time: notify when Twilio toll-free SMS verification gets approved
    await _check_tollfree_approval(db)

    # Periodically pull the latest from the Google Sheet (throttled to ~15 min)
    synced = await _maybe_sync_sheet(db)

    return {"checked": checked, "alerts_sent": alerts_sent, "sheet_synced": synced}


async def _maybe_sync_sheet(db, min_minutes: float = 15.0) -> bool:
    """Run the sheet sync only if it hasn't run in the last `min_minutes`."""
    from database import AppFlag
    try:
        flag = await db.get(AppFlag, "sheet_last_sync")
        if flag and flag.value:
            last = datetime.fromisoformat(json.loads(flag.value).get("at"))
            if (datetime.utcnow() - last).total_seconds() < min_minutes * 60:
                return False
    except Exception:
        pass
    await _run_sheet_sync()
    return True


async def _check_tollfree_approval(db: AsyncSession):
    from database import AppFlag
    try:
        flag = await db.get(AppFlag, "tollfree_notified")
        if flag and flag.value == "yes":
            return  # already notified

        import httpx
        sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        token = os.getenv("TWILIO_AUTH_TOKEN", "")
        if not sid or not token:
            return
        r = httpx.get("https://messaging.twilio.com/v1/Tollfree/Verifications", auth=(sid, token), timeout=15)
        verifications = r.json().get("verifications", [])
        if not verifications:
            return
        status = verifications[0].get("status", "")

        # Twilio uses TWILIO_APPROVED for approved toll-free verifications
        if status == "TWILIO_APPROVED":
            from alerts import send_email_alert
            send_email_alert(
                "ahronriss@gmail.com",
                "Your Twilio SMS is APPROVED — text alerts are now live!",
                0, "https://card-finder-seven.vercel.app", "great_deal", 0,
            )
            db.add(AppFlag(key="tollfree_notified", value="yes"))
            await db.commit()
    except Exception as e:
        print(f"Toll-free check error: {e}")


@app.get("/tollfree-status")
async def tollfree_status():
    """Return current Twilio toll-free verification status."""
    import httpx
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    try:
        r = httpx.get("https://messaging.twilio.com/v1/Tollfree/Verifications", auth=(sid, token), timeout=15)
        vs = r.json().get("verifications", [])
        return {"status": vs[0].get("status") if vs else "none", "submitted": vs[0].get("date_created") if vs else None}
    except Exception as e:
        return {"error": str(e)}


# --- Card Shops directory (password-gated) ---

SHOPS_PASSWORD = os.getenv("SHOPS_PASSWORD", "cards")  # override in prod via env


def require_shop_access(x_shops_password: Optional[str] = Header(None)):
    """Single shared-password gate for all shop routes."""
    if not x_shops_password or x_shops_password != SHOPS_PASSWORD:
        raise HTTPException(401, "Invalid or missing access password")
    return True


def serialize_shop(s: CardShop) -> dict:
    return {
        "id": s.id, "name": s.name, "website": s.website, "phone": s.phone,
        "full_address": s.full_address, "city": s.city, "state": s.state,
        "rating": s.rating, "reviews": s.reviews, "email": s.email,
        "instagram": s.instagram, "tiktok": s.tiktok, "whatnot": s.whatnot,
        "contact_way": s.contact_way, "contacted": s.contacted,
        "topps_fanatics": s.topps_fanatics, "tcg_account": s.tcg_account,
        "buys_wholesale": s.buys_wholesale, "willing_to_wholesale": s.willing_to_wholesale,
        "collectors": s.collectors, "notes": s.notes,
        "shop_type": s.shop_type or "shop",
        "update_log": json.loads(s.update_log) if s.update_log else [],
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


class ShopUpsert(BaseModel):
    name: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    full_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None
    email: Optional[str] = None
    instagram: Optional[str] = None
    tiktok: Optional[str] = None
    whatnot: Optional[str] = None
    contact_way: Optional[str] = None
    contacted: Optional[str] = None
    topps_fanatics: Optional[str] = None
    tcg_account: Optional[str] = None
    buys_wholesale: Optional[str] = None
    willing_to_wholesale: Optional[str] = None
    collectors: Optional[str] = None
    notes: Optional[str] = None


class AIUpdateRequest(BaseModel):
    text: str


@app.post("/shops/check-password")
async def shops_check_password(_: bool = Depends(require_shop_access)):
    """Lets the frontend validate the password before storing it."""
    return {"ok": True}


@app.get("/shops/states")
async def shop_states(_: bool = Depends(require_shop_access), db: AsyncSession = Depends(get_db)):
    """Distinct states with shop counts, for the filter dropdown."""
    result = await db.execute(
        select(CardShop.state, func.count()).group_by(CardShop.state).order_by(CardShop.state)
    )
    return [{"state": st, "count": c} for st, c in result.all() if st]


@app.get("/shops")
async def list_shops(
    q: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    contacted: Optional[str] = None,  # "yes" | "no"
    shop_type: Optional[str] = None,  # "shop" | "whatnot_breaker"
    min_rating: Optional[float] = None,
    min_reviews: Optional[int] = None,
    has_website: Optional[bool] = None,
    has_email: Optional[bool] = None,
    has_phone: Optional[bool] = None,
    has_instagram: Optional[bool] = None,
    topps_fanatics: Optional[bool] = None,      # has a Topps/Fanatics account noted
    willing_to_wholesale: Optional[bool] = None,
    sort: str = "name",  # name | rating | reviews
    limit: int = 50,
    offset: int = 0,
    _: bool = Depends(require_shop_access),
    db: AsyncSession = Depends(get_db),
):
    f = dict(q=q, state=state, city=city, contacted=contacted, shop_type=shop_type,
             min_rating=min_rating, min_reviews=min_reviews, has_website=has_website,
             has_email=has_email, has_phone=has_phone, has_instagram=has_instagram,
             topps_fanatics=topps_fanatics, willing_to_wholesale=willing_to_wholesale, sort=sort)
    stmt = _build_shop_query(f)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.limit(min(limit, 200)).offset(offset)
    result = await db.execute(stmt)
    shops = result.scalars().all()
    return {"shops": [serialize_shop(s) for s in shops], "total": total or 0}


def _build_shop_query(f: dict):
    """Build a filtered+ordered CardShop query from a dict of filter values.
    Shared by /shops and /shops/ask."""
    def filled(col):
        return (col.isnot(None)) & (col != "")

    stmt = select(CardShop)
    if f.get("q"):
        # Match each word independently so "502 Frank" finds "502frank",
        # and word order/spacing doesn't matter.
        for word in str(f["q"]).split():
            like = f"%{word}%"
            stmt = stmt.where(or_(
                CardShop.name.ilike(like), CardShop.full_address.ilike(like),
                CardShop.city.ilike(like), CardShop.email.ilike(like),
            ))
    if f.get("shop_type"):
        stmt = stmt.where(CardShop.shop_type == f["shop_type"])
    if f.get("state"):
        stmt = stmt.where(CardShop.state == f["state"])
    if f.get("city"):
        stmt = stmt.where(CardShop.city.ilike(f"%{f['city']}%"))
    if f.get("contacted") == "yes":
        stmt = stmt.where(filled(CardShop.contacted))
    elif f.get("contacted") == "no":
        stmt = stmt.where(or_(CardShop.contacted.is_(None), CardShop.contacted == ""))
    if f.get("min_rating") is not None:
        stmt = stmt.where(CardShop.rating >= f["min_rating"])
    if f.get("min_reviews") is not None:
        stmt = stmt.where(CardShop.reviews >= f["min_reviews"])
    if f.get("has_website"):
        stmt = stmt.where(filled(CardShop.website))
    if f.get("has_email"):
        stmt = stmt.where(filled(CardShop.email))
    if f.get("has_phone"):
        stmt = stmt.where(filled(CardShop.phone))
    if f.get("has_instagram"):
        stmt = stmt.where(filled(CardShop.instagram))
    if f.get("topps_fanatics"):
        stmt = stmt.where(filled(CardShop.topps_fanatics))
    if f.get("willing_to_wholesale"):
        stmt = stmt.where(filled(CardShop.willing_to_wholesale))

    order = {
        "rating": CardShop.rating.desc().nullslast(),
        "reviews": CardShop.reviews.desc().nullslast(),
    }.get(f.get("sort"), CardShop.name)
    return stmt.order_by(order)


@app.post("/shops/ask")
async def ask_shops(req: AIUpdateRequest, _: bool = Depends(require_shop_access), db: AsyncSession = Depends(get_db)):
    """Natural-language Q&A over the shop database: Groq picks filters,
    we run them, then Groq answers from the real matching rows."""
    import ai
    question = (req.text or "").strip()
    if not question:
        raise HTTPException(400, "Empty question")
    try:
        filters = ai.nl_to_shop_filters(question)
    except Exception:
        filters = {}
    stmt = _build_shop_query(filters)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(50))
    shops = [serialize_shop(s) for s in result.scalars().all()]
    try:
        answer = ai.answer_shop_question(question, shops, total or 0)
    except Exception as e:
        answer = f"Found {total} matching shops, but couldn't generate a summary ({e})."
    return {"answer": answer, "filters": filters, "shops": shops, "total": total or 0}


# --- Auctions: card sales Q&A (password-gated, reuses the Shops password) ---

@app.post("/auctions/ask")
async def auctions_ask(req: AIUpdateRequest, _: bool = Depends(require_shop_access)):
    """Natural-language Q&A about a card's auction/sale history. We extract the
    card from the question, gather sales from PSA APR + Goldin (best-effort, often
    blocked) and eBay (live), then have the AI answer grounded in the real rows."""
    import ai
    from scrapers import auction_scraper

    question = (req.text or "").strip()
    if not question:
        raise HTTPException(400, "Empty question")

    card_query = ai.nl_to_card_query(question)

    psa, goldin = await asyncio.gather(
        auction_scraper.psa_apr_sales(card_query),
        auction_scraper.goldin_sales(card_query),
    )

    try:
        ebay_rows = await get_sold_history(card_query, limit=20)
    except Exception:
        ebay_rows = []
    ebay_sales = [{
        "source": "ebay", "auction_house": "eBay",
        "title": r.get("title"), "sold_price": r.get("sold_price"),
        "sold_at": r.get("sold_at") or "", "grade": "",
        "listing_url": r.get("listing_url"), "image_url": r.get("image_url"),
    } for r in ebay_rows if r.get("sold_price")]

    sales = (psa["sales"] + goldin["sales"] + ebay_sales)[:30]
    sources = [
        psa and {"name": psa["name"], "status": psa["status"], "count": len(psa["sales"])},
        goldin and {"name": goldin["name"], "status": goldin["status"], "count": len(goldin["sales"])},
        {"name": "eBay", "status": "ok" if ebay_sales else "no data", "count": len(ebay_sales)},
    ]

    answer = ai.answer_card_question(question, sales, sources)
    return {"answer": answer, "card_query": card_query, "sales": sales, "sources": sources}


async def _run_sheet_sync() -> dict:
    """Run the Google Sheet sync and record the outcome in app_flags."""
    from database import AppFlag
    import sheet_sync
    async with AsyncSessionLocal() as session:
        try:
            summary = await sheet_sync.sync_from_sheet(session)
        except Exception as e:
            print(f"Sheet sync failed: {e}")
            return {"error": str(e)}
        # store last-sync info
        info = json.dumps({"at": datetime.utcnow().isoformat(), **summary})
        flag = await session.get(AppFlag, "sheet_last_sync")
        if flag:
            flag.value = info
        else:
            session.add(AppFlag(key="sheet_last_sync", value=info))
        await session.commit()
        print(f"Sheet sync: {summary}")
        return summary


from database import AsyncSessionLocal  # noqa: E402


@app.post("/shops/sync-from-sheet")
async def sync_from_sheet_route(_: bool = Depends(require_shop_access)):
    """Manual 'Sync now' — pulls the latest from the Google Sheet."""
    summary = await _run_sheet_sync()
    return summary


@app.get("/shops/sync-status")
async def sync_status(_: bool = Depends(require_shop_access), db: AsyncSession = Depends(get_db)):
    from database import AppFlag
    flag = await db.get(AppFlag, "sheet_last_sync")
    return json.loads(flag.value) if flag and flag.value else {"at": None}


@app.get("/shops/{shop_id}")
async def get_shop(shop_id: int, _: bool = Depends(require_shop_access), db: AsyncSession = Depends(get_db)):
    s = await db.get(CardShop, shop_id)
    if not s:
        raise HTTPException(404, "Shop not found")
    return serialize_shop(s)


@app.post("/shops")
async def create_shop(data: ShopUpsert, _: bool = Depends(require_shop_access), db: AsyncSession = Depends(get_db)):
    if not data.name:
        raise HTTPException(400, "Shop name required")
    shop = CardShop(**data.model_dump(exclude_none=True))
    db.add(shop)
    await db.commit()
    await db.refresh(shop)
    return serialize_shop(shop)


@app.put("/shops/{shop_id}")
async def update_shop(shop_id: int, data: ShopUpsert, _: bool = Depends(require_shop_access), db: AsyncSession = Depends(get_db)):
    s = await db.get(CardShop, shop_id)
    if not s:
        raise HTTPException(404, "Shop not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(s, field, value)
    await db.commit()
    await db.refresh(s)
    return serialize_shop(s)


@app.post("/shops/{shop_id}/ai-update")
async def ai_update_shop(shop_id: int, req: AIUpdateRequest, _: bool = Depends(require_shop_access), db: AsyncSession = Depends(get_db)):
    """Free-text update box: Groq parses the note into structured fields,
    applies them, and keeps a timestamped log of what changed."""
    s = await db.get(CardShop, shop_id)
    if not s:
        raise HTTPException(404, "Shop not found")
    if not req.text or not req.text.strip():
        raise HTTPException(400, "Empty note")

    current = serialize_shop(s)
    import ai
    try:
        extracted = ai.extract_shop_fields(req.text.strip(), current)
    except Exception as e:
        raise HTTPException(502, f"AI parsing failed: {e}")

    fields = {k: v for k, v in extracted.get("fields", {}).items() if k in SHOP_EDITABLE_FIELDS}
    changed = {}
    for field, value in fields.items():
        old = getattr(s, field, None)
        if old != value:
            changed[field] = {"from": old, "to": value}
            setattr(s, field, value)

    # always append the raw note to the running notes log
    stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    note_line = f"[{stamp}] {req.text.strip()}"
    s.notes = (s.notes + "\n" + note_line) if s.notes else note_line

    # structured history of AI-applied changes
    log = json.loads(s.update_log) if s.update_log else []
    log.insert(0, {
        "at": datetime.utcnow().isoformat(),
        "note": req.text.strip(),
        "summary": extracted.get("summary", ""),
        "changed": changed,
    })
    s.update_log = json.dumps(log[:50])  # keep last 50

    await db.commit()
    await db.refresh(s)
    return {"shop": serialize_shop(s), "changed": changed, "summary": extracted.get("summary", "")}


# Bump this string whenever backend code changes so we can confirm what's live.
BUILD_VERSION = "2026-06-11-sheet-sync-all-tabs"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/version")
async def version():
    """Reports the running backend build + which shop features are present,
    so we can confirm a deploy actually landed."""
    return {
        "version": BUILD_VERSION,
        "features": {
            "shops": True,
            "ai_ask": True,
            "sheet_sync": True,          # /shops/sync-from-sheet exists in this build
            "sheet_sync_all_tabs": True,  # Final + Sheet1 + Whatnot
        },
    }


@app.get("/test-send")
async def test_send():
    """Attempt a real SMS + email and report the actual errors (for debugging)."""
    import smtplib, os
    from email.mime.text import MIMEText
    results = {}

    # Test Twilio SMS
    try:
        from twilio.rest import Client as TwilioClient
        c = TwilioClient(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
        c.messages.create(
            body="Card Finder test SMS ✓",
            messaging_service_sid=os.getenv("TWILIO_MESSAGING_SERVICE_SID"),
            to="+18187409787",
        )
        results["sms"] = "sent ok"
    except Exception as e:
        results["sms"] = f"FAILED: {type(e).__name__}: {str(e)[:200]}"

    # Test SendGrid HTTP API
    try:
        import httpx
        resp = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {os.getenv('SENDGRID_API_KEY')}", "Content-Type": "application/json"},
            json={
                "personalizations": [{"to": [{"email": "ahronriss@gmail.com"}]}],
                "from": {"email": os.getenv("SENDGRID_FROM_EMAIL"), "name": "Card Finder"},
                "subject": "Card Finder Test",
                "content": [{"type": "text/plain", "value": "Card Finder test email ✓"}],
            },
            timeout=15,
        )
        results["email"] = "sent ok" if resp.status_code < 400 else f"FAILED: {resp.status_code} {resp.text[:200]}"
    except Exception as e:
        results["email"] = f"FAILED: {type(e).__name__}: {str(e)[:200]}"

    return results


@app.get("/diag")
async def diag():
    """Diagnostic: which alert credentials are configured (presence only, not values)."""
    def has(k):
        v = os.getenv(k, "")
        return bool(v) and not v.startswith("your_")
    return {
        "twilio_sid": has("TWILIO_ACCOUNT_SID"),
        "twilio_token": has("TWILIO_AUTH_TOKEN"),
        "twilio_messaging_sid": has("TWILIO_MESSAGING_SERVICE_SID"),
        "gmail_address": has("GMAIL_ADDRESS"),
        "gmail_app_password": has("GMAIL_APP_PASSWORD"),
        "ebay_app_id": has("EBAY_APP_ID"),
        "ebay_cert_id": has("EBAY_CERT_ID"),
    }
