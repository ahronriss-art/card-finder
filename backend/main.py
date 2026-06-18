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
from database import init_db, get_db, User, SavedSearch, CardListing, CardShop, PopWatch, CallerNote, CallerDeal, SHOP_EDITABLE_FIELDS
from scrapers.ebay_scraper import search_cards, get_sold_history
from scrapers.psa_api import psa_cert_lookup, PSA_API_TOKEN
from agents.price_analyst import analyze_deal
from agents.misspelling_finder import generate_misspellings
import anthropic as _anthropic
_claude = _anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
from alerts import send_alert, send_pop_alert
from mock_data import MOCK_LISTINGS, MOCK_SOLD
from database import AuthSession
from auth import current_user, issue_session, norm_email, hash_password, verify_password

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
    extra_emails: Optional[str] = None
    extra_phones: Optional[str] = None


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
    brand: Optional[str] = None
    insert_type: Optional[str] = None
    card_number: Optional[str] = None
    year: Optional[str] = None
    exclude: Optional[str] = None
    source: str = "ebay"
    dry_spell_months: Optional[int] = None
    catch_misspellings: bool = False
    deal_threshold_pct: Optional[int] = None
    folder: Optional[str] = None
    check_interval_minutes: float = 30.0
    alert_method: str = "both"


class UpdateSearchRequest(BaseModel):
    query: str
    sport: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    numbered_to: Optional[int] = None
    brand: Optional[str] = None
    insert_type: Optional[str] = None
    card_number: Optional[str] = None
    year: Optional[str] = None
    exclude: Optional[str] = None
    source: str = "ebay"
    dry_spell_months: Optional[int] = None
    catch_misspellings: bool = False
    deal_threshold_pct: Optional[int] = None
    folder: Optional[str] = None
    check_interval_minutes: float = 30.0
    alert_method: str = "both"


# --- Routes ---

# --- Email + password login ---

class AuthRequest(BaseModel):
    email: str
    password: str


def _user_dict(user) -> dict:
    return {"id": user.id, "email": user.email, "phone": user.phone,
            "carrier": user.carrier, "alert_method": user.alert_method,
            "extra_emails": user.extra_emails, "extra_phones": user.extra_phones}


@app.post("/auth/signup")
async def signup(req: AuthRequest, db: AsyncSession = Depends(get_db)):
    email = norm_email(req.email)
    password = req.password or ""
    if not email or "@" not in email:
        raise HTTPException(400, "Enter a valid email address")
    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    r = await db.execute(select(User).where(func.lower(User.email) == email))
    user = r.scalar_one_or_none()
    if user and user.password_hash:
        raise HTTPException(409, "An account with this email already exists. Please log in.")

    if user:
        # Existing email (from the old flow) without a password — claim it, keeping alerts.
        user.password_hash = hash_password(password)
    else:
        user = User(email=email, password_hash=hash_password(password), alert_method="email")
        db.add(user)
    await db.commit()
    await db.refresh(user)

    token = await issue_session(db, user.id)
    return {"token": token, "user": _user_dict(user)}


@app.post("/auth/login")
async def login(req: AuthRequest, db: AsyncSession = Depends(get_db)):
    email = norm_email(req.email)
    password = req.password or ""
    if not email or not password:
        raise HTTPException(400, "Email and password required")

    r = await db.execute(select(User).where(func.lower(User.email) == email))
    user = r.scalar_one_or_none()
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")

    token = await issue_session(db, user.id)
    return {"token": token, "user": _user_dict(user)}


@app.get("/auth/me")
async def auth_me(user: User = Depends(current_user)):
    return _user_dict(user)


@app.post("/auth/logout")
async def auth_logout(authorization: str = Header(None), db: AsyncSession = Depends(get_db)):
    token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None
    if token:
        s = await db.get(AuthSession, token)
        if s:
            await db.delete(s)
            await db.commit()
    return {"ok": True}


@app.post("/users")
async def create_user(data: UserCreate, db: AsyncSession = Depends(get_db)):
    # Normalize so the SAME email always maps to the SAME account (and the same
    # alerts) regardless of caps/spaces — that's how logins share alerts.
    email = (data.email or "").strip().lower() or None
    phone = (data.phone or "").strip() or None
    if not email and not phone:
        raise HTTPException(400, "Email or phone required")

    # If a user with this email or phone already exists, reuse it (don't error)
    existing = None
    if email:
        r = await db.execute(select(User).where(func.lower(User.email) == email))
        existing = r.scalar_one_or_none()
    if not existing and phone:
        r = await db.execute(select(User).where(User.phone == phone))
        existing = r.scalar_one_or_none()

    if existing:
        if email: existing.email = email
        if phone: existing.phone = phone
        if data.carrier is not None: existing.carrier = data.carrier
        existing.alert_method = data.alert_method
        await db.commit()
        await db.refresh(existing)
        user = existing
    else:
        user = User(email=email, phone=phone, carrier=data.carrier, alert_method=data.alert_method)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return {"id": user.id, "email": user.email, "phone": user.phone, "carrier": user.carrier, "alert_method": user.alert_method}


@app.put("/users/{user_id}")
async def update_user(user_id: int, data: UserCreate, db: AsyncSession = Depends(get_db),
                      me: User = Depends(current_user)):
    if user_id != me.id:
        raise HTTPException(403, "Not your account")
    user = me
    if data.email: user.email = data.email.strip().lower()
    if data.phone: user.phone = data.phone.strip()
    if data.carrier is not None: user.carrier = data.carrier
    if data.extra_emails is not None: user.extra_emails = _blank(data.extra_emails)
    if data.extra_phones is not None: user.extra_phones = _blank(data.extra_phones)
    user.alert_method = data.alert_method
    await db.commit()
    return _user_dict(user)


@app.post("/search")
async def search(req: SearchRequest):
    """Search for cards and return listings with price analysis."""
    if USE_MOCK:
        enriched = []
        for listing in MOCK_LISTINGS:
            analysis = analyze_deal(listing, MOCK_SOLD)
            enriched.append({**listing, "analysis": analysis})
        return {"listings": enriched, "sold_history": MOCK_SOLD[:10], "total": len(enriched), "mock": True}

    from scrapers import auction_scraper

    query = req.query
    if req.sport:
        query = f"{req.sport} {query}"

    listings, sold, goldin = await asyncio.gather(
        search_cards(query, req.min_price, req.max_price),
        get_sold_history(query, limit=20),
        auction_scraper.goldin_sales(query),
    )

    # Grade-clean market value (Goldin completed sales preferred), then score
    # each listing against it — fast, consistent, no per-listing LLM call.
    target_grade = auction_scraper.extract_grade(query)
    goldin_sold = [s for s in goldin.get("sales", []) if s.get("status") == "sold"]
    market, _trend = _market_value(goldin_sold, sold, target_grade)

    enriched = [{**l, "analysis": _score_listing(l, market, target_grade)} for l in listings]

    return {
        "listings": enriched,
        "sold_history": sold[:10],
        "total": len(enriched),
        "market": market,
    }


@app.get("/sold-history")
async def sold_history(query: str, sport: Optional[str] = None):
    """Get recently sold cards to show market value."""
    q = f"{sport} {query}" if sport else query
    sold = await get_sold_history(q, limit=30)
    prices = [s["sold_price"] for s in sold if s.get("sold_price")]
    avg = round(sum(prices) / len(prices), 2) if prices else None
    return {"sold": sold, "avg_price": avg, "count": len(sold)}


def _blank(v):
    """Normalize empty/whitespace strings to None so blank filters aren't stored."""
    return v.strip() if isinstance(v, str) and v.strip() else None


@app.post("/saved-searches")
async def save_search(req: SaveSearchRequest, db: AsyncSession = Depends(get_db),
                      me: User = Depends(current_user)):
    search = SavedSearch(
        user_id=me.id,
        query=req.query,
        sport=req.sport,
        min_price=req.min_price,
        max_price=req.max_price,
        numbered_to=req.numbered_to,
        brand=_blank(req.brand),
        insert_type=_blank(req.insert_type),
        card_number=_blank(req.card_number),
        year=_blank(req.year),
        exclude=_blank(req.exclude),
        source=req.source if req.source in ("ebay", "auction") else "ebay",
        dry_spell_months=req.dry_spell_months,
        catch_misspellings=req.catch_misspellings,
        deal_threshold_pct=req.deal_threshold_pct,
        folder=_blank(req.folder),
        check_interval_minutes=req.check_interval_minutes,
        alert_method=req.alert_method,
    )
    db.add(search)
    await db.commit()
    await db.refresh(search)
    return {"id": search.id, "query": search.query}


@app.get("/saved-searches/{user_id}")
async def get_saved_searches(user_id: int, db: AsyncSession = Depends(get_db),
                             me: User = Depends(current_user)):
    if user_id != me.id:
        raise HTTPException(403, "Not your account")
    result = await db.execute(
        select(SavedSearch).where(SavedSearch.user_id == me.id, SavedSearch.active == True)
    )
    searches = result.scalars().all()
    return [{"id": s.id, "query": s.query, "sport": s.sport, "min_price": s.min_price, "max_price": s.max_price, "numbered_to": s.numbered_to, "brand": s.brand, "insert_type": s.insert_type, "card_number": s.card_number, "year": s.year, "exclude": s.exclude, "source": s.source or "ebay", "dry_spell_months": s.dry_spell_months, "catch_misspellings": bool(s.catch_misspellings), "deal_threshold_pct": s.deal_threshold_pct, "folder": s.folder, "check_interval_minutes": s.check_interval_minutes, "alert_method": s.alert_method} for s in searches]


@app.put("/saved-searches/{search_id}")
async def update_search(search_id: int, req: UpdateSearchRequest, db: AsyncSession = Depends(get_db),
                        me: User = Depends(current_user)):
    result = await db.execute(select(SavedSearch).where(SavedSearch.id == search_id))
    search = result.scalar_one_or_none()
    if not search:
        raise HTTPException(404, "Search not found")
    if search.user_id != me.id:
        raise HTTPException(403, "Not your alert")
    # Full overwrite: the edit form always sends the complete state, so a None
    # here means the user cleared that filter (e.g. removed the price range).
    search.query = req.query
    search.sport = req.sport
    search.min_price = req.min_price
    search.max_price = req.max_price
    search.numbered_to = req.numbered_to
    search.brand = _blank(req.brand)
    search.insert_type = _blank(req.insert_type)
    search.card_number = _blank(req.card_number)
    search.year = _blank(req.year)
    search.exclude = _blank(req.exclude)
    search.source = req.source if req.source in ("ebay", "auction") else "ebay"
    search.dry_spell_months = req.dry_spell_months
    search.catch_misspellings = req.catch_misspellings
    search.deal_threshold_pct = req.deal_threshold_pct
    search.folder = _blank(req.folder)
    search.check_interval_minutes = req.check_interval_minutes
    search.alert_method = req.alert_method
    # Re-baseline on next run so edits take effect cleanly without alert spam.
    search.last_checked_at = None
    await db.commit()
    return {"updated": True}


class FolderUpdate(BaseModel):
    folder: Optional[str] = None


@app.put("/saved-searches/{search_id}/folder")
async def set_search_folder(search_id: int, req: FolderUpdate, db: AsyncSession = Depends(get_db),
                            me: User = Depends(current_user)):
    """Set just the folder on an existing alert (no re-baseline), for organizing
    alerts that already exist."""
    result = await db.execute(select(SavedSearch).where(SavedSearch.id == search_id))
    search = result.scalar_one_or_none()
    if not search:
        raise HTTPException(404, "Search not found")
    if search.user_id != me.id:
        raise HTTPException(403, "Not your alert")
    search.folder = _blank(req.folder)
    await db.commit()
    return {"updated": True, "folder": search.folder}


@app.delete("/saved-searches/{search_id}")
async def delete_search(search_id: int, db: AsyncSession = Depends(get_db),
                        me: User = Depends(current_user)):
    result = await db.execute(select(SavedSearch).where(SavedSearch.id == search_id))
    search = result.scalar_one_or_none()
    if not search:
        raise HTTPException(404, "Search not found")
    if search.user_id != me.id:
        raise HTTPException(403, "Not your alert")
    search.active = False
    await db.commit()
    return {"deleted": True}


# --- Pop Watch: track a PSA cert's population and alert when it increases ---

class PopWatchRequest(BaseModel):
    user_id: int
    cert_number: str
    auction_url: Optional[str] = None
    auction_ends_at: Optional[str] = None   # ISO date/datetime; watch stops after
    check_interval_minutes: float = 60.0
    alert_method: str = "both"


def _watch_dict(w: PopWatch):
    return {
        "id": w.id, "cert_number": w.cert_number, "label": w.label, "grade": w.grade,
        "population": w.last_population, "population_higher": w.last_population_higher,
        "auction_url": w.auction_url,
        "auction_ends_at": w.auction_ends_at.isoformat() if w.auction_ends_at else None,
        "check_interval_minutes": w.check_interval_minutes, "alert_method": w.alert_method,
        "last_checked_at": w.last_checked_at.isoformat() if w.last_checked_at else None,
        "cert_url": f"https://www.psacard.com/cert/{w.cert_number}",
    }


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00").split("+")[0])
    except Exception:
        return None


@app.get("/pop-lookup")
async def pop_lookup(cert: str):
    """Return the live PSA population for a cert number (pop at grade, # higher,
    total). Used by the Pop Reports search when the user enters a cert number."""
    if not PSA_API_TOKEN:
        raise HTTPException(503, "PSA pop lookup isn't configured yet (missing PSA_API_TOKEN).")
    info = await psa_cert_lookup(cert)
    if not info:
        raise HTTPException(502, "Couldn't reach the PSA API. Try again shortly.")
    if not info.get("valid"):
        raise HTTPException(404, "PSA couldn't find that cert number. Double-check it.")
    return info


@app.post("/pop-watches")
async def create_pop_watch(req: PopWatchRequest, db: AsyncSession = Depends(get_db),
                           me: User = Depends(current_user)):
    if not PSA_API_TOKEN:
        raise HTTPException(503, "PSA pop tracking isn't configured yet (missing PSA_API_TOKEN).")
    info = await psa_cert_lookup(req.cert_number)
    if not info:
        raise HTTPException(502, "Couldn't reach the PSA API. Try again shortly.")
    if not info.get("valid"):
        raise HTTPException(404, "PSA couldn't find that cert number. Double-check it.")

    watch = PopWatch(
        user_id=me.id,
        cert_number=info["cert"],
        label=info["label"],
        grade=info.get("grade"),
        last_population=info.get("population"),
        last_population_higher=info.get("population_higher"),
        auction_url=_blank(req.auction_url),
        auction_ends_at=_parse_dt(req.auction_ends_at),
        check_interval_minutes=req.check_interval_minutes,
        alert_method=req.alert_method,
        last_checked_at=datetime.utcnow(),
    )
    db.add(watch)
    await db.commit()
    await db.refresh(watch)
    return _watch_dict(watch)


@app.get("/pop-watches/{user_id}")
async def list_pop_watches(user_id: int, db: AsyncSession = Depends(get_db),
                           me: User = Depends(current_user)):
    if user_id != me.id:
        raise HTTPException(403, "Not your account")
    result = await db.execute(
        select(PopWatch).where(PopWatch.user_id == me.id, PopWatch.active == True).order_by(PopWatch.id.desc())
    )
    return [_watch_dict(w) for w in result.scalars().all()]


@app.delete("/pop-watches/{watch_id}")
async def delete_pop_watch(watch_id: int, db: AsyncSession = Depends(get_db),
                           me: User = Depends(current_user)):
    result = await db.execute(select(PopWatch).where(PopWatch.id == watch_id))
    watch = result.scalar_one_or_none()
    if not watch:
        raise HTTPException(404, "Pop watch not found")
    if watch.user_id != me.id:
        raise HTTPException(403, "Not your pop watch")
    watch.active = False
    await db.commit()
    return {"deleted": True}


async def _check_pop_watches(db: AsyncSession) -> int:
    """Poll each active pop watch's PSA cert; alert when population increases.
    Returns the number of pop-increase alerts sent."""
    if not PSA_API_TOKEN:
        return 0
    result = await db.execute(select(PopWatch).where(PopWatch.active == True))
    watches = result.scalars().all()
    sent = 0
    now = datetime.utcnow()

    for w in watches:
        # Stop watching once the auction is over.
        if w.auction_ends_at and now > w.auction_ends_at:
            w.active = False
            continue
        if w.last_checked_at:
            elapsed = (now - w.last_checked_at).total_seconds() / 60
            if elapsed < (w.check_interval_minutes or 60):
                continue

        info = await psa_cert_lookup(w.cert_number)
        w.last_checked_at = now
        if not info or not info.get("valid"):
            continue

        new_pop = info.get("population")
        old_pop = w.last_population
        if new_pop is not None and old_pop is not None and new_pop > old_pop:
            user_res = await db.execute(select(User).where(User.id == w.user_id))
            user = user_res.scalar_one_or_none()
            if user:
                send_pop_alert(user, w.label or info["label"], old_pop, new_pop,
                               info["url"], grade=w.grade or info.get("grade") or "", method=w.alert_method)
                sent += 1
        if new_pop is not None:
            w.last_population = new_pop
        if info.get("population_higher") is not None:
            w.last_population_higher = info.get("population_higher")

    await db.commit()
    return sent


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

    # Auto-stretch: when there are many alerts, raise the effective interval so
    # the day's eBay calls stay under budget (no early exhaustion).
    from alert_filters import min_interval_for
    floor_interval = min_interval_for(len(searches))

    checked = 0
    alerts_sent = 0

    for search in searches:
        # Respect each search's interval, but never check more often than the
        # budget-safe floor.
        if search.last_checked_at:
            elapsed = (datetime.utcnow() - search.last_checked_at).total_seconds() / 60
            if elapsed < max(search.check_interval_minutes or 30, floor_interval):
                continue

        from alert_filters import build_query, gather_alert_listings, passes_deal_threshold
        # First check ever? Seed the baseline silently (don't alert on existing listings)
        is_first_check = search.last_checked_at is None
        try:
            src, listings = await gather_alert_listings(search)
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
                    CardListing.source == src,
                )
            )
            if existing.scalar_one_or_none():
                continue

            db.add(CardListing(
                source=src, external_id=ext_id,
                title=listing.get("title"), price=listing.get("price"),
                listing_url=listing.get("listing_url"), image_url=listing.get("image_url"),
                seller_name=listing.get("seller_name"), condition=listing.get("condition"),
            ))

            # Only alert on genuinely new finds, not the initial baseline
            if not is_first_check:
                if src == "goldin":
                    analysis = {"verdict": "auction", "avg_sold_price": 0,
                                "last_sold_price": listing.get("last_sold_price"),
                                "last_sold_at": listing.get("last_sold_at")}
                else:
                    sold = await get_sold_history(build_query(search), limit=10)
                    analysis = analyze_deal(listing, sold)
                if not passes_deal_threshold(search, src, analysis):
                    continue  # not enough of a discount to alert on
                send_alert(user, listing, analysis, method=search.alert_method)
                alerts_sent += 1

    await db.commit()

    # PSA pop watches: alert when a watched cert's population increases
    pop_alerts = await _check_pop_watches(db)

    # One-time: notify when Twilio toll-free SMS verification gets approved
    await _check_tollfree_approval(db)

    # Periodically pull the latest from the Google Sheet (throttled to ~15 min)
    synced = await _maybe_sync_sheet(db)

    return {"checked": checked, "alerts_sent": alerts_sent, "pop_alerts": pop_alerts, "sheet_synced": synced}


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

# Temporary /admin/* test+debug endpoints auto-disable after the scheduled
# re-test (00:30 PT). The dead code is deleted in the next session.
ADMIN_TEMP_EXPIRY = datetime(2026, 6, 19, 9, 0, 0)  # 09:00 UTC = ~02:00 PT


def require_shop_access(x_shops_password: Optional[str] = Header(None)):
    """Single shared-password gate for all shop routes."""
    if not x_shops_password or x_shops_password != SHOPS_PASSWORD:
        raise HTTPException(401, "Invalid or missing access password")
    return True


# --- Caller Notes (shared, gated by the Shops password) ---

class CallerNoteRequest(BaseModel):
    caller_name: str
    note: str
    caller_phone: Optional[str] = None
    instagram: Optional[str] = None
    facebook: Optional[str] = None
    email: Optional[str] = None


def _caller_note_dict(n: CallerNote) -> dict:
    return {"id": n.id, "caller_name": n.caller_name, "caller_phone": n.caller_phone,
            "instagram": n.instagram, "facebook": n.facebook, "email": n.email,
            "note": n.note, "created_at": n.created_at.isoformat() if n.created_at else None}


@app.post("/caller-notes")
async def add_caller_note(req: CallerNoteRequest, db: AsyncSession = Depends(get_db),
                          _: bool = Depends(require_shop_access)):
    name = (req.caller_name or "").strip()
    note = (req.note or "").strip()
    if not name or not note:
        raise HTTPException(400, "Caller name and note are required")
    n = CallerNote(caller_name=name, caller_phone=_blank(req.caller_phone),
                   instagram=_blank(req.instagram), facebook=_blank(req.facebook),
                   email=_blank(req.email), note=note)
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return _caller_note_dict(n)


@app.get("/caller-notes")
async def list_caller_notes(db: AsyncSession = Depends(get_db),
                            _: bool = Depends(require_shop_access)):
    res = await db.execute(select(CallerNote).order_by(CallerNote.created_at.desc()))
    return [_caller_note_dict(n) for n in res.scalars().all()]


class CallerNoteUpdate(BaseModel):
    note: Optional[str] = None
    caller_phone: Optional[str] = None


@app.put("/caller-notes/{note_id}")
async def update_caller_note(note_id: int, req: CallerNoteUpdate, db: AsyncSession = Depends(get_db),
                             _: bool = Depends(require_shop_access)):
    n = await db.get(CallerNote, note_id)
    if not n:
        raise HTTPException(404, "Note not found")
    if req.note is not None:
        text = req.note.strip()
        if not text:
            raise HTTPException(400, "Note can't be empty")
        n.note = text
    if req.caller_phone is not None:
        n.caller_phone = _blank(req.caller_phone)
    await db.commit()
    await db.refresh(n)
    return _caller_note_dict(n)


@app.delete("/caller-notes/{note_id}")
async def delete_caller_note(note_id: int, db: AsyncSession = Depends(get_db),
                             _: bool = Depends(require_shop_access)):
    n = await db.get(CallerNote, note_id)
    if not n:
        raise HTTPException(404, "Note not found")
    await db.delete(n)
    await db.commit()
    return {"deleted": True}


# --- Caller Deals (closed deals per caller) ---

class CallerDealRequest(BaseModel):
    caller_name: str
    description: str
    amount: Optional[float] = None


def _caller_deal_dict(d: CallerDeal) -> dict:
    return {"id": d.id, "caller_name": d.caller_name, "description": d.description,
            "amount": d.amount, "created_at": d.created_at.isoformat() if d.created_at else None}


@app.post("/caller-deals")
async def add_caller_deal(req: CallerDealRequest, db: AsyncSession = Depends(get_db),
                          _: bool = Depends(require_shop_access)):
    name = (req.caller_name or "").strip()
    desc = (req.description or "").strip()
    if not name or not desc:
        raise HTTPException(400, "Caller name and a deal description are required")
    d = CallerDeal(caller_name=name, description=desc, amount=req.amount)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return _caller_deal_dict(d)


@app.get("/caller-deals")
async def list_caller_deals(db: AsyncSession = Depends(get_db),
                            _: bool = Depends(require_shop_access)):
    res = await db.execute(select(CallerDeal).order_by(CallerDeal.created_at.desc()))
    return [_caller_deal_dict(d) for d in res.scalars().all()]


@app.delete("/caller-deals/{deal_id}")
async def delete_caller_deal(deal_id: int, db: AsyncSession = Depends(get_db),
                             _: bool = Depends(require_shop_access)):
    d = await db.get(CallerDeal, deal_id)
    if not d:
        raise HTTPException(404, "Deal not found")
    await db.delete(d)
    await db.commit()
    return {"deleted": True}


def _require_admin_temp(key: str):
    if not SHOPS_PASSWORD or key != SHOPS_PASSWORD:
        raise HTTPException(401, "Invalid admin key")
    if datetime.utcnow() > ADMIN_TEMP_EXPIRY:
        raise HTTPException(410, "Temporary admin endpoint expired")


class _AlertUser:
    def __init__(self, email):
        self.email = email; self.phone = None; self.carrier = None
        self.alert_method = "email"; self.extra_emails = None; self.extra_phones = None


class _TmpSearch:
    def __init__(self, query):
        self.query = query; self.numbered_to = None


class AdminEmail(BaseModel):
    to: str
    subject: str
    body: str


@app.post("/admin/send-email")
async def admin_send_email(req: AdminEmail, key: str = ""):
    """Send a plain email via the app's mailer (Brevo). Password-gated; used by
    the scheduled re-test to email results."""
    _require_admin_temp(key)
    from alerts import _deliver_email
    ok = _deliver_email(req.to, req.subject, text=req.body)
    return {"sent": bool(ok)}


@app.post("/admin/ebay-debug")
async def admin_ebay_debug(q: str, key: str = ""):
    """Surface eBay's raw search response (errors/warnings/total) for debugging."""
    _require_admin_temp(key)
    from scrapers.ebay_scraper import _get_token, _do_search, usage_status
    out = {"app_id_set": bool(os.getenv("EBAY_APP_ID")), "cert_id_set": bool(os.getenv("EBAY_CERT_ID")),
           "usage": usage_status()}
    try:
        token = await _get_token()
        out["got_token"] = bool(token)
    except Exception as e:
        out["token_error"] = repr(e)
        return out
    try:
        data = await _do_search(token, q, None, None, 5)
        out.update({"total": data.get("total"), "count": len(data.get("itemSummaries") or []),
                    "errors": data.get("errors"), "warnings": data.get("warnings"),
                    "keys": list(data.keys())})
    except Exception as e:
        out["search_error"] = repr(e)
    return out


@app.post("/admin/test-search-alert")
async def admin_test_search_alert(query: str, email: str, key: str = "",
                                  db: AsyncSession = Depends(get_db)):
    """One-off: run a real eBay search for `query`, apply the SAME strict alert
    filter, and email the top matching listing to `email`. Protected by the Shops
    password (?key=). Lets us test exactly what an alert would catch + deliver."""
    _require_admin_temp(key)
    from alert_filters import passes_filters
    listings = await search_cards(query, None, None, limit=15)
    tmp = _TmpSearch(query)
    matches = [l for l in listings if passes_filters(tmp, l)]
    if not matches:
        return {"searched": query, "raw_results": len(listings), "matches": 0,
                "sent": False, "note": "No listing matched every word in your query."}
    top = matches[0]
    sold = await get_sold_history(query, limit=10)
    analysis = analyze_deal(top, sold)
    send_alert(_AlertUser(email), top, analysis, method="email")
    return {"searched": query, "raw_results": len(listings), "matches": len(matches),
            "sent": True, "to": email, "alerted_title": top.get("title"),
            "price": top.get("price"), "matched_titles": [m.get("title") for m in matches[:5]]}


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


# --- Studio: AI image/flyer generation (password-gated; calls a paid API) ---

class StudioRequest(BaseModel):
    prompt: str
    size: str = "square"        # square | portrait | landscape
    quality: str = "medium"     # low | medium | high
    enhance: bool = True


_STUDIO_SIZES = {"square": (1024, 1024), "portrait": (1024, 1536), "landscape": (1536, 1024)}
_GEMINI_MODEL = {"name": None}  # discovered image model, cached across requests


@app.post("/studio/generate")
async def studio_generate(req: StudioRequest, _: bool = Depends(require_shop_access)):
    """Generate text-free flyer/background art (the user overlays real text in
    the browser). Tries each configured engine in order and falls through on
    failure, so a quota/outage on one moves to the next:
      OpenAI (paid) > Cloudflare Workers AI (free) > Hugging Face (free) >
      Gemini (needs billing) > Pollinations (no key, often rate-limited)."""
    import httpx, base64, random, urllib.parse, asyncio
    import ai

    prompt = (req.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "Describe the image you want to make.")
    used = ai.enhance_image_prompt(prompt) if req.enhance else prompt
    w, h = _STUDIO_SIZES.get(req.size, (1024, 1024))
    quality = req.quality if req.quality in ("low", "medium", "high") else "medium"

    openai_key = os.getenv("OPENAI_API_KEY", "")
    cf_acct, cf_token = os.getenv("CLOUDFLARE_ACCOUNT_ID", ""), os.getenv("CLOUDFLARE_API_TOKEN", "")
    hf = os.getenv("HF_API_TOKEN", "")
    gem = os.getenv("GEMINI_API_KEY", "")

    async def via_openai(c):
        r = await c.post("https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
            json={"model": "gpt-image-1", "prompt": used, "n": 1, "size": f"{w}x{h}", "quality": quality})
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code} {r.text[:150]}")
        return "data:image/png;base64," + r.json()["data"][0]["b64_json"]

    async def via_cloudflare(c):
        url = f"https://api.cloudflare.com/client/v4/accounts/{cf_acct}/ai/run/@cf/black-forest-labs/flux-1-schnell"
        r = await c.post(url, headers={"Authorization": f"Bearer {cf_token}"}, json={"prompt": used, "steps": 6})
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code} {r.text[:150]}")
        img = (r.json().get("result") or {}).get("image")
        if not img:
            raise RuntimeError("no image returned")
        return "data:image/jpeg;base64," + img

    async def via_hf(c):
        api = "https://api-inference.huggingface.co/models/black-forest-labs/FLUX.1-schnell"
        r = None
        for attempt in range(2):
            r = await c.post(api, headers={"Authorization": f"Bearer {hf}"},
                             json={"inputs": used, "parameters": {"width": w, "height": h}})
            if r.status_code == 503 and attempt == 0:
                await asyncio.sleep(8); continue
            break
        if r.status_code != 200 or not r.content:
            raise RuntimeError(f"{r.status_code} {r.text[:150]}")
        ct = (r.headers.get("content-type") or "image/png").split(";")[0]
        return f"data:{ct};base64," + base64.b64encode(r.content).decode()

    async def via_gemini(c):
        base = "https://generativelanguage.googleapis.com/v1beta"
        model = _GEMINI_MODEL["name"]
        if not model:
            lr = await c.get(f"{base}/models?key={gem}&pageSize=200")
            if lr.status_code == 200:
                for m in lr.json().get("models", []):
                    nm = m.get("name", "").split("/")[-1]
                    if ("generateContent" in m.get("supportedGenerationMethods", [])
                            and "image" in nm.lower() and "imagen" not in nm.lower()):
                        model = nm; break
            model = model or "gemini-2.5-flash-image-preview"
            _GEMINI_MODEL["name"] = model
        body = {"contents": [{"parts": [{"text": used}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
        r = await c.post(f"{base}/models/{model}:generateContent?key={gem}", json=body)
        if r.status_code != 200:
            _GEMINI_MODEL["name"] = None
            raise RuntimeError(f"{r.status_code} {r.text[:150]}")
        parts = (((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        inline = next((p["inlineData"] for p in parts if p.get("inlineData")), None)
        if not inline:
            raise RuntimeError("no image returned")
        return f"data:{inline.get('mimeType', 'image/png')};base64,{inline['data']}"

    async def via_pollinations(c):
        seed = random.randint(1, 1_000_000)
        url = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(used)}"
               f"?width={w}&height={h}&nologo=true&model=flux&seed={seed}")
        r = await c.get(url)
        if r.status_code != 200 or "image" not in (r.headers.get("content-type") or ""):
            raise RuntimeError(f"{r.status_code} (datacenter rate-limited)")
        ct = (r.headers.get("content-type") or "image/jpeg").split(";")[0]
        return f"data:{ct};base64," + base64.b64encode(r.content).decode()

    chain = []
    if openai_key: chain.append(("openai", via_openai))
    if cf_acct and cf_token: chain.append(("cloudflare", via_cloudflare))
    if hf: chain.append(("huggingface", via_hf))
    if gem: chain.append(("gemini", via_gemini))
    chain.append(("pollinations", via_pollinations))

    errors = []
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as c:
        for name, fn in chain:
            try:
                return {"image": await fn(c), "prompt_used": used, "engine": name}
            except Exception as e:
                errors.append(f"{name}: {str(e)[:140]}")
    raise HTTPException(502, "All image engines failed. " + " | ".join(errors[-3:])
                        + " — add free Cloudflare Workers AI keys (CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN), or enable billing on Gemini/OpenAI.")


# --- Auctions: card sales Q&A (password-gated, reuses the Shops password) ---

def _is_reprint(title: str) -> bool:
    t = (title or "").lower()
    return any(w in t for w in ("reprint", "reproduction", "facsimile", "commemorative", "porcelain", "metal card"))


def _deal_score(pct: float) -> str:
    if pct <= -20: return "great"
    if pct <= -5:  return "good"
    if pct <= 15:  return "fair"
    return "high"


def _keep_comp(title, target_grade):
    """Keep a comp only if it's not a reprint and (when a grade is targeted)
    its grade matches — so a PSA 5 valuation isn't polluted by PSA 9s."""
    from scrapers import auction_scraper
    if _is_reprint(title):
        return False
    if target_grade and auction_scraper.extract_grade(title or "") != target_grade:
        return False
    return True


def _market_value(goldin_sold, ebay_sold, target_grade):
    """Grade-clean market value (median) + dated price-trend series. Prefers
    real Goldin completed sales (eBay 'sold' is really asking prices, which
    inflate value); falls back to eBay when Goldin is thin. Returns (market, trend)."""
    from statistics import median
    from datetime import datetime, timedelta
    g = [c for c in goldin_sold if c.get("sold_price") and _keep_comp(c.get("title"), target_grade)]
    e = [c for c in ebay_sold if c.get("sold_price") and _keep_comp(c.get("title"), target_grade)]
    comps = g if len(g) >= 2 else (g + e)
    if not comps:
        return None, []

    # Drop gross low-outlier mismatches: the same card in the same grade shouldn't
    # span ~7x, so anything under 15% of the top comp is almost certainly a
    # different/cheaper item the keyword search dragged in (it pollutes the median).
    hi = max(c["sold_price"] for c in comps)
    floor = hi * 0.15
    comps = [c for c in comps if c["sold_price"] >= floor]
    g = [c for c in g if c["sold_price"] >= floor]

    # Full dated history (Goldin sold has real dates) drives the trend chart.
    dated = sorted([c for c in g if c.get("sold_at")], key=lambda x: x["sold_at"])
    trend = [{"date": c["sold_at"], "price": c["sold_price"]} for c in dated]
    trend_pct = None
    dp = [c["sold_price"] for c in dated]
    if len(dp) >= 4:
        h = len(dp) // 2
        old, rec = median(dp[:h]), median(dp[h:])
        if old:
            trend_pct = round((rec - old) / old * 100)

    # Headline market value reflects RECENT sales (last ~18 months), not all-time,
    # so a card that's appreciated isn't valued off stale comps. Fall back to the
    # most recent 5 dated sales, then to all comps when there are no dates.
    value_comps = comps
    if len(dated) >= 3:
        try:
            cutoff = datetime.utcnow() - timedelta(days=548)
            recent = [c for c in dated if datetime.strptime(c["sold_at"][:10], "%Y-%m-%d") >= cutoff]
        except Exception:
            recent = []
        value_comps = recent if len(recent) >= 3 else dated[-5:]

    prices = sorted(c["sold_price"] for c in value_comps)
    last = dated[-1] if dated else None
    market = {
        "grade": target_grade or None,
        "median": round(median(prices)),
        "low": round(min(prices)),
        "high": round(max(prices)),
        "count": len(prices),
        "trend_pct": trend_pct,
        "last_sold": round(last["sold_price"]) if last else None,
        "last_sold_at": last["sold_at"] if last else None,
    }
    return market, trend


def _market_and_deals(goldin_sold, ebay_sold, active, target_grade):
    """Market value + trend + deal-scored current listings (for the Auctions tab)."""
    from scrapers import auction_scraper
    market, trend = _market_value(goldin_sold, ebay_sold, target_grade)
    deals = []
    if market:
        mv = market["median"]
        for l in active:
            p = l.get("price")
            if not p or not _keep_comp(l.get("title"), target_grade):
                continue
            pct = round((p - mv) / mv * 100)
            # Skip too-good-to-be-true lowballs (almost always mislabeled/fake/
            # damaged) and clearly-overpriced items — keep only believable deals.
            if pct < -65 or pct > 15:
                continue
            deals.append({
                "title": l.get("title"), "price": p, "pct": pct, "score": _deal_score(pct),
                "grade": auction_scraper.extract_grade(l.get("title") or ""),
                "listing_url": l.get("listing_url"), "image_url": l.get("image_url"),
            })
        deals.sort(key=lambda d: d["pct"])  # best deals first
        deals = deals[:8]
    return market, trend, deals


def _score_listing(listing, market, target_grade):
    """Deal verdict for one search listing vs the card's market value. Fast
    (no LLM), grade-aware, with the same scam guard as the Auctions deals."""
    from scrapers import auction_scraper
    if not market:
        return {"verdict": "unknown", "summary": "No recent sold comps to compare against."}
    price = listing.get("price") or 0
    g = auction_scraper.extract_grade(listing.get("title") or "")
    if target_grade and g and g != target_grade:
        return {"verdict": "unknown", "summary": f"This is {g} — market shown is for {target_grade}."}
    if not price:
        return {"verdict": "unknown", "summary": ""}
    mv = market["median"]
    pct = round((price - mv) / mv * 100)
    base = {"avg_sold_price": mv, "pct_vs_market": pct, "sample_size": market["count"],
            "most_recent_sold": market.get("last_sold"), "most_recent_date": market.get("last_sold_at")}
    if pct < -65:
        return {**base, "verdict": "suspicious",
                "summary": "Priced far below market — likely a reprint, error, or different card. Verify before buying."}
    if pct <= -20:
        return {**base, "verdict": "great_deal", "summary": f"{abs(pct)}% below the ${mv:,} market median — an excellent deal."}
    if pct <= -5:
        return {**base, "verdict": "good_deal", "summary": f"{abs(pct)}% under the ${mv:,} market median. Solid buy."}
    if pct <= 15:
        return {**base, "verdict": "fair", "summary": f"Right around the ${mv:,} market median."}
    return {**base, "verdict": "overpriced", "summary": f"{pct}% above the ${mv:,} market median — negotiate or wait."}


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
        "sold_at": r.get("sold_at") or "",
        "grade": auction_scraper.extract_grade(r.get("title") or ""),
        "listing_url": r.get("listing_url"), "image_url": r.get("image_url"),
    } for r in ebay_rows if r.get("sold_price")]

    sales = (psa["sales"] + goldin["sales"] + ebay_sales)[:30]
    sources = [
        psa and {"name": psa["name"], "status": psa["status"], "count": len(psa["sales"])},
        goldin and {"name": goldin["name"], "status": goldin["status"], "count": len(goldin["sales"]),
                    "sold": goldin.get("sold_count"), "live": goldin.get("live_count")},
        {"name": "eBay", "status": "ok" if ebay_sales else "no data", "count": len(ebay_sales)},
    ]

    # --- Deal Score + trend ---
    target_grade = auction_scraper.extract_grade(card_query)
    goldin_sold = [s for s in goldin["sales"] if s.get("status") == "sold"]
    try:
        active = await search_cards(card_query, limit=12)  # current listings to score
    except Exception:
        active = []
    market, trend, deals = _market_and_deals(goldin_sold, ebay_sales, active, target_grade)

    answer = ai.answer_card_question(question, sales, sources)
    return {"answer": answer, "card_query": card_query, "sales": sales, "sources": sources,
            "market": market, "trend": trend, "deals": deals}


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


@app.get("/test-email")
async def test_email(to: str):
    """Send a real sample alert EMAIL to any address — to confirm that anyone who
    enters their email will actually receive alerts. Uses the live email path."""
    from alerts import send_email_alert
    if "@" not in to:
        raise HTTPException(400, "Provide a valid ?to= email address.")
    send_email_alert(
        to_email=to,
        card_title="2023 Topps Chrome Victor Wembanyama RC #1 PSA 10 (sample alert)",
        price=123.45,
        listing_url="https://www.ebay.com/sch/i.html?_nkw=wembanyama+psa+10",
        verdict="good_deal",
        avg_price=150.0,
        note="This is a sample Card Finder alert confirming email delivery works.",
    )
    return {"sent": True, "to": to, "from": os.getenv("SENDGRID_FROM_EMAIL", "(unset)")}


class TestAlertRequest(BaseModel):
    user_id: int


@app.post("/test-alert")
async def test_alert(req: TestAlertRequest, db: AsyncSession = Depends(get_db),
                     me: User = Depends(current_user)):
    """Send a real sample alert to a user via their configured method(s), so they
    can confirm alerts actually reach them. Uses the same send path as live alerts."""
    if req.user_id != me.id:
        raise HTTPException(403, "Not your account")
    user = me
    if not (user.email or user.phone):
        raise HTTPException(400, "No email or phone on file — add your contact info first.")

    sample = {
        "title": "TEST — 2023 Topps Chrome Victor Wembanyama RC #1 PSA 10",
        "price": 123.45,
        "listing_url": "https://www.ebay.com/sch/i.html?_nkw=wembanyama+psa+10",
    }
    analysis = {"verdict": "good_deal", "avg_sold_price": 150.0}
    send_alert(user, sample, analysis, method=user.alert_method)

    sent_to = []
    if user.alert_method in ("email", "both") and user.email:
        sent_to.append(f"email ({user.email})")
    if user.alert_method in ("sms", "both") and user.phone:
        sent_to.append(f"SMS ({user.phone})")
    return {"sent": True, "via": sent_to or ["(no matching contact for your alert method)"]}


@app.get("/alert-status")
async def alert_status(db: AsyncSession = Depends(get_db)):
    """Aggregate health of the alert pipeline (no PII): how many active saved
    searches exist, how many distinct users have alerts on, and how fresh the
    last-checked timestamps are. Fresh timestamps => the cron is actually firing.
    """
    now = datetime.utcnow()
    res = await db.execute(select(SavedSearch).where(SavedSearch.active == True))
    searches = res.scalars().all()

    checked_ats = [s.last_checked_at for s in searches if s.last_checked_at]
    never_checked = sum(1 for s in searches if not s.last_checked_at)
    most_recent = max(checked_ats) if checked_ats else None
    oldest = min(checked_ats) if checked_ats else None

    def mins_ago(dt):
        return round((now - dt).total_seconds() / 60, 1) if dt else None

    # "stale" = past due by >2x its interval (likely the cron isn't running)
    stale = 0
    for s in searches:
        if not s.last_checked_at:
            continue
        due = (s.check_interval_minutes or 15) * 2
        if (now - s.last_checked_at).total_seconds() / 60 > due:
            stale += 1

    users = {s.user_id for s in searches}
    contactable = 0
    if users:
        ures = await db.execute(select(User).where(User.id.in_(users)))
        for u in ures.scalars().all():
            if u.email or u.phone:
                contactable += 1

    pop_res = await db.execute(select(PopWatch).where(PopWatch.active == True))
    pop_watches = len(pop_res.scalars().all())

    return {
        "active_searches": len(searches),
        "users_with_alerts": len(users),
        "users_contactable": contactable,
        "never_checked": never_checked,
        "stale_searches": stale,
        "most_recent_check_mins_ago": mins_ago(most_recent),
        "oldest_check_mins_ago": mins_ago(oldest),
        "active_pop_watches": pop_watches,
        "server_time": now.isoformat() + "Z",
    }


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
async def test_send(sms: bool = False):
    """Attempt a real email (and optionally SMS) and report the actual errors.
    Email only by default; pass ?sms=1 to also fire a real test SMS. This avoids
    random crawlers/bots that hit this URL triggering texts to your phone."""
    import smtplib, os
    from email.mime.text import MIMEText
    results = {}

    # Test Twilio SMS — opt-in only (?sms=1), so stray GETs don't text the phone
    if sms:
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
    else:
        results["sms"] = "skipped (pass ?sms=1 to test SMS)"

    # Test the real email path (Brevo preferred, SendGrid fallback)
    try:
        from alerts import _deliver_email, BREVO_API_KEY
        ok = _deliver_email(
            "ahronriss@gmail.com",
            subject="Card Finder Test",
            text="Card Finder test email ✓",
            html="<p>Card Finder test email ✓</p>",
        )
        provider = "Brevo" if BREVO_API_KEY else "SendGrid"
        results["email"] = f"sent ok via {provider}" if ok else f"FAILED via {provider} (see server logs)"
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
