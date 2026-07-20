from fastapi import FastAPI, Depends, HTTPException, Header, Request, Response
import secrets as _secrets
import time as _time
from collections import defaultdict
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func, delete as sa_delete
from pydantic import BaseModel
from typing import Optional
import asyncio
import json
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import os
from database import init_db, get_db, User, SavedSearch, CardListing, CardShop, PopWatch, PopLookup, CallerNote, CallerDeal, Task, SmsConversation, SmsMessage, BroadcastGroup, BroadcastContact, BroadcastLog, BroadcastTemplate, ScheduledBroadcast, ReleaseProduct, ReleaseCard, ReleaseCalendar, SentAlert, WatchedAuction, PortfolioCard, SellerWatch, SHOP_EDITABLE_FIELDS
from scrapers.ebay_scraper import search_cards, get_sold_history
from scrapers.psa_api import psa_cert_lookup, PSA_API_TOKEN
from agents.price_analyst import analyze_deal
from agents.misspelling_finder import generate_misspellings
import anthropic as _anthropic
_claude = _anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
from alerts import send_alert, send_pop_alert, send_release_alert, send_release_new_alert, send_digest, send_seller_alert
from mock_data import MOCK_LISTINGS, MOCK_SOLD
from database import AuthSession
from auth import current_user, issue_session, norm_email, hash_password, verify_password

USE_MOCK = False  # Browse API active


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    asyncio.create_task(_run_sheet_sync())  # best-effort sync on startup, non-blocking
    await _seed_ebay_usage()  # restore today's eBay call count (survives restarts)
    app.state.ebay_usage_flusher = asyncio.create_task(_ebay_usage_flusher())  # keep ref
    # Self-driving alert scheduler so freshness doesn't depend on an external pinger.
    app.state.alert_loop = asyncio.create_task(_alert_scheduler_loop())  # keep ref (no GC)
    yield

app = FastAPI(title="Card Finder API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Known frontend origin(s); add more via CORS_ORIGINS (comma-separated).
    allow_origins=[o.strip() for o in os.getenv(
        "CORS_ORIGINS",
        "https://card-finder-seven.vercel.app,https://26cards.vercel.app").split(",") if o.strip()],
    # Also allow ANY *.vercel.app subdomain so renaming the site (or preview
    # deploys) never breaks the frontend->backend calls again. Auth is by bearer
    # token / shop password, not cookies, so a permissive CORS origin is safe here.
    allow_origin_regex=r"https://[a-z0-9-]+\.vercel\.app",
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
    digest: Optional[bool] = None


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
    include_auctions: bool = False
    check_interval_minutes: float = 60.0
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
    include_auctions: bool = False
    check_interval_minutes: float = 60.0
    alert_method: str = "both"


# --- Routes ---

# --- Email + password login ---

class AuthRequest(BaseModel):
    email: str
    password: str


def _user_dict(user) -> dict:
    return {"id": user.id, "email": user.email, "phone": user.phone,
            "carrier": user.carrier, "alert_method": user.alert_method,
            "extra_emails": user.extra_emails, "extra_phones": user.extra_phones,
            "digest": bool(getattr(user, "digest", False))}


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


# Basic in-memory brute-force throttle: max failed logins per client IP per window.
_login_fails: dict = defaultdict(list)
_LOGIN_WINDOW_S = 300   # 5 minutes
_LOGIN_MAX_FAILS = 10


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return (xff.split(",")[0].strip() if xff else
            (request.client.host if request.client else "?"))


@app.post("/auth/login")
async def login(req: AuthRequest, request: Request, db: AsyncSession = Depends(get_db)):
    email = norm_email(req.email)
    password = req.password or ""
    if not email or not password:
        raise HTTPException(400, "Email and password required")

    ip = _client_ip(request)
    now = _time.time()
    recent = [t for t in _login_fails[ip] if now - t < _LOGIN_WINDOW_S]
    _login_fails[ip] = recent
    if len(recent) >= _LOGIN_MAX_FAILS:
        raise HTTPException(429, "Too many login attempts — try again in a few minutes.")

    r = await db.execute(select(User).where(func.lower(User.email) == email))
    user = r.scalar_one_or_none()
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        _login_fails[ip].append(now)
        raise HTTPException(401, "Incorrect email or password")

    _login_fails.pop(ip, None)  # clear on success
    token = await issue_session(db, user.id)
    return {"token": token, "user": _user_dict(user)}


class ResetRequest(BaseModel):
    email: str
    origin: Optional[str] = None   # site URL, so the reset LINK points back to the app


class ResetConfirm(BaseModel):
    email: str
    code: str
    password: str


_DEFAULT_APP_ORIGIN = os.getenv("APP_ORIGIN", "https://26cards.vercel.app")


@app.post("/auth/request-reset")
async def request_reset(req: ResetRequest, db: AsyncSession = Depends(get_db)):
    """Email a password-reset LINK (with a one-time token). Returns a generic
    success either way so it can't be used to probe which emails have accounts."""
    from alerts import _deliver_email
    from datetime import timedelta
    from urllib.parse import quote
    import secrets
    email = norm_email(req.email)
    r = await db.execute(select(User).where(func.lower(User.email) == email))
    user = r.scalar_one_or_none()
    if user and user.email:
        token = secrets.token_urlsafe(24)
        user.reset_code = token
        user.reset_expires = datetime.utcnow() + timedelta(hours=1)
        await db.commit()
        origin = (req.origin or "").strip().rstrip("/") or _DEFAULT_APP_ORIGIN
        if not origin.startswith("http"):
            origin = _DEFAULT_APP_ORIGIN
        link = f"{origin}/?reset={token}&email={quote(user.email)}"
        html = (f'<div style="font-family:-apple-system,sans-serif;max-width:480px">'
                f'<h2 style="color:#7c3aed">Reset your Card Finder password</h2>'
                f'<p>Click the button below to set a new password. This link expires in 1 hour.</p>'
                f'<p style="margin:24px 0"><a href="{link}" '
                f'style="background:linear-gradient(135deg,#f97316,#ec4899);color:#fff;padding:14px 28px;'
                f'border-radius:10px;text-decoration:none;font-weight:700;display:inline-block">'
                f'Reset my password</a></p>'
                f'<p style="color:#475569;font-size:13px">Or paste this link into your browser:<br>'
                f'<a href="{link}">{link}</a></p>'
                f'<p style="color:#94a3b8;font-size:12px">If you didn\'t request this, ignore this email.</p></div>')
        _deliver_email(user.email, subject="Reset your Card Finder password",
                       html=html,
                       text=f"Reset your Card Finder password (expires in 1 hour):\n{link}\n\nIf you didn't request this, ignore this email.")
    return {"ok": True, "message": "If that email has an account, a reset link is on its way. Check your inbox (and spam)."}


@app.post("/auth/reset-password")
async def reset_password(req: ResetConfirm, db: AsyncSession = Depends(get_db)):
    """Verify the emailed code and set a new password, then sign the user in."""
    email = norm_email(req.email)
    code = (req.code or "").strip()
    if len(req.password or "") < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    r = await db.execute(select(User).where(func.lower(User.email) == email))
    user = r.scalar_one_or_none()
    if (not user or not user.reset_code or not code or user.reset_code != code
            or not user.reset_expires or user.reset_expires < datetime.utcnow()):
        raise HTTPException(400, "Invalid or expired reset code. Request a new one.")
    user.password_hash = hash_password(req.password)
    user.reset_code = None
    user.reset_expires = None
    await db.commit()
    await db.refresh(user)
    token = await issue_session(db, user.id)
    return {"token": token, "user": _user_dict(user)}


class ChangePasswordRequest(BaseModel):
    new_password: str


@app.post("/auth/change-password")
async def change_password(req: ChangePasswordRequest, db: AsyncSession = Depends(get_db),
                          user: User = Depends(current_user)):
    """Change the signed-in user's password (no email needed)."""
    if len(req.new_password or "") < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"ok": True}


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
    if data.email: user.email = data.email.strip().lower()  # email is the login id — only set, never blank
    if data.phone is not None: user.phone = _blank(data.phone)  # "" clears the primary phone; omitted = no change
    if data.carrier is not None: user.carrier = data.carrier
    if data.extra_emails is not None: user.extra_emails = _blank(data.extra_emails)
    if data.extra_phones is not None: user.extra_phones = _blank(data.extra_phones)
    if data.digest is not None: user.digest = bool(data.digest)
    user.alert_method = data.alert_method
    await db.commit()
    return _user_dict(user)


class CardLookupRequest(BaseModel):
    image: Optional[str] = ""               # base64 (data-URL prefix tolerated)
    image_url: Optional[str] = None         # OR a photo URL (e.g. a recent find) — server fetches it
    media_type: Optional[str] = "image/jpeg"


def _filter_exact_comps(card: dict, query: str, sold: list) -> list:
    """Keep only comps that are the SAME card: the player's name, the parallel's
    distinctive words (e.g. 'gold', 'sapphire'), and the serial (e.g. /50) must all
    appear in the comp title — so 'Gold Sapphire /50' doesn't match 'Purple /75' or
    'Gold Geometric'."""
    import re
    GENERIC = {"auto", "autograph", "rc", "rookie", "card", "cards", "refractor",
               "prizm", "parallel", "insert", "mint", "gem", "psa", "bgs", "sgc",
               "the", "and", "of", "variation"}
    req = set()
    # Player: require only the last name — listings often drop the first name.
    pw = [w for w in re.split(r"[^a-z0-9]+", (card.get("player") or "").lower()) if len(w) >= 3]
    if pw:
        req.add(pw[-1])
    # Parallel: require each distinctive word (gold, sapphire, orange, refractor color…).
    for w in re.split(r"[^a-z0-9]+", (card.get("parallel") or "").lower()):
        if len(w) >= 3 and w not in GENERIC:
            req.add(w)
    if not req:
        return []                                  # nothing distinctive to match on
    sm = re.search(r"/(\d+)", " ".join(str(x or "") for x in
                   (card.get("parallel"), card.get("card_number"), query)))
    serial = sm.group(1) if sm else None

    def ok(title):
        t = (title or "").lower()
        if not all(w in t for w in req):
            return False
        if serial and not re.search(rf"/0*{serial}(?!\d)", t):
            return False
        return True
    return [s for s in sold if ok(s.get("title"))]


def _price_from_comps(sold: list) -> dict:
    """Turn eBay sold comps into a pricing readout: market value, recommended
    buy price, and a probability the card flips for a profit."""
    import statistics
    prices = sorted(s.get("sold_price") for s in sold if s.get("sold_price"))
    n = len(prices)
    if n == 0:
        return {"count": 0}
    market = statistics.median(prices)
    last_sold = sold[0].get("sold_price") if sold else None  # most recent comp
    fees = 0.13                              # eBay + shipping, rough
    buy = round(market * 0.70)               # buy at ~70% of market
    break_even_sale = buy / (1 - fees)       # must sell above this to profit
    profit_prob = round(100 * sum(1 for p in prices if p > break_even_sale) / n)
    expected_profit = round(market * (1 - fees) - buy)
    return {
        "count": n,
        "market": round(market),
        "last_sold": round(last_sold) if last_sold else None,
        "low": round(prices[0]),
        "high": round(prices[-1]),
        "recommended_buy": buy,
        "profit_probability": profit_prob,   # % of comps that clear buy + fees
        "expected_profit": expected_profit,  # net if bought at buy, sold at market
        "fees_pct": int(fees * 100),
    }


@app.post("/card-lookup")
async def card_lookup(req: CardLookupRequest):
    """Identify a card from a photo (Claude vision) and price it from eBay sold
    comps: market value, recommended buy price, and profit probability. (PSA
    pop report / gem rate is Phase 2 — needs PSA_API_TOKEN.)"""
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(503, "Card identification isn't configured yet (missing GROQ_API_KEY).")
    img = req.image or ""
    media_type = req.media_type or "image/jpeg"
    if not img and req.image_url:
        # Recent finds come with a photo URL — fetch it server-side (avoids browser
        # CORS on i.ebayimg.com) and base64-encode it for the vision model.
        import base64 as _b64, httpx as _httpx
        try:
            async with _httpx.AsyncClient(timeout=15, follow_redirects=True) as _c:
                r = await _c.get(req.image_url, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
            img = _b64.b64encode(r.content).decode()
            media_type = (r.headers.get("content-type") or media_type).split(";")[0].strip()
        except Exception as e:
            print(f"card-lookup image-url fetch error: {e}")
            raise HTTPException(502, "Couldn't load that find's photo. Try uploading it instead.")
    if img.strip().startswith("data:") and "," in img:
        img = img.split(",", 1)[1]            # strip data-URL prefix
    if not img:
        raise HTTPException(400, "No image provided.")

    from card_vision import identify_card
    try:
        card = await identify_card(img, media_type)
    except Exception as e:
        msg = str(e)
        print(f"card-lookup vision error: {msg}")
        low = msg.lower()
        if "429" in low or "rate limit" in low or "too many" in low:
            raise HTTPException(429, "Card ID is busy (free Groq rate limit) — wait a few seconds and try again.")
        raise HTTPException(502, "Couldn't read the card from that photo. Try a clearer, well-lit shot.")

    if not card.get("identified"):
        return {"identified": False, "card": card, "pricing": None, "comps": []}

    query = card.get("search_query") or " ".join(filter(None, [
        card.get("year"), card.get("brand"), card.get("player"),
        card.get("parallel"), card.get("card_number"),
        (f"{card.get('grader')} {card.get('grade')}" if card.get("is_graded") else None),
    ]))
    sold = await get_sold_history(query, limit=25)
    exact = _filter_exact_comps(card, query, sold)
    comps = exact if exact else sold               # exact-card comps; fall back if none match
    return {
        "identified": True,
        "card": card,
        "query": query,
        "exact_comps": bool(exact),
        "pricing": _price_from_comps(comps),
        "comps": [{"title": s.get("title"), "price": s.get("sold_price"),
                   "url": s.get("listing_url"), "image_url": s.get("image_url")}
                  for s in comps[:8]],
    }


class PopLookupSave(BaseModel):
    thumb: str
    result: dict


@app.get("/pop-lookups")
async def list_pop_lookups(me: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """The signed-in user's saved Pop Report lookups (most recent first)."""
    import json as _json
    res = await db.execute(select(PopLookup).where(PopLookup.user_id == me.id)
                           .order_by(PopLookup.created_at.desc()).limit(24))
    rows = res.scalars().all()
    out = []
    for r in rows:
        try:
            out.append({"id": r.id, "thumb": r.thumb, "result": _json.loads(r.result_json or "{}"),
                        "ts": int(r.created_at.timestamp() * 1000) if r.created_at else 0})
        except Exception:
            continue
    return {"lookups": out}


@app.post("/pop-lookups")
async def save_pop_lookup(req: PopLookupSave, me: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    """Save a lookup (screenshot thumbnail + result), keeping the last 24 per user."""
    import json as _json
    row = PopLookup(user_id=me.id, thumb=req.thumb[:400_000],
                    result_json=_json.dumps(req.result)[:200_000])
    db.add(row)
    await db.flush()
    # Trim to the 24 most recent for this user.
    old = (await db.execute(select(PopLookup.id).where(PopLookup.user_id == me.id)
           .order_by(PopLookup.created_at.desc()).offset(24))).scalars().all()
    for oid in old:
        await db.execute(sa_delete(PopLookup).where(PopLookup.id == oid))
    await db.commit()
    return {"id": row.id}


@app.delete("/pop-lookups/{lookup_id}")
async def delete_pop_lookup(lookup_id: int, me: User = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    row = await db.get(PopLookup, lookup_id)
    if not row:
        raise HTTPException(404, "Not found")
    if row.user_id != me.id:
        raise HTTPException(403, "Not yours")
    await db.execute(sa_delete(PopLookup).where(PopLookup.id == lookup_id))
    await db.commit()
    return {"ok": True}


@app.delete("/pop-lookups")
async def clear_pop_lookups(me: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.execute(sa_delete(PopLookup).where(PopLookup.user_id == me.id))
    await db.commit()
    return {"ok": True}


class CardChatRequest(BaseModel):
    context: dict                                  # {card, pricing, pop, query}
    messages: Optional[list] = None                # [{role, content}, ...] follow-ups


def _card_context_block(ctx: dict) -> str:
    card = ctx.get("card") or {}
    pricing = ctx.get("pricing") or {}
    pop = ctx.get("pop")
    lines = []
    name = " ".join(filter(None, [card.get("year"), card.get("brand"), card.get("player"),
                                   card.get("parallel"),
                                   (f"#{card.get('card_number')}" if card.get("card_number") else None)]))
    lines.append(f"Card: {name or 'unknown'}")
    if card.get("is_graded"):
        lines.append(f"Graded: {card.get('grader')} {card.get('grade')}"
                     + (f" (cert {card.get('cert_number')})" if card.get("cert_number") else ""))
    if pop:
        lines.append(f"PSA population: {pop.get('total')} graded total, {pop.get('psa10')} are PSA 10 "
                     f"(gem rate {pop.get('gem_rate')}%). Per-grade: {pop.get('grades')}.")
    if (pricing or {}).get("count"):
        lines.append(f"eBay sold comps ({pricing.get('count')}): market ${pricing.get('market')}, "
                     f"last sold ${pricing.get('last_sold')}, range ${pricing.get('low')}-${pricing.get('high')}. "
                     f"Recommended buy ${pricing.get('recommended_buy')}, est net profit ${pricing.get('expected_profit')} "
                     f"({pricing.get('profit_probability')}% of comps clear buy + fees).")
    else:
        lines.append("No eBay sold comps found.")
    return "\n".join(lines)


_CARD_ADVISOR_SYSTEM = (
    "You are a sharp, practical sports-card investment advisor. You're given a card's identity, its PSA "
    "population/gem rate, and eBay sold-comp pricing. Explain what the numbers mean in plain English, then give a "
    "clear verdict — BUY, HOLD, or PASS — with a one-line reason. Reasoning to use: a LOW gem rate means a PSA 10 is "
    "scarcer and commands a bigger premium; a HIGH total population means more supply and softer prices; compare the "
    "recommended buy vs market for margin. Be concise and direct. Never invent data you weren't given; if comps or pop "
    "are missing, say so."
)


@app.post("/card-chat")
async def card_chat(req: CardChatRequest):
    """AI advisor for a looked-up card: summarizes the pop + pricing data and
    gives a buy/hold/pass verdict; answers follow-up questions with that context."""
    if not os.getenv("GROQ_API_KEY"):
        raise HTTPException(503, "AI summary isn't configured (missing GROQ_API_KEY).")
    import ai
    ctx_block = _card_context_block(req.context or {})
    msgs = req.messages or []
    if not msgs:
        prompt = f"{ctx_block}\n\nSummarize this card's data and tell me whether to buy it."
    else:
        convo = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in msgs)
        prompt = f"Card data:\n{ctx_block}\n\nConversation so far:\n{convo}\n\nAnswer the latest question concisely, using the card data."
    try:
        answer = await asyncio.to_thread(ai.generate, prompt, _CARD_ADVISOR_SYSTEM, 450)
    except Exception as e:
        print(f"card-chat error: {e}")
        raise HTTPException(502, "AI advisor is busy — try again in a moment.")
    return {"answer": (answer or "").strip()}


# eBay trading-card categories by TYPE (sport isn't a category — it's an aspect).
_TREND_CATEGORIES = {
    "all":     ["261328", "183454"],  # sports singles + CCG (Pokemon/MTG/etc.)
    "singles": ["261328"],
    "boxes":   ["261332"],            # sealed boxes
    "packs":   ["261331"],            # sealed packs
    "cases":   ["261333"],            # sealed cases
    "lots":    ["261329"],            # card lots
    "breaks":  ["261334"],            # box & case breaks
    "pokemon": ["183454"],            # CCG individual cards
}

# Best-effort sport detection from the title (eBay omits the sport from most titles,
# so we lean on Pokemon/TCG names + league words + major teams/stars).
_SPORT_HINTS = [
    ("Pokémon/TCG", ["pokemon", "pokémon", "charizard", "pikachu", "yu-gi-oh", "yugioh", "yu gi oh",
        "mtg", "magic the gathering", "one piece", "lorcana", "gengar", "umbreon", "mewtwo", "eevee",
        "wotc", "wizards of the coast", "tcg", "japanese card", "ccg"]),
    ("Basketball", ["basketball", "nba", "wnba", "wembanyama", "jordan", "lebron", "kobe", "curry",
        "doncic", "jokic", "durant", "giannis", "luka", "flagg", "anthony edwards", "gilgeous", "shai",
        "bronny", "caitlin clark", "ja morant", "zion", "victor wemb", "tatum", "brunson", "dybantsa",
        "lakers", "celtics", "warriors", "spurs", "mavericks", "mavs", "nuggets", "thunder", "cavaliers",
        "cavs", "knicks", "76ers", "sixers", "bulls", "heat", "bucks", "suns", "clippers", "pelicans",
        "grizzlies", "timberwolves", "rockets", "jazz", "hawks", "hornets", "pistons", "pacers",
        "raptors", "wizards", "nets", "trail blazers", "blazers"]),
    ("Football", ["nfl", "football", "mahomes", "tom brady", "josh allen", "burrow", "justin jefferson",
        "ja'marr", "herbert", "lamar jackson", "caleb williams", "jayden daniels", "bo nix", "drake maye",
        "joe montana", "jerry rice", "peyton manning", "cowboys", "chiefs", "49ers", "niners", "eagles",
        "packers", "raiders", "bills", "bengals", "ravens", "lions", "patriots", "steelers", "dolphins",
        "commanders", "vikings", "bears", "saints", "falcons", "buccaneers", "bucs", "rams", "chargers",
        "broncos", "titans", "colts", "jaguars", "texans", "seahawks", "browns"]),
    ("Baseball", ["baseball", "mlb", "ohtani", "aaron judge", "mike trout", "acuna", "juan soto",
        "tatis", "mookie betts", "bryce harper", "paul skenes", "skenes", "mickey mantle", "mantle",
        "derek jeter", "ken griffey", "pujols", "bobby witt", "elly de la cruz", "yankees", "dodgers",
        "braves", "red sox", "mets", "cubs", "padres", "pirates", "guardians", "twins", "astros",
        "mariners", "blue jays", "phillies", "brewers", "reds", "rockies", "marlins", "nationals",
        "white sox", "athletics", "royals", "tigers", "orioles"]),
    ("Soccer", ["soccer", "fifa", "uefa", "world cup", "premier league", "la liga", "messi", "ronaldo",
        "mbappe", "mbappé", "haaland", "yamal", "bellingham", "neymar", "pele", "maradona", "vinicius",
        "barcelona", "real madrid", "manchester", "psg", "liverpool", "arsenal", "chelsea", "bayern"]),
    ("Hockey", ["nhl", "hockey", "mcdavid", "gretzky", "crosby", "ovechkin", "bedard", "auston matthews",
        "cale makar", "maple leafs", "canadiens", "bruins", "oilers", "blackhawks", "penguins",
        "red wings", "flyers", "capitals", "lightning", "avalanche", "golden knights", "kraken"]),
    ("UFC/MMA", ["ufc", " mma", "mma ", "bellator", "jon jones", "conor mcgregor", "mcgregor",
        "khabib", "israel adesanya", "octagon"]),
    # Generic multi-sport collections/lots that name no single sport.
    ("Mixed/Lot", ["storage unit", "million cards", "estate find", "estate sale", "liquidation",
        "collection find", "card chase box", "huge collection", "unopened pack lot", "mystery"]),
]


def _detect_card_sport(title: str) -> str:
    t = (title or "").lower()
    for sport, hints in _SPORT_HINTS:
        if any(h in t for h in hints):
            return sport
    return "Other"


@app.get("/trending-cards")
async def trending_cards(category: str = "all"):
    """The most-watched trading cards on eBay right now, by TYPE category. Each card
    is tagged with a best-effort `sport` so the UI can filter by sport too."""
    import httpx
    app_id = os.getenv("EBAY_APP_ID", "")
    if not app_id:
        raise HTTPException(503, "eBay isn't configured (missing EBAY_APP_ID).")
    SKIP = ("grading tool", "centering tool", "toploader", "sleeves", "card saver",
            "binder", "supplies", "magnetic holder")
    cats = _TREND_CATEGORIES.get(category, _TREND_CATEGORIES["all"])
    items = []
    async with httpx.AsyncClient(timeout=20) as client:
        for cat in cats:
            try:
                r = await client.get("https://svcs.ebay.com/MerchandisingService", params={
                    "OPERATION-NAME": "getMostWatchedItems", "SERVICE-VERSION": "1.1.0",
                    "CONSUMER-ID": app_id, "RESPONSE-DATA-FORMAT": "JSON",
                    "categoryId": cat, "maxResults": "20"})
                recs = (r.json().get("getMostWatchedItemsResponse", {})
                        .get("itemRecommendations", {}).get("item", []))
                for it in recs:
                    title = it.get("title") or ""
                    if any(s in title.lower() for s in SKIP):
                        continue
                    tl = title.lower()
                    items.append({
                        "title": title,
                        "watch_count": int(it.get("watchCount") or 0),
                        "price": float((it.get("buyItNowPrice") or {}).get("__value__") or 0) or None,
                        "url": it.get("viewItemURL"),
                        "image_url": it.get("imageURL"),
                        "sport": _detect_card_sport(title),
                        "graded": any(g in tl for g in ("psa", "bgs", "sgc", "cgc", "gem mt", "gem mint")),
                        "auto": ("auto" in tl or "autograph" in tl),
                    })
            except Exception as e:
                print(f"trending-cards fetch error (cat {cat}): {e}")
    seen, out = set(), []
    for it in sorted(items, key=lambda x: -x["watch_count"]):
        if not it["url"] or it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
    return {"cards": out[:40], "as_of": datetime.utcnow().isoformat()}


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
        include_auctions=req.include_auctions,
        check_interval_minutes=req.check_interval_minutes,
        alert_method=req.alert_method,
    )
    db.add(search)
    await db.commit()
    await db.refresh(search)
    return {"id": search.id, "query": search.query}


@app.get("/my-finds")
async def my_finds(limit: int = 60, db: AsyncSession = Depends(get_db),
                   me: User = Depends(current_user)):
    """Recent alert finds (cards actually sent) for the logged-in user."""
    res = await db.execute(
        select(SentAlert).where(SentAlert.user_id == me.id)
        .order_by(SentAlert.sent_at.desc()).limit(min(limit, 200)))
    return [{
        "sent_at": s.sent_at.isoformat() if s.sent_at else None,
        "title": s.title, "price": s.price, "is_auction": bool(s.is_auction),
        "pct_vs_market": s.pct_vs_market, "alert": s.query,
        "listing_url": s.listing_url, "image_url": s.image_url,
        "sport": _detect_card_sport(f"{s.title or ''} {s.query or ''}"),
    } for s in res.scalars().all()]


@app.get("/alert-auctions")
async def alert_auctions(search_id: int, db: AsyncSession = Depends(get_db),
                         me: User = Depends(current_user)):
    """Browse current eBay AUCTIONS matching one of the user's saved alerts —
    on demand, no alerts sent. Ignores the 24h-freshness/price-floor filters so
    you see all live auctions for that card."""
    s = await db.get(SavedSearch, search_id)
    if not s or s.user_id != me.id:
        raise HTTPException(404, "Alert not found")
    from alert_filters import build_query, _ebay_keywords, passes_filters, detect_sport
    listings = await search_cards(_ebay_keywords(build_query(s)), None, None, 50, auctions_only=True, sport=detect_sport(build_query(s)))
    out = [l for l in listings if l.get("is_auction") and passes_filters(s, l)]
    out.sort(key=lambda l: l.get("end_date") or "9999")  # ending soonest first
    return [{"external_id": l.get("external_id"), "title": l.get("title"), "price": l.get("price"),
             "listing_url": l.get("listing_url"), "image_url": l.get("image_url"),
             "end_date": l.get("end_date")}
            for l in out]


@app.get("/alert-auctions-all")
async def alert_auctions_all(db: AsyncSession = Depends(get_db), me: User = Depends(current_user)):
    """Live eBay auctions across ALL of the user's alerts, merged and sorted by
    ending-soonest. On demand — uses ~1 eBay call per unique alert search."""
    from alert_filters import build_query, _ebay_keywords, passes_filters, detect_sport
    res = await db.execute(select(SavedSearch).where(
        SavedSearch.user_id == me.id, SavedSearch.active == True))
    searches = [s for s in res.scalars().all() if (getattr(s, "source", None) or "ebay") == "ebay"]

    sem = asyncio.Semaphore(6)  # bounded concurrency so we don't hammer eBay

    async def fetch(s):
        async with sem:
            try:
                listings = await search_cards(_ebay_keywords(build_query(s)), None, None, 50, auctions_only=True, sport=detect_sport(build_query(s)))
            except Exception:
                return []
        return [(s, l) for l in listings if l.get("is_auction") and passes_filters(s, l)]

    groups = await asyncio.gather(*[fetch(s) for s in searches])
    merged = {}
    for group in groups:
        for s, l in group:
            eid = l.get("external_id")
            if eid and eid not in merged:
                merged[eid] = {"external_id": eid, "title": l.get("title"), "price": l.get("price"),
                               "listing_url": l.get("listing_url"), "image_url": l.get("image_url"),
                               "end_date": l.get("end_date"), "alert": s.query}
    out = sorted(merged.values(), key=lambda x: x.get("end_date") or "9999")
    return out[:80]


@app.get("/alert-matches-all")
async def alert_matches_all(db: AsyncSession = Depends(get_db), me: User = Depends(current_user)):
    """All current eBay listings (Buy-It-Now + auctions) matching ANY of the
    user's alerts — on demand, no 24h/price filter, most valuable first."""
    from alert_filters import build_query, _ebay_keywords, passes_filters, detect_sport
    res = await db.execute(select(SavedSearch).where(
        SavedSearch.user_id == me.id, SavedSearch.active == True))
    searches = [s for s in res.scalars().all() if (getattr(s, "source", None) or "ebay") == "ebay"]

    sem = asyncio.Semaphore(6)

    async def fetch(s):
        async with sem:
            try:
                listings = await search_cards(_ebay_keywords(build_query(s)), None, None, 50, include_auctions=True, sport=detect_sport(build_query(s)))
            except Exception:
                return []
        return [(s, l) for l in listings if passes_filters(s, l)]

    groups = await asyncio.gather(*[fetch(s) for s in searches])
    merged = {}
    for group in groups:
        for s, l in group:
            eid = l.get("external_id")
            if eid and eid not in merged:
                merged[eid] = {"external_id": eid, "title": l.get("title"), "price": l.get("price"),
                               "listing_url": l.get("listing_url"), "image_url": l.get("image_url"),
                               "is_auction": bool(l.get("is_auction")), "alert": s.query}
    out = sorted(merged.values(), key=lambda x: -(x.get("price") or 0))  # most valuable first
    return out[:100]


@app.get("/deals-feed")
async def deals_feed(db: AsyncSession = Depends(get_db), me: User = Depends(current_user)):
    """The best current STEALS across all the user's alerts: Buy-It-Now listings
    priced below their eBay sold-comp market value, ranked by % under market.
    Uses ~2 eBay calls per alert (listings + sold comps), so it's on-demand."""
    import statistics
    from alert_filters import build_query, _ebay_keywords, passes_filters, detect_sport
    res = await db.execute(select(SavedSearch).where(
        SavedSearch.user_id == me.id, SavedSearch.active == True))
    searches = [s for s in res.scalars().all() if (getattr(s, "source", None) or "ebay") == "ebay"]

    sem = asyncio.Semaphore(5)

    async def fetch(s):
        q = build_query(s)
        async with sem:
            try:
                listings, sold = await asyncio.gather(
                    search_cards(_ebay_keywords(q), None, None, 50, include_auctions=False, sport=detect_sport(q)),
                    get_sold_history(q, limit=25),
                )
            except Exception:
                return []
        prices = sorted(x.get("sold_price") for x in sold if x.get("sold_price"))
        if len(prices) < 3:
            return []  # too few comps to trust a market value
        market = statistics.median(prices)
        if market <= 0:
            return []
        rows = []
        for l in listings:
            if l.get("is_auction") or not passes_filters(s, l):
                continue
            p = l.get("price") or 0
            if p <= 0:
                continue
            pct = (market - p) / market * 100.0
            if pct < 10:  # only genuine deals — 10%+ under market
                continue
            rows.append({
                "external_id": l.get("external_id"), "title": l.get("title"),
                "price": round(p, 2), "market": round(market),
                "pct_below": round(pct, 1), "comps": len(prices),
                "listing_url": l.get("listing_url"), "image_url": l.get("image_url"),
                "alert": s.query,
            })
        return rows

    groups = await asyncio.gather(*[fetch(s) for s in searches])
    merged = {}
    for group in groups:
        for r in group:
            eid = r.get("external_id")
            if eid and (eid not in merged or r["pct_below"] > merged[eid]["pct_below"]):
                merged[eid] = r
    out = sorted(merged.values(), key=lambda x: -x["pct_below"])
    return out[:60]


# --- Portfolio: track cards you own + value them against eBay sold comps ---

class PortfolioAddRequest(BaseModel):
    name: str
    paid: Optional[float] = None
    qty: int = 1
    notes: Optional[str] = None


class PortfolioUpdateRequest(BaseModel):
    paid: Optional[float] = None
    qty: Optional[int] = None
    notes: Optional[str] = None


def _portfolio_dict(c) -> dict:
    return {"id": c.id, "name": c.name, "paid": c.paid, "qty": c.qty or 1, "notes": c.notes,
            "market_value": c.market_value, "comps": c.comps,
            "valued_at": c.valued_at.isoformat() if c.valued_at else None}


@app.get("/portfolio")
async def get_portfolio(db: AsyncSession = Depends(get_db), me: User = Depends(current_user)):
    res = await db.execute(select(PortfolioCard).where(PortfolioCard.user_id == me.id)
                           .order_by(PortfolioCard.created_at.desc()))
    return [_portfolio_dict(c) for c in res.scalars().all()]


@app.post("/portfolio")
async def add_portfolio_card(req: PortfolioAddRequest, db: AsyncSession = Depends(get_db),
                             me: User = Depends(current_user)):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Give the card a name/search.")
    c = PortfolioCard(user_id=me.id, name=name, paid=req.paid, qty=max(1, req.qty or 1),
                      notes=(req.notes or "").strip() or None)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return _portfolio_dict(c)


@app.put("/portfolio/{card_id}")
async def update_portfolio_card(card_id: int, req: PortfolioUpdateRequest, db: AsyncSession = Depends(get_db),
                                me: User = Depends(current_user)):
    c = await db.get(PortfolioCard, card_id)
    if not c or c.user_id != me.id:
        raise HTTPException(404, "Card not found")
    if req.paid is not None: c.paid = req.paid
    if req.qty is not None: c.qty = max(1, req.qty)
    if req.notes is not None: c.notes = (req.notes or "").strip() or None
    await db.commit()
    return _portfolio_dict(c)


@app.delete("/portfolio/{card_id}")
async def delete_portfolio_card(card_id: int, db: AsyncSession = Depends(get_db),
                                me: User = Depends(current_user)):
    c = await db.get(PortfolioCard, card_id)
    if not c or c.user_id != me.id:
        raise HTTPException(404, "Card not found")
    await db.delete(c)
    await db.commit()
    return {"deleted": True}


@app.post("/portfolio/revalue")
async def revalue_portfolio(db: AsyncSession = Depends(get_db), me: User = Depends(current_user)):
    """Refresh each owned card's market value from eBay sold comps (median).
    ~1 eBay call per card, so it's on-demand. Returns the updated list + totals."""
    import statistics
    res = await db.execute(select(PortfolioCard).where(PortfolioCard.user_id == me.id))
    cards = res.scalars().all()
    sem = asyncio.Semaphore(5)
    now = datetime.utcnow()

    async def value(c):
        async with sem:
            try:
                sold = await get_sold_history(c.name, limit=25)
            except Exception:
                return
        prices = sorted(x.get("sold_price") for x in sold if x.get("sold_price"))
        if len(prices) >= 3:
            c.market_value = round(statistics.median(prices), 2)
            c.comps = len(prices)
            c.valued_at = now
        else:
            c.comps = len(prices)
            c.valued_at = now

    await asyncio.gather(*[value(c) for c in cards])
    await db.commit()
    items = [_portfolio_dict(c) for c in cards]
    total_value = sum((c.market_value or 0) * (c.qty or 1) for c in cards)
    total_cost = sum((c.paid or 0) * (c.qty or 1) for c in cards)
    return {"cards": items, "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2), "total_gain": round(total_value - total_cost, 2)}


# --- Seller watch: alert when a specific eBay seller posts new listings ---

class SellerWatchRequest(BaseModel):
    seller_name: str
    label: Optional[str] = None
    alert_method: str = "both"


def _seller_watch_dict(w) -> dict:
    return {"id": w.id, "seller_name": w.seller_name, "label": w.label,
            "alert_method": w.alert_method,
            "last_checked_at": w.last_checked_at.isoformat() if w.last_checked_at else None,
            "url": f"https://www.ebay.com/usr/{w.seller_name}"}


@app.get("/seller-watches")
async def list_seller_watches(db: AsyncSession = Depends(get_db), me: User = Depends(current_user)):
    res = await db.execute(select(SellerWatch).where(
        SellerWatch.user_id == me.id, SellerWatch.active == True).order_by(SellerWatch.id.desc()))
    return [_seller_watch_dict(w) for w in res.scalars().all()]


@app.post("/seller-watches")
async def add_seller_watch(req: SellerWatchRequest, db: AsyncSession = Depends(get_db),
                           me: User = Depends(current_user)):
    name = (req.seller_name or "").strip().lstrip("@")
    if not name:
        raise HTTPException(400, "Enter an eBay seller username.")
    # seed seen_ids with the seller's CURRENT listings so we only alert on NEW ones
    seen = []
    try:
        from alert_filters import detect_sport  # noqa
        listings = await search_cards("", None, None, 50, include_auctions=True, seller=name)
        seen = [l.get("external_id") for l in listings if l.get("external_id")]
    except Exception:
        pass
    w = SellerWatch(user_id=me.id, seller_name=name, label=(req.label or "").strip() or None,
                    seen_ids=json.dumps(seen), last_checked_at=datetime.utcnow(),
                    alert_method=req.alert_method)
    db.add(w)
    await db.commit()
    await db.refresh(w)
    return _seller_watch_dict(w)


@app.delete("/seller-watches/{watch_id}")
async def delete_seller_watch(watch_id: int, db: AsyncSession = Depends(get_db),
                              me: User = Depends(current_user)):
    w = await db.get(SellerWatch, watch_id)
    if not w or w.user_id != me.id:
        raise HTTPException(404, "Seller watch not found")
    w.active = False
    await db.commit()
    return {"deleted": True}


async def _check_seller_watches(db: AsyncSession) -> int:
    """Poll each active seller watch; alert on newly-listed items. Returns count sent."""
    result = await db.execute(select(SellerWatch).where(SellerWatch.active == True))
    watches = result.scalars().all()
    sent = 0
    now = datetime.utcnow()
    for w in watches:
        if w.last_checked_at and (now - w.last_checked_at).total_seconds() < 15 * 60:
            continue
        try:
            listings = await search_cards("", None, None, 50, include_auctions=True, seller=w.seller_name)
        except Exception:
            continue
        w.last_checked_at = now
        seen = set(json.loads(w.seen_ids) if w.seen_ids else [])
        fresh = [l for l in listings if l.get("external_id") and l["external_id"] not in seen]
        if fresh:
            user = await db.get(User, w.user_id)
            if user and (user.email or user.phone):
                send_seller_alert(user, w.seller_name, fresh, method=w.alert_method)
                sent += 1
            seen.update(l["external_id"] for l in fresh)
            w.seen_ids = json.dumps(list(seen)[-500:])  # cap stored ids
    await db.commit()
    return sent


class WatchAuctionRequest(BaseModel):
    external_id: str
    title: Optional[str] = None
    image_url: Optional[str] = None
    listing_url: Optional[str] = None
    price: Optional[float] = None
    end_date: Optional[str] = None


@app.get("/watched-auctions")
async def list_watched_auctions(db: AsyncSession = Depends(get_db), me: User = Depends(current_user)):
    res = await db.execute(select(WatchedAuction).where(WatchedAuction.user_id == me.id)
                           .order_by(WatchedAuction.end_date))
    return [{"id": w.id, "external_id": w.external_id, "title": w.title, "image_url": w.image_url,
             "listing_url": w.listing_url, "price": w.price, "end_date": w.end_date,
             "notified": bool(w.notified)} for w in res.scalars().all()]


@app.post("/watched-auctions")
async def add_watched_auction(req: WatchAuctionRequest, db: AsyncSession = Depends(get_db),
                              me: User = Depends(current_user)):
    existing = await db.execute(select(WatchedAuction).where(
        WatchedAuction.user_id == me.id, WatchedAuction.external_id == req.external_id))
    w = existing.scalar_one_or_none()
    if not w:
        w = WatchedAuction(user_id=me.id, external_id=req.external_id, title=req.title,
                           image_url=req.image_url, listing_url=req.listing_url,
                           price=req.price, end_date=req.end_date)
        db.add(w)
        await db.commit()
        await db.refresh(w)
    return {"id": w.id, "external_id": w.external_id, "watching": True}


@app.delete("/watched-auctions/{external_id}")
async def remove_watched_auction(external_id: str, db: AsyncSession = Depends(get_db),
                                 me: User = Depends(current_user)):
    res = await db.execute(select(WatchedAuction).where(
        WatchedAuction.user_id == me.id, WatchedAuction.external_id == external_id))
    w = res.scalar_one_or_none()
    if w:
        await db.delete(w)
        await db.commit()
    return {"external_id": external_id, "watching": False}


@app.get("/saved-searches/{user_id}")
async def get_saved_searches(user_id: int, db: AsyncSession = Depends(get_db),
                             me: User = Depends(current_user)):
    if user_id != me.id:
        raise HTTPException(403, "Not your account")
    result = await db.execute(
        select(SavedSearch).where(SavedSearch.user_id == me.id, SavedSearch.active == True)
    )
    searches = result.scalars().all()
    return [{"id": s.id, "query": s.query, "sport": s.sport, "min_price": s.min_price, "max_price": s.max_price, "numbered_to": s.numbered_to, "brand": s.brand, "insert_type": s.insert_type, "card_number": s.card_number, "year": s.year, "exclude": s.exclude, "source": s.source or "ebay", "dry_spell_months": s.dry_spell_months, "catch_misspellings": bool(s.catch_misspellings), "deal_threshold_pct": s.deal_threshold_pct, "folder": s.folder, "include_auctions": bool(s.include_auctions), "check_interval_minutes": s.check_interval_minutes, "alert_method": s.alert_method, "health_status": s.health_status, "health_detail": s.health_detail, "health_checked_at": s.health_checked_at.isoformat() if s.health_checked_at else None} for s in searches]


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
    search.include_auctions = req.include_auctions
    search.check_interval_minutes = req.check_interval_minutes
    search.alert_method = req.alert_method
    # Re-baseline on next run so edits take effect cleanly without alert spam.
    search.last_checked_at = None
    await db.commit()
    return {"updated": True}


class LintRequest(BaseModel):
    query: str = ""
    sport: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    numbered_to: Optional[int] = None
    brand: Optional[str] = None
    insert_type: Optional[str] = None
    card_number: Optional[str] = None
    year: Optional[str] = None
    exclude: Optional[str] = None
    include_auctions: bool = False
    catch_misspellings: bool = False


@app.post("/alerts/lint")
async def lint_alert(req: LintRequest, me: User = Depends(current_user)):
    """Live sanity-check a draft alert against eBay before it's saved, so the user
    sees DEAD / NARROW / too-broad problems and spelling fixes up front. ~1 eBay call."""
    from types import SimpleNamespace
    from alert_filters import build_query, _ebay_keywords, detect_sport, classify_health
    from scrapers.ebay_scraper import search_cards

    s = SimpleNamespace(
        query=(req.query or ""), sport=(req.sport if req.sport and req.sport != "Any" else None),
        year=req.year, brand=req.brand, insert_type=req.insert_type, card_number=req.card_number,
        numbered_to=req.numbered_to, exclude=req.exclude,
        catch_misspellings=bool(req.catch_misspellings), min_price=req.min_price,
        include_auctions=bool(req.include_auctions), source="ebay",
    )
    full = build_query(s)
    if not full.strip():
        return {"status": "empty", "messages": ["Enter a card or keywords to check."], "suggestions": [], "stats": {}}

    kw = _ebay_keywords(full)
    try:
        listings = await search_cards(kw, None, None, 40, bool(req.include_auctions), sport=detect_sport(full))
    except Exception:
        listings = []
    out = classify_health(s, listings)
    out["stats"]["keywords"] = kw
    return out


@app.post("/alerts/scan-health")
async def scan_my_alert_health(db: AsyncSession = Depends(get_db), me: User = Depends(current_user)):
    """Re-run the health check on all of the current user's active alerts now and
    store the verdicts (so the Alerts page badges refresh on demand)."""
    res = await db.execute(select(SavedSearch).where(
        SavedSearch.user_id == me.id, SavedSearch.active == True))
    searches = res.scalars().all()
    summary = await _scan_alert_health(db, searches)
    return {"scanned": len(searches), "summary": summary}


class SetMethodRequest(BaseModel):
    method: str  # "email", "sms", or "both"


@app.post("/alerts/set-all-method")
async def set_all_alert_method(req: SetMethodRequest, db: AsyncSession = Depends(get_db),
                               me: User = Depends(current_user)):
    """Bulk-set the delivery method on ALL of the current user's active alerts —
    e.g. switch everything to Email to cut the Twilio bill."""
    method = (req.method or "").lower()
    if method not in ("email", "sms", "both"):
        raise HTTPException(400, "method must be email, sms, or both")
    res = await db.execute(select(SavedSearch).where(
        SavedSearch.user_id == me.id, SavedSearch.active == True))
    rows = res.scalars().all()
    for s in rows:
        s.alert_method = method
    await db.commit()
    return {"updated": len(rows), "method": method}


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


class FolderAssistRequest(BaseModel):
    folder: str
    instruction: str


@app.post("/saved-searches/folder-assistant")
async def folder_assistant(req: FolderAssistRequest, db: AsyncSession = Depends(get_db),
                           me: User = Depends(current_user)):
    """AI helper for a folder: turn a natural-language request into edits across
    the user's alerts (rename folder, move/delete, set price/interval/numbered)."""
    folder = (req.folder or "").strip()
    if not req.instruction or not req.instruction.strip():
        raise HTTPException(400, "Tell the assistant what to do")

    result = await db.execute(select(SavedSearch).where(
        SavedSearch.user_id == me.id, SavedSearch.active == True))
    mine = result.scalars().all()
    by_id = {s.id: s for s in mine}

    import ai
    payload = [{"id": s.id, "query": s.query, "folder": s.folder, "min_price": s.min_price,
                "numbered_to": s.numbered_to, "check_interval_minutes": s.check_interval_minutes}
               for s in mine]
    try:
        if folder:
            plan = ai.plan_folder_actions(folder, payload, req.instruction.strip())
        else:
            plan = ai.plan_organize_actions(payload, req.instruction.strip())  # whole-list organize
    except Exception as e:
        raise HTTPException(502, f"AI assistant failed: {e}")

    _ALERT_EDITABLE = {"query", "sport", "brand", "insert_type", "card_number", "year",
                       "exclude", "min_price", "max_price", "numbered_to",
                       "check_interval_minutes", "source", "folder", "alert_method"}

    applied = []
    for a in plan.get("actions", []):
        op = a.get("op")
        try:
            if op == "update":
                s = by_id.get(a.get("id"))
                if not s:
                    continue
                flds = a.get("fields") or {}
                changed = []
                for k, v in flds.items():
                    if k not in _ALERT_EDITABLE:
                        continue
                    if k == "source" and v not in ("ebay", "auction"):
                        continue
                    setattr(s, k, (v if v != "" else None))
                    changed.append(k)
                if changed:
                    s.last_checked_at = None  # re-baseline after filter edits
                    applied.append(f"Updated {', '.join(changed)} on '{s.query}'")
            elif op == "rename_folder":
                to = (a.get("to") or "").strip() or None
                n = 0
                for s in mine:
                    if (s.folder or "").strip() == folder:
                        s.folder = to; n += 1
                applied.append(f"Renamed folder to '{to}' ({n} alerts)")
            elif op in ("set_folder", "set_min_price", "set_interval", "set_numbered_to", "delete"):
                s = by_id.get(a.get("id"))
                if not s:
                    continue
                if op == "set_folder":
                    s.folder = (a.get("folder") or "").strip() or None
                    applied.append(f"Moved '{s.query}' to '{s.folder or 'Ungrouped'}'")
                elif op == "set_min_price":
                    s.min_price = a.get("value")
                    applied.append(f"Set min price ${s.min_price} on '{s.query}'")
                elif op == "set_interval":
                    s.check_interval_minutes = float(a.get("minutes") or 60)
                    s.last_checked_at = None
                    applied.append(f"Set interval {int(s.check_interval_minutes)}m on '{s.query}'")
                elif op == "set_numbered_to":
                    s.numbered_to = a.get("value")
                    applied.append(f"Set numbered /{s.numbered_to} on '{s.query}'")
                elif op == "delete":
                    s.active = False
                    applied.append(f"Removed '{s.query}'")
        except Exception:
            continue

    await db.commit()
    return {"summary": plan.get("summary", ""), "applied": applied}


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


# --- Global alerts on/off switch ---

class PauseRequest(BaseModel):
    paused: bool


@app.get("/alerts/pause-state")
async def get_pause_state(me: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    from database import AppFlag
    f = await db.get(AppFlag, "alerts_paused")
    return {"paused": bool(f and f.value == "yes")}


@app.post("/alerts/pause-state")
async def set_pause_state(req: PauseRequest, me: User = Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    """Turn all alert checking on/off (global switch)."""
    from database import AppFlag
    f = await db.get(AppFlag, "alerts_paused")
    val = "yes" if req.paused else "no"
    if not f:
        db.add(AppFlag(key="alerts_paused", value=val))
    else:
        f.value = val
    await db.commit()
    return {"paused": req.paused}


_ALERT_INTERVAL_S = 15 * 60  # scheduler heartbeat
_alert_run = {"running": False, "next_run": None, "last_run": None}


@app.get("/run-alert-check")
@app.post("/run-alert-check")
async def run_alert_check(
    authorization: str = Header(None),
    x_auth_token: str = Header(None),
    x_cron_token: str = Header(None),
    token: str = "",
    db: AsyncSession = Depends(get_db),
):
    """Kick off an alert check in the background and return immediately, so the
    pinging scheduler never times out on a long (85-alert) run. Guards against
    overlapping runs.

    Accepts either a signed-in user or a CRON_TOKEN. The free-tier web service
    sleeps when idle, and a sleeping service runs no scheduler loop, so an
    external pinger has to be able to reach this without a session."""
    cron_token = os.getenv("CRON_TOKEN", "")
    supplied = x_cron_token or token
    if not (cron_token and supplied and _secrets.compare_digest(supplied, cron_token)):
        await current_user(authorization=authorization, x_auth_token=x_auth_token, db=db)
    from database import AppFlag, AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        pause = await db.get(AppFlag, "alerts_paused")
        if pause and pause.value == "yes":
            return {"paused": True}
    if _alert_run["running"]:
        return {"status": "already running"}
    _alert_run["running"] = True
    # Keep a reference — the event loop only weakly references tasks, so an
    # unreferenced create_task can be garbage-collected before it finishes.
    _alert_run["task"] = asyncio.create_task(_alert_check_bg())
    return {"status": "started"}


async def _alert_check_bg():
    from database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            await _do_alert_check(db)
    except Exception as e:
        print(f"alert-check background error: {e}")
    finally:
        _alert_run["running"] = False


async def _check_watched_auctions(db: AsyncSession):
    """Text the user ~30 min before a watched auction ends (once per auction)."""
    from datetime import datetime, timezone, timedelta
    from alerts import send_sms
    now = datetime.now(timezone.utc)
    res = await db.execute(select(WatchedAuction).where(WatchedAuction.notified == False))  # noqa: E712
    for w in res.scalars().all():
        if not w.end_date:
            continue
        try:
            end = datetime.fromisoformat(str(w.end_date).replace("Z", "+00:00"))
        except Exception:
            continue
        if end <= now:
            w.notified = True  # already ended — don't notify
            continue
        if (end - now) <= timedelta(minutes=35):  # within ~30 min of ending
            user = await db.get(User, w.user_id)
            phone = getattr(user, "phone", None) if user else None
            if phone:
                mins = max(1, int((end - now).total_seconds() / 60))
                body = (f"⏰ Auction ending in ~{mins} min: {(w.title or '')[:70]} — "
                        f"current bid ${w.price or 0:,.0f}\n{w.listing_url or ''}")
                send_sms(phone, body)
            w.notified = True
    await db.commit()


def _pacific_day_str() -> str:
    """Approx Pacific calendar day (UTC-8), matching the eBay budget day. Used to
    detect the midnight-Pacific rollover for the daily task reset."""
    from datetime import datetime, timedelta
    return (datetime.utcnow() - timedelta(hours=8)).strftime("%Y-%m-%d")


async def _send_daily_digests(db: AsyncSession) -> int:
    """At the first heartbeat of each new Pacific day, send each digest-enabled
    user a one-shot summary of the PREVIOUS day's alert finds. Real-time pings
    are unaffected — this is additive. Returns how many digests were sent."""
    from database import AppFlag
    today = _pacific_day_str()
    flag = await db.get(AppFlag, "digest_sent_day")
    if flag and flag.value == today:
        return 0  # already sent for today

    # Previous Pacific day window (finds sent during it), in UTC terms.
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    day_start_utc = datetime.strptime(today, "%Y-%m-%d") + timedelta(hours=8)  # 00:00 Pacific -> UTC
    prev_start = day_start_utc - timedelta(days=1)
    prev_label = (now - timedelta(hours=8) - timedelta(days=1)).strftime("%b %-d")

    users = (await db.execute(select(User).where(User.digest == True))).scalars().all()
    sent = 0
    for u in users:
        if not (u.email or u.phone):
            continue
        res = await db.execute(select(SentAlert).where(
            SentAlert.user_id == u.id,
            SentAlert.sent_at >= prev_start, SentAlert.sent_at < day_start_utc)
            .order_by(SentAlert.pct_vs_market.asc().nulls_last(), SentAlert.price.desc()))
        finds = [{"title": s.title, "price": s.price, "pct_vs_market": s.pct_vs_market,
                  "is_auction": bool(s.is_auction), "listing_url": s.listing_url}
                 for s in res.scalars().all()]
        if finds:
            send_digest(u, finds, day_label=prev_label, method=u.alert_method)
            sent += 1

    if flag:
        flag.value = today
    else:
        db.add(AppFlag(key="digest_sent_day", value=today))
    await db.commit()
    if sent:
        print(f"Daily digests sent: {sent} for finds on {prev_label}")
    return sent


async def _reset_tasks_if_new_day(db: AsyncSession):
    """At the first heartbeat of each new Pacific day, uncheck every task and all
    of its checklist/line items so recurring daily lists start fresh. Task text,
    assignments, and AI chat are preserved; nothing is deleted."""
    from database import AppFlag
    today = _pacific_day_str()
    flag = await db.get(AppFlag, "tasks_reset_day")
    if flag and flag.value == today:
        return  # already reset for today
    res = await db.execute(select(Task))
    for t in res.scalars().all():
        t.done = False
        t.completed_at = None
        if t.checklist:
            try:
                items = json.loads(t.checklist)
                for it in items:
                    it["done"] = False
                t.checklist = json.dumps(items)
            except Exception:
                pass
    if flag:
        flag.value = today
    else:
        db.add(AppFlag(key="tasks_reset_day", value=today))
    await db.commit()
    print(f"Daily task reset done for {today} (Pacific)")


async def _scan_alert_health(db: AsyncSession, searches) -> dict:
    """Run each eBay alert against live results and store an ok/narrow/dead verdict.
    ~1 eBay call per unique search; results are cached so duplicates are cheap."""
    from alert_filters import build_query, _ebay_keywords, detect_sport, classify_health
    from scrapers.ebay_scraper import search_cards
    now = datetime.utcnow()
    summary = {"ok": 0, "narrow": 0, "dead": 0, "skipped": 0}
    for s in searches:
        if (getattr(s, "source", None) or "ebay") != "ebay":
            summary["skipped"] += 1
            continue
        full = build_query(s)
        if not full.strip():
            summary["skipped"] += 1
            continue
        try:
            listings = await search_cards(_ebay_keywords(full), None, None, 40,
                                          bool(getattr(s, "include_auctions", False)), sport=detect_sport(full))
        except Exception:
            summary["skipped"] += 1
            continue
        res = classify_health(s, listings)
        s.health_status = res["status"]
        s.health_detail = (res["messages"][0] if res["messages"] else "")[:300]
        s.health_checked_at = now
        summary[res["status"]] = summary.get(res["status"], 0) + 1
    await db.commit()
    return summary


async def _scan_health_if_new_day(db: AsyncSession):
    """Once per Pacific day, refresh every active alert's health badge."""
    from database import AppFlag
    today = _pacific_day_str()
    flag = await db.get(AppFlag, "alert_health_day")
    if flag and flag.value == today:
        return
    res = await db.execute(select(SavedSearch).where(SavedSearch.active == True))
    summary = await _scan_alert_health(db, res.scalars().all())
    if flag:
        flag.value = today
    else:
        db.add(AppFlag(key="alert_health_day", value=today))
    await db.commit()
    print(f"Daily alert-health scan for {today}: {summary}")


async def _alert_scheduler_loop():
    """Run the alert check every 15 min from inside the web app, so freshness
    doesn't depend on an external cron. Honors the pause flag + overlap guard."""
    from database import AsyncSessionLocal, AppFlag
    await asyncio.sleep(25)  # let startup settle
    while True:
        _alert_run["last_run"] = _time.time()
        try:
            # Reset the shared Tasks board at the midnight-Pacific rollover.
            try:
                async with AsyncSessionLocal() as db:
                    await _reset_tasks_if_new_day(db)
            except Exception as e:
                print(f"daily task reset error: {e}")
            # Send each opted-in user their once-a-day digest of yesterday's finds.
            try:
                async with AsyncSessionLocal() as db:
                    await _send_daily_digests(db)
            except Exception as e:
                print(f"daily digest error: {e}")
            # Refresh alert-health badges once per Pacific day.
            try:
                async with AsyncSessionLocal() as db:
                    await _scan_health_if_new_day(db)
            except Exception as e:
                print(f"daily alert-health scan error: {e}")
            # Snapshot tracked wax boxes once per Pacific day (builds the dated ladder).
            try:
                async with AsyncSessionLocal() as db:
                    await _snapshot_wax_if_new_day(db)
            except Exception as e:
                print(f"daily wax snapshot error: {e}")
            # Auction end-reminders run regardless of the alert pause (user opted in per-auction).
            try:
                async with AsyncSessionLocal() as db:
                    await _check_watched_auctions(db)
            except Exception as e:
                print(f"watched-auction check error: {e}")
            async with AsyncSessionLocal() as db:
                pause = await db.get(AppFlag, "alerts_paused")
                paused = bool(pause and pause.value == "yes")
            if not paused and not _alert_run["running"]:
                _alert_run["running"] = True
                try:
                    async with AsyncSessionLocal() as db:
                        await _do_alert_check(db)
                except Exception as e:
                    print(f"scheduler alert-check error: {e}")
                finally:
                    _alert_run["running"] = False
        except Exception as e:
            print(f"alert scheduler loop error: {e}")
        _alert_run["next_run"] = _time.time() + _ALERT_INTERVAL_S
        await asyncio.sleep(_ALERT_INTERVAL_S)


async def _do_alert_check(db: AsyncSession):
    """Check all active saved searches and send alerts for newly-listed cards."""
    from datetime import datetime

    result = await db.execute(select(SavedSearch).where(SavedSearch.active == True))
    searches = result.scalars().all()

    # Runs 24/7. Budget eBay calls by the number of UNIQUE searches, not the
    # number of alerts: alerts that share the same eBay query (same cleaned
    # keywords + auction setting) are served from one cached call per 10-min
    # cycle, so they cost a single API call between them. Counting unique
    # searches lets overlapping alerts check far more often within the same
    # daily budget. The auto-stretch floor is then the fastest safe interval.
    from alert_filters import min_interval_for, build_query, _ebay_keywords

    def _search_key(s):
        if (getattr(s, "source", None) or "ebay") != "ebay":
            return ("nonebay", s.id)  # goldin/auction alerts each cost their own call
        return (_ebay_keywords(build_query(s)), bool(getattr(s, "include_auctions", False)))

    unique_searches = len({_search_key(s) for s in searches})
    # Check every card at most once an hour to conserve the eBay daily budget.
    # If there are ever so many searches that hourly would exceed the budget,
    # min_interval_for backs off further (slower than hourly), never faster.
    floor_interval = max(min_interval_for(max(unique_searches, 1)), 60)

    checked = 0
    alerts_sent = 0

    for search in searches:
        # Check at the fastest budget-safe rate (the floor). The 15-min scheduler
        # heartbeat naturally caps the real rate, so when the floor is small the
        # effective rate is ~15 min — as soon as possible without exhausting quota.
        if search.last_checked_at:
            elapsed = (datetime.utcnow() - search.last_checked_at).total_seconds() / 60
            if elapsed < floor_interval:
                continue

        from alert_filters import build_query, gather_alert_listings, passes_deal_threshold, LISTED_MIN_PRICE
        # First check ever? Seed the baseline silently (don't alert on existing listings)
        is_first_check = search.last_checked_at is None
        try:
            src, listings = await gather_alert_listings(search)
        except Exception:
            continue
        search.last_checked_at = datetime.utcnow()
        if listings:
            search.last_match_at = datetime.utcnow()  # this alert is alive (matched something)
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
                # Auctions: only alert if the card's market (avg sold price) is over
                # $1000 — the live bid is meaningless, so judge by what it really sells for.
                if listing.get("is_auction") and (analysis.get("avg_sold_price") or 0) < LISTED_MIN_PRICE:
                    continue
                if not passes_deal_threshold(search, src, analysis):
                    continue  # not enough of a discount to alert on
                send_alert(user, listing, analysis, method=search.alert_method, alert_label=search.query)
                search.alerts_sent_count = (search.alerts_sent_count or 0) + 1
                db.add(SentAlert(
                    user_id=user.id, search_id=search.id, query=search.query,
                    title=listing.get("title"), price=listing.get("price"),
                    listing_url=listing.get("listing_url"), image_url=listing.get("image_url"),
                    verdict=analysis.get("verdict"), pct_vs_market=analysis.get("pct_vs_market"),
                    is_auction=bool(listing.get("is_auction")),
                ))
                alerts_sent += 1

    await db.commit()

    # Track alerts sent per day (Pacific) so we can report the daily count.
    if alerts_sent:
        from database import AppFlag
        from datetime import timedelta
        day = (datetime.utcnow() - timedelta(hours=7)).strftime("%Y-%m-%d")
        flag = await db.get(AppFlag, "alerts_sent_log")
        log = json.loads(flag.value) if flag and flag.value else {}
        log[day] = log.get(day, 0) + alerts_sent
        log = dict(sorted(log.items())[-14:])  # keep last 14 days
        if flag:
            flag.value = json.dumps(log)
        else:
            db.add(AppFlag(key="alerts_sent_log", value=json.dumps(log)))
        await db.commit()

    # PSA pop watches: alert when a watched cert's population increases
    pop_alerts = await _check_pop_watches(db)

    # Seller watches: alert when a watched eBay seller posts new listings
    seller_alerts = await _check_seller_watches(db)

    # Scheduled broadcasts: fire any whose send time has arrived
    scheduled_sent = await _send_due_broadcasts(db)

    # Release calendar: auto-pull new upcoming releases (daily) + notify on new ones
    new_releases = await _maybe_refresh_releases(db)
    # Release calendar: remind ahead of a product's street date
    release_reminders = await _check_release_calendar(db)

    # One-time: notify when Twilio toll-free SMS verification gets approved
    await _check_tollfree_approval(db)

    # Periodically pull the latest from the Google Sheet (throttled to ~15 min)
    synced = await _maybe_sync_sheet(db)

    print(f"alert-check done: checked={checked} sent={alerts_sent} pop={pop_alerts} sellers={seller_alerts} releases={release_reminders} new_releases={new_releases} synced={synced}")


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
                "26buys@gmail.com",
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

SHOPS_PASSWORD = os.getenv("SHOPS_PASSWORD", "")  # no weak default — fail closed if unset
# Separate secret for /admin/* (read-all-users data). Falls back to the shops password
# only until you set ADMIN_KEY on the server, so admin access can be split off.
ADMIN_KEY = os.getenv("ADMIN_KEY", "") or SHOPS_PASSWORD


def _key_ok(provided: str, expected: str) -> bool:
    """Constant-time secret compare; never passes on an empty/unset expected secret."""
    return bool(expected) and bool(provided) and _secrets.compare_digest(provided, expected)


def require_shop_access(x_shops_password: Optional[str] = Header(None)):
    """Single shared-password gate for all shop routes."""
    if not _key_ok(x_shops_password or "", SHOPS_PASSWORD):
        raise HTTPException(401, "Invalid or missing access password")
    return True


def require_admin(x_admin_key: Optional[str] = Header(None), key: str = ""):
    """Gate for /admin/* endpoints (they can read any user's data). Prefer the
    X-Admin-Key header; ?key= still works for backward compat but is deprecated
    (it leaks the secret into URLs/logs — switch to the header)."""
    if not _key_ok((x_admin_key or key) or "", ADMIN_KEY):
        raise HTTPException(401, "Invalid admin key")
    return True


# --- Admin search recovery/edit (shop-gated; defined after require_shop_access) ---

@app.get("/admin/deleted-searches")
async def admin_deleted_searches(email: Optional[str] = None, db: AsyncSession = Depends(get_db),
                                 _: bool = Depends(require_shop_access)):
    """Recovery helper: list soft-deleted (inactive) saved searches so an
    accidentally-deleted alert can be restored. Optionally filter by user email."""
    q = select(SavedSearch).where(SavedSearch.active == False)
    if email:
        ur = await db.execute(select(User).where(func.lower(User.email) == email.strip().lower()))
        u = ur.scalar_one_or_none()
        if not u:
            return []
        q = q.where(SavedSearch.user_id == u.id)
    res = await db.execute(q.order_by(SavedSearch.id.desc()))
    return [{"id": s.id, "user_id": s.user_id, "query": s.query, "folder": s.folder,
             "brand": s.brand, "numbered_to": s.numbered_to, "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in res.scalars().all()]


class RestoreSearchRequest(BaseModel):
    search_id: int


@app.post("/admin/restore-search")
async def admin_restore_search(req: RestoreSearchRequest, db: AsyncSession = Depends(get_db),
                               _: bool = Depends(require_shop_access)):
    """Reactivate a soft-deleted saved search (undo an accidental delete)."""
    s = await db.get(SavedSearch, req.search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    s.active = True
    s.last_checked_at = None  # re-baseline so it doesn't blast old listings
    await db.commit()
    return {"restored": True, "id": s.id, "query": s.query}


@app.get("/admin/active-searches")
async def admin_active_searches(email: str, db: AsyncSession = Depends(get_db),
                                _: bool = Depends(require_shop_access)):
    """List a user's active saved searches (shop-gated helper for admin edits)."""
    ur = await db.execute(select(User).where(func.lower(User.email) == email.strip().lower()))
    u = ur.scalar_one_or_none()
    if not u:
        return []
    res = await db.execute(select(SavedSearch).where(
        SavedSearch.user_id == u.id, SavedSearch.active == True).order_by(SavedSearch.id))
    return [{"id": s.id, "query": s.query, "folder": s.folder, "numbered_to": s.numbered_to,
             "brand": s.brand} for s in res.scalars().all()]


class AdminEditSearchRequest(BaseModel):
    search_id: int
    numbered_to: Optional[int] = None
    query: Optional[str] = None
    exclude: Optional[str] = None
    brand: Optional[str] = None
    active: Optional[bool] = None   # False = soft-delete this search


@app.post("/admin/edit-search")
async def admin_edit_search(req: AdminEditSearchRequest, db: AsyncSession = Depends(get_db),
                            _: bool = Depends(require_shop_access)):
    """Shop-gated edit of a saved search's filter fields (only fields provided).
    Pass active=False to soft-delete (e.g. remove a duplicate)."""
    s = await db.get(SavedSearch, req.search_id)
    if not s:
        raise HTTPException(404, "Search not found")
    if req.numbered_to is not None: s.numbered_to = req.numbered_to
    if req.query is not None: s.query = req.query.strip()
    if req.exclude is not None: s.exclude = _blank(req.exclude)
    if req.brand is not None: s.brand = _blank(req.brand)
    if req.active is not None: s.active = req.active
    s.last_checked_at = None  # re-baseline after filter change
    await db.commit()
    return {"id": s.id, "query": s.query, "numbered_to": s.numbered_to, "active": s.active}


# Single owner account allowed to see budget/financial counters (eBay usage, Twilio balance).
OWNER_EMAIL = norm_email(os.getenv("OWNER_EMAIL", "26buys@gmail.com"))


async def require_owner(me: User = Depends(current_user)):
    """Restrict an endpoint to the one owner account."""
    if norm_email(me.email) != OWNER_EMAIL:
        raise HTTPException(403, "Not authorized")
    return me


@app.post("/admin/alerts-pause")
async def admin_alerts_pause(paused: bool = True, _: bool = Depends(require_admin),
                             db: AsyncSession = Depends(get_db)):
    """Global pause/resume for all alert checks. Gated by the admin key."""
    from database import AppFlag
    f = await db.get(AppFlag, "alerts_paused")
    val = "yes" if paused else "no"
    if not f:
        db.add(AppFlag(key="alerts_paused", value=val))
    else:
        f.value = val
    await db.commit()
    return {"alerts_paused": paused}


@app.get("/admin/sent-alerts")
async def admin_sent_alerts(email: str, limit: int = 50, days: int = 7,
                            _: bool = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Recent alert finds (the cards actually emailed/texted) for a user."""
    from datetime import timedelta
    r = await db.execute(select(User).where(func.lower(User.email) == norm_email(email)))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(404, f"No account for {email}")
    cutoff = datetime.utcnow() - timedelta(days=days)
    res = await db.execute(
        select(SentAlert).where(SentAlert.user_id == user.id, SentAlert.sent_at >= cutoff)
        .order_by(SentAlert.sent_at.desc()).limit(min(limit, 200)))
    rows = res.scalars().all()
    return {"count": len(rows), "finds": [{
        "sent_at": s.sent_at.isoformat() if s.sent_at else None,
        "title": s.title, "price": s.price, "is_auction": s.is_auction,
        "pct_vs_market": s.pct_vs_market, "alert": s.query, "listing_url": s.listing_url,
    } for s in rows]}


@app.get("/admin/alert-report")
async def admin_alert_report(email: str, live: bool = False, _: bool = Depends(require_admin),
                             db: AsyncSession = Depends(get_db)):
    """Health report for a user's alerts: lifetime alerts sent, last time each
    matched, and (live=true) a fresh eBay scan flagging DEAD alerts (keywords
    that return nothing / never match) vs NARROW (matches exist but under $2000).
    live=true uses ~1 eBay call per unique search."""
    from alert_filters import build_query, _ebay_keywords, passes_filters, detect_sport, LISTED_MIN_PRICE
    r = await db.execute(select(User).where(func.lower(User.email) == norm_email(email)))
    user = r.scalar_one_or_none()
    if not user:
        raise HTTPException(404, f"No account for {email}")
    res = await db.execute(select(SavedSearch).where(
        SavedSearch.user_id == user.id, SavedSearch.active == True).order_by(SavedSearch.id))
    now = datetime.utcnow()
    rows = []
    for s in res.scalars().all():
        days = round((now - s.last_match_at).total_seconds() / 86400, 1) if s.last_match_at else None
        info = {"id": s.id, "query": s.query, "alerts_sent": s.alerts_sent_count or 0,
                "last_match_days_ago": days, "include_auctions": bool(s.include_auctions)}
        if live and (getattr(s, "source", None) or "ebay") == "ebay":
            listings = await search_cards(_ebay_keywords(build_query(s)), None, None, 50,
                                          bool(s.include_auctions), sport=detect_sport(build_query(s)))
            matched = [l for l in listings if passes_filters(s, l)]
            floor = max(s.min_price or 0, LISTED_MIN_PRICE)
            priced = [l for l in matched if l.get("is_auction") or (l.get("price") or 0) >= floor]
            info["ebay_results"] = len(listings)
            info["word_matches"] = len(matched)
            info["priced_matches"] = len(priced)
            if not listings:
                info["status"] = "DEAD — eBay returns nothing for these keywords (check spelling/terms)"
            elif not matched:
                info["status"] = "DEAD — results exist but none contain all your words"
            elif not priced:
                info["status"] = "NARROW — matches exist but none clear the $1000 floor"
            else:
                info["status"] = "ok"
        rows.append(info)
    summary = {}
    if live:
        for r2 in rows:
            st = (r2.get("status") or "").split(" ")[0].lower() or "n/a"
            summary[st] = summary.get(st, 0) + 1
    rows.sort(key=lambda x: (0 if str(x.get("status", "")).startswith("DEAD") else
                             1 if str(x.get("status", "")).startswith("NARROW") else 2,
                             -(x["alerts_sent"])))
    return {"total": len(rows), "summary": summary, "alerts": rows}


# --- Broadcast: blast an SMS to a pasted list of phone numbers ---

class AssigneeItem(BaseModel):
    name: Optional[str] = None
    phone: str


class BroadcastRequest(BaseModel):
    recipients: str  # pasted list of phone numbers
    message: str
    assigned_to: Optional[str] = None      # (legacy single) teammate name
    assignee_phone: Optional[str] = None   # (legacy single) teammate phone
    assignees: Optional[list[AssigneeItem]] = None  # one or more follow-up teammates
    save_as_group: Optional[str] = None    # if set, save these recipients as a named group
    image: Optional[str] = None            # data URL (data:image/...;base64,...) to send as MMS


# Short-lived in-memory store for broadcast MMS images. Twilio fetches the media
# within seconds of send, so ephemeral storage is fine (and survives the single
# uvicorn worker). Keyed by a random id; entries expire after ~15 min.
_broadcast_media: dict = {}


def _stash_broadcast_image(data_url: str):
    """Decode a data URL, stash the bytes, return (media_id, content_type) or None."""
    import base64, re as _re, secrets as _secrets, time as _t
    m = _re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", (data_url or "").strip(), _re.DOTALL)
    if not m:
        return None
    ctype, b64 = m.group(1), m.group(2)
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None
    if len(raw) > 5 * 1024 * 1024:  # 5MB cap (Twilio MMS media limit)
        return None
    # prune expired
    now = _t.time()
    for k in [k for k, v in _broadcast_media.items() if v[2] < now]:
        _broadcast_media.pop(k, None)
    mid = _secrets.token_urlsafe(12)
    _broadcast_media[mid] = (ctype, raw, now + 15 * 60)
    return mid, ctype


@app.get("/broadcast/media/{mid}")
async def broadcast_media(mid: str):
    """Serve a stashed broadcast image (public — Twilio must fetch it, no auth)."""
    import time as _t
    ent = _broadcast_media.get(mid)
    if not ent or ent[2] < _t.time():
        raise HTTPException(404, "media expired")
    return Response(content=ent[1], media_type=ent[0])


def _parse_recipients(raw: str):
    """Split a pasted blob into (phones, skipped, names). Phones are normalized to
    E.164 (US-default +1) for Twilio. A line like "Uriel 8187409787" also yields a
    name -> {phone: name} so the Inbox conversation can show the person's name."""
    import re
    phones, skipped, names = [], [], {}
    # Split on line/comma/semicolon/tab — NOT spaces, so "(212) 555 1234" stays intact.
    for tok in re.split(r"[\n\r,;\t]+", raw or ""):
        tok = tok.strip()
        if not tok:
            continue
        digits = re.sub(r"\D", "", tok)
        phone = None
        if len(digits) == 10:
            phone = "+1" + digits
        elif len(digits) == 11 and digits.startswith("1"):
            phone = "+" + digits
        elif len(digits) >= 11:
            phone = "+" + digits
        if not phone:
            skipped.append(tok)
            continue
        phones.append(phone)
        # Whatever letters remain on the line (after removing the number) = the name.
        nm = re.sub(r"[\d()+\-.]", "", tok)
        nm = re.sub(r"\s+", " ", nm).strip(" -–—:•")
        if nm and phone not in names:
            names[phone] = nm[:80]
    return list(dict.fromkeys(phones)), skipped, names


def _one_phone(raw):
    phones, _, _ = _parse_recipients(raw or "")
    return phones[0] if phones else None


# Reserved conversation key for the single consolidated broadcast thread (not a real number).
BROADCAST_THREAD = "__broadcast__"


async def _execute_broadcast(db, *, recipients: str, message: str, image: Optional[str],
                             assignees: list, save_as_group: Optional[str], base_url: str) -> dict:
    """Core broadcast send — shared by the live /broadcast endpoint and the scheduler.
    Sends the text/MMS to every parsed number, keeps per-person conversations for
    reply routing, logs the blast to the 📣 Broadcasts thread, and optionally saves
    the recipients as a reusable group."""
    from alerts import send_sms
    body = (message or "").strip()
    # An image alone (no text) is a valid MMS, so only require one of them.
    if not body and not image:
        raise HTTPException(400, "Message is empty.")

    # Stash the image and build a public URL Twilio can fetch (MMS).
    media_url = None
    if image:
        stash = _stash_broadcast_image(image)
        if stash:
            media_url = f"{base_url.rstrip('/')}/broadcast/media/{stash[0]}"
    phones, skipped, rcpt_names = _parse_recipients(recipients)
    if not phones:
        raise HTTPException(400, "No valid phone numbers found.")
    now = datetime.utcnow()
    ss = sf = 0
    for p in phones:
        if send_sms(p, body, media_url=media_url):  # send exactly what's typed (Twilio still auto-honors STOP)
            ss += 1
            # Keep a per-person conversation so a REPLY still lands in its own thread
            # and forwards to the assigned teammate — but don't log the outbound or
            # bump it here. The blast itself is shown as ONE thread (below), so we
            # leave these threads out of the Inbox list until the person replies.
            conv = await db.get(SmsConversation, p)
            if not conv:
                conv = SmsConversation(phone=p, created_at=now)
                db.add(conv)
            # Save the person's name so the Inbox shows it (not just the number).
            nm = rcpt_names.get(p)
            if not nm:  # fall back to a saved contact's name for this number
                ct = (await db.execute(select(BroadcastContact).where(
                    BroadcastContact.phone == p, BroadcastContact.name.isnot(None)).limit(1))).scalar_one_or_none()
                nm = ct.name if ct else None
            if nm and not conv.name:
                conv.name = nm
            _apply_assignees(conv, assignees)
        else:
            sf += 1

    # Log the whole blast as a SINGLE outbound entry in one "📣 Broadcasts" thread,
    # so the Inbox shows broadcasts as one conversation instead of one per recipient.
    if ss:
        bconv = await db.get(SmsConversation, BROADCAST_THREAD)
        if not bconv:
            bconv = SmsConversation(phone=BROADCAST_THREAD, name="📣 Broadcasts", created_at=now)
            db.add(bconv)
        logged = body or ("📷 Photo" if media_url else "")
        n_txt = f"{ss} recipient" + ("" if ss == 1 else "s")
        bconv.name = "📣 Broadcasts"
        bconv.last_at = now
        bconv.last_preview = (f"{logged}  →  {n_txt}")[:120]
        bconv.last_direction = "out"
        db.add(SmsMessage(phone=BROADCAST_THREAD, direction="out",
                          body=f"{logged}\n\n— sent to {n_txt}", sender="broadcast", created_at=now))
    # Save the recipients as a reusable group for future targeted messages.
    saved_group = None
    gname = (save_as_group or "").strip()
    if gname:
        res = await db.execute(select(BroadcastGroup).where(func.lower(BroadcastGroup.name) == gname.lower()))
        grp = res.scalar_one_or_none()
        if not grp:
            grp = BroadcastGroup(name=gname)
            db.add(grp); await db.flush()
        existing = {c.phone for c in (await db.execute(
            select(BroadcastContact).where(BroadcastContact.group_id == grp.id))).scalars().all()}
        added = 0
        for p in phones:
            if p not in existing:
                db.add(BroadcastContact(group_id=grp.id, phone=p, name=rcpt_names.get(p))); existing.add(p); added += 1
        # Log what was sent to this group so the history shows what we contacted them about.
        db.add(BroadcastLog(group_id=grp.id, message=body, sent_count=ss))
        saved_group = {"id": grp.id, "name": grp.name, "added": added, "total": len(existing)}

    await db.commit()

    return {"sms": {"sent": ss, "failed": sf, "total": len(phones)}, "skipped": skipped,
            "assignees": assignees, "saved_group": saved_group}


def _resolve_assignees(req: "BroadcastRequest") -> list:
    """Follow-up team: prefer the multi-assignee list, else the legacy single field."""
    if req.assignees:
        return [{"name": a.name, "phone": a.phone} for a in req.assignees]
    if req.assignee_phone:
        return [{"name": req.assigned_to, "phone": req.assignee_phone}]
    return []


@app.post("/broadcast")
async def broadcast(req: BroadcastRequest, request: Request, db: AsyncSession = Depends(get_db),
                    _: bool = Depends(require_shop_access)):
    """Send one text to a pasted list. If a follow-up teammate is assigned, each
    recipient becomes a tracked conversation whose replies route to that teammate.
    Pass image (data URL) to send it as an MMS picture."""
    return await _execute_broadcast(
        db, recipients=req.recipients, message=req.message, image=req.image,
        assignees=_resolve_assignees(req), save_as_group=req.save_as_group,
        base_url=str(request.base_url))


# --- Broadcast templates (reusable saved messages) ---

class TemplateCreate(BaseModel):
    name: str
    body: str


@app.get("/broadcast/templates")
async def list_broadcast_templates(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    res = await db.execute(select(BroadcastTemplate).order_by(BroadcastTemplate.name))
    return [{"id": t.id, "name": t.name, "body": t.body} for t in res.scalars().all()]


@app.post("/broadcast/templates")
async def create_broadcast_template(req: TemplateCreate, db: AsyncSession = Depends(get_db),
                                    _: bool = Depends(require_shop_access)):
    name, body = (req.name or "").strip(), (req.body or "").strip()
    if not name or not body:
        raise HTTPException(400, "Template needs a name and a message.")
    res = await db.execute(select(BroadcastTemplate).where(func.lower(BroadcastTemplate.name) == name.lower()))
    t = res.scalar_one_or_none()
    if t:
        t.body = body                       # overwrite an existing template of the same name
    else:
        t = BroadcastTemplate(name=name, body=body); db.add(t)
    await db.commit(); await db.refresh(t)
    return {"id": t.id, "name": t.name, "body": t.body}


@app.delete("/broadcast/templates/{tid}")
async def delete_broadcast_template(tid: int, db: AsyncSession = Depends(get_db),
                                    _: bool = Depends(require_shop_access)):
    t = await db.get(BroadcastTemplate, tid)
    if t:
        await db.delete(t); await db.commit()
    return {"ok": True}


# --- Scheduled broadcasts (send later, dispatched by run-alert-check) ---

class ScheduleCreate(BaseModel):
    recipients: str
    message: Optional[str] = ""
    image: Optional[str] = None
    assignees: Optional[list] = None        # [{name, phone}]
    assigned_to: Optional[str] = None
    assignee_phone: Optional[str] = None
    save_as_group: Optional[str] = None
    send_at: str                            # ISO datetime (UTC)


def _sched_dict(s: "ScheduledBroadcast") -> dict:
    phones, _, _ = _parse_recipients(s.recipients or "")
    return {"id": s.id, "message": s.message, "has_image": bool(s.image),
            "recipient_count": len(phones), "save_as_group": s.save_as_group,
            "send_at": s.send_at.isoformat() if s.send_at else None,
            "status": s.status, "result": s.result,
            "sent_at": s.sent_at.isoformat() if s.sent_at else None}


@app.get("/broadcast/scheduled")
async def list_scheduled_broadcasts(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    res = await db.execute(select(ScheduledBroadcast).order_by(ScheduledBroadcast.send_at))
    return [_sched_dict(s) for s in res.scalars().all()]


@app.post("/broadcast/schedule")
async def schedule_broadcast(req: ScheduleCreate, db: AsyncSession = Depends(get_db),
                             _: bool = Depends(require_shop_access)):
    body = (req.message or "").strip()
    if not body and not req.image:
        raise HTTPException(400, "Message is empty.")
    phones, _, _ = _parse_recipients(req.recipients)
    if not phones:
        raise HTTPException(400, "No valid phone numbers found.")
    try:
        when = datetime.fromisoformat((req.send_at or "").replace("Z", "+00:00"))
        if when.tzinfo:                      # normalize to naive UTC (DB stores UTC)
            when = when.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        raise HTTPException(400, "Invalid send time.")
    if when <= datetime.utcnow():
        raise HTTPException(400, "Pick a time in the future.")
    assignees = req.assignees or ([{"name": req.assigned_to, "phone": req.assignee_phone}] if req.assignee_phone else [])
    s = ScheduledBroadcast(recipients=req.recipients, message=body, image=req.image,
                           assignees=json.dumps(assignees), save_as_group=req.save_as_group,
                           send_at=when, status="pending")
    db.add(s); await db.commit(); await db.refresh(s)
    return _sched_dict(s)


@app.delete("/broadcast/scheduled/{sid}")
async def cancel_scheduled_broadcast(sid: int, db: AsyncSession = Depends(get_db),
                                     _: bool = Depends(require_shop_access)):
    s = await db.get(ScheduledBroadcast, sid)
    if s and s.status == "pending":
        s.status = "canceled"; await db.commit()
    return {"ok": True}


async def _send_due_broadcasts(db: AsyncSession) -> int:
    """Send any pending scheduled broadcasts whose time has arrived. Called from
    run_alert_check so it fires on the existing external cron cadence."""
    now = datetime.utcnow()
    res = await db.execute(select(ScheduledBroadcast).where(
        ScheduledBroadcast.status == "pending", ScheduledBroadcast.send_at <= now))
    due = res.scalars().all()
    sent = 0
    base_url = os.getenv("PUBLIC_BASE_URL", "https://card-finder-backend.onrender.com")
    for s in due:
        try:
            assignees = json.loads(s.assignees) if s.assignees else []
        except Exception:
            assignees = []
        try:
            out = await _execute_broadcast(db, recipients=s.recipients, message=s.message or "",
                                           image=s.image, assignees=assignees,
                                           save_as_group=s.save_as_group, base_url=base_url)
            s.status = "sent"
            s.result = f"{out['sms']['sent']} sent, {out['sms']['failed']} failed"
            sent += 1
        except Exception as e:
            s.status = "failed"; s.result = str(e)[:200]
            print(f"scheduled broadcast {s.id} failed: {e}")
        s.sent_at = now
        s.image = None                       # don't keep the image data URL after send
        await db.commit()
    return sent


@app.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    """One-screen ops metrics: alerts, broadcasts, inbox, audience, deals, portfolio."""
    from datetime import timedelta
    now = datetime.utcnow()
    wk = now - timedelta(days=7)

    async def n(q):
        return (await db.execute(q)).scalar() or 0

    active_searches = await n(select(func.count()).select_from(SavedSearch).where(SavedSearch.active == True))  # noqa: E712
    total_searches = await n(select(func.count()).select_from(SavedSearch))

    alerts_total = await n(select(func.count()).select_from(SentAlert))
    alerts_7d = await n(select(func.count()).select_from(SentAlert).where(SentAlert.sent_at >= wk))

    # Every consolidated broadcast message ends with "— sent to N recipient(s)";
    # count blasts and sum recipients straight from those (covers non-group blasts).
    import re as _re
    bmsgs = (await db.execute(select(SmsMessage.body).where(
        SmsMessage.phone == BROADCAST_THREAD, SmsMessage.sender == "broadcast"))).scalars().all()
    blasts = len(bmsgs)
    recipients_total = sum(int(mo.group(1)) for b in bmsgs
                           if (mo := _re.search(r"sent to (\d+) recipient", b or "")))
    last_blast = (await db.execute(select(func.max(SmsMessage.created_at)).where(
        SmsMessage.phone == BROADCAST_THREAD))).scalar()
    scheduled_pending = await n(select(func.count()).select_from(ScheduledBroadcast).where(
        ScheduledBroadcast.status == "pending"))

    convos = await n(select(func.count()).select_from(SmsConversation).where(
        SmsConversation.last_at.isnot(None), SmsConversation.phone != BROADCAST_THREAD))
    unread = await n(select(func.sum(SmsConversation.unread)))
    replies = await n(select(func.count()).select_from(SmsMessage).where(SmsMessage.direction == "in"))
    replies_7d = await n(select(func.count()).select_from(SmsMessage).where(
        SmsMessage.direction == "in", SmsMessage.created_at >= wk))

    groups_total = await n(select(func.count()).select_from(BroadcastGroup))
    contacts_total = await n(select(func.count()).select_from(BroadcastContact))
    named_contacts = await n(select(func.count()).select_from(BroadcastContact).where(BroadcastContact.name.isnot(None)))

    callers = await n(select(func.count(func.distinct(CallerNote.caller_name))))
    deals_count = await n(select(func.count()).select_from(CallerDeal))
    buy_total = await n(select(func.sum(CallerDeal.amount)).where(CallerDeal.kind == "buy"))
    sell_total = await n(select(func.sum(CallerDeal.amount)).where(CallerDeal.kind == "sell"))

    pf_cards = await n(select(func.sum(PortfolioCard.qty)))
    pf_value = (await db.execute(select(func.sum(PortfolioCard.market_value * PortfolioCard.qty)))).scalar() or 0
    pf_cost = (await db.execute(select(func.sum(PortfolioCard.paid * PortfolioCard.qty)))).scalar() or 0

    reply_rate = round(100 * replies / recipients_total, 1) if recipients_total else None

    return {
        "as_of": now.isoformat(),
        "searches": {"active": active_searches, "total": total_searches},
        "alerts": {"total": alerts_total, "last_7d": alerts_7d},
        "broadcasts": {"blasts": blasts, "recipients_total": recipients_total,
                       "last_at": last_blast.isoformat() if last_blast else None,
                       "scheduled_pending": scheduled_pending},
        "inbox": {"conversations": convos, "unread": unread, "replies": replies,
                  "replies_7d": replies_7d, "reply_rate_pct": reply_rate},
        "audience": {"groups": groups_total, "contacts": contacts_total, "named": named_contacts},
        "deals": {"logged": deals_count, "bought": round(buy_total, 2), "sold": round(sell_total, 2), "callers": callers},
        "portfolio": {"cards": pf_cards, "market_value": round(pf_value, 2),
                      "cost": round(pf_cost, 2), "pnl": round(pf_value - pf_cost, 2)},
    }


# --- Broadcast groups (reusable saved audiences) ---

async def _group_dict(db, g: BroadcastGroup) -> dict:
    cnt = len((await db.execute(select(BroadcastContact).where(BroadcastContact.group_id == g.id))).scalars().all())
    return {"id": g.id, "name": g.name, "folder": g.folder, "count": cnt,
            "created_at": g.created_at.isoformat() if g.created_at else None}


@app.get("/broadcast/groups")
async def list_broadcast_groups(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    res = await db.execute(select(BroadcastGroup).order_by(BroadcastGroup.name))
    return [await _group_dict(db, g) for g in res.scalars().all()]


class GroupCreate(BaseModel):
    name: str
    recipients: str = ""
    folder: Optional[str] = None


@app.post("/broadcast/groups")
async def create_broadcast_group(req: GroupCreate, db: AsyncSession = Depends(get_db),
                                 _: bool = Depends(require_shop_access)):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Group name is required.")
    res = await db.execute(select(BroadcastGroup).where(func.lower(BroadcastGroup.name) == name.lower()))
    grp = res.scalar_one_or_none()
    if not grp:
        grp = BroadcastGroup(name=name); db.add(grp); await db.flush()
    if req.folder is not None:
        grp.folder = req.folder.strip() or None
    phones, _sk, _nm = _parse_recipients(req.recipients)
    existing = {c.phone for c in (await db.execute(
        select(BroadcastContact).where(BroadcastContact.group_id == grp.id))).scalars().all()}
    for p in phones:
        if p not in existing:
            db.add(BroadcastContact(group_id=grp.id, phone=p)); existing.add(p)
    await db.commit()
    return await _group_dict(db, grp)


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    folder: Optional[str] = None


@app.put("/broadcast/groups/{group_id}")
async def update_broadcast_group(group_id: int, req: GroupUpdate, db: AsyncSession = Depends(get_db),
                                 _: bool = Depends(require_shop_access)):
    grp = await db.get(BroadcastGroup, group_id)
    if not grp:
        raise HTTPException(404, "Group not found")
    if req.name is not None and req.name.strip():
        grp.name = req.name.strip()
    if req.folder is not None:
        grp.folder = req.folder.strip() or None
    await db.commit()
    return await _group_dict(db, grp)


@app.get("/broadcast/groups/{group_id}")
async def get_broadcast_group(group_id: int, db: AsyncSession = Depends(get_db),
                              _: bool = Depends(require_shop_access)):
    grp = await db.get(BroadcastGroup, group_id)
    if not grp:
        raise HTTPException(404, "Group not found")
    res = await db.execute(select(BroadcastContact).where(BroadcastContact.group_id == group_id).order_by(BroadcastContact.id))
    contacts = [{"id": c.id, "phone": c.phone, "name": c.name} for c in res.scalars().all()]
    logs = (await db.execute(select(BroadcastLog).where(BroadcastLog.group_id == group_id)
                             .order_by(BroadcastLog.created_at.desc()).limit(50))).scalars().all()
    history = [{"message": l.message, "sent_count": l.sent_count,
                "created_at": l.created_at.isoformat() if l.created_at else None} for l in logs]
    return {"id": grp.id, "name": grp.name, "folder": grp.folder, "contacts": contacts, "history": history}


@app.post("/broadcast/groups/{group_id}/contacts")
async def add_group_contacts(group_id: int, req: GroupCreate, db: AsyncSession = Depends(get_db),
                             _: bool = Depends(require_shop_access)):
    grp = await db.get(BroadcastGroup, group_id)
    if not grp:
        raise HTTPException(404, "Group not found")
    phones, _sk, names = _parse_recipients(req.recipients)
    # A single number with a top-level name (blank per-line name) still gets named.
    fallback = (req.name or "").strip() if len(phones) == 1 else ""
    existing = {c.phone for c in (await db.execute(
        select(BroadcastContact).where(BroadcastContact.group_id == group_id))).scalars().all()}
    added = 0
    for p in phones:
        if p not in existing:
            db.add(BroadcastContact(group_id=group_id, phone=p, name=names.get(p) or fallback or None))
            existing.add(p); added += 1
    await db.commit()
    return {"added": added, "total": len(existing)}


@app.delete("/broadcast/groups/{group_id}")
async def delete_broadcast_group(group_id: int, db: AsyncSession = Depends(get_db),
                                 _: bool = Depends(require_shop_access)):
    await db.execute(sa_delete(BroadcastContact).where(BroadcastContact.group_id == group_id))
    grp = await db.get(BroadcastGroup, group_id)
    if grp:
        await db.delete(grp)
    await db.commit()
    return {"deleted": True}


@app.delete("/broadcast/contacts/{contact_id}")
async def delete_group_contact(contact_id: int, db: AsyncSession = Depends(get_db),
                               _: bool = Depends(require_shop_access)):
    c = await db.get(BroadcastContact, contact_id)
    if c:
        await db.delete(c); await db.commit()
    return {"deleted": True}


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None


@app.put("/broadcast/contacts/{contact_id}")
async def update_group_contact(contact_id: int, req: ContactUpdate, db: AsyncSession = Depends(get_db),
                               _: bool = Depends(require_shop_access)):
    """Rename a contact (or fix their number) inside a broadcast group."""
    c = await db.get(BroadcastContact, contact_id)
    if not c:
        raise HTTPException(404, "Contact not found")
    if req.name is not None:
        c.name = _blank(req.name)
    if req.phone is not None:
        phones, _sk, _nm = _parse_recipients(req.phone)
        if phones:
            c.phone = phones[0]
    await db.commit()
    return {"id": c.id, "phone": c.phone, "name": c.name}


# --- Inbound SMS webhook (Twilio posts here when the 877 receives a reply) ---

@app.post("/sms/inbound")
async def sms_inbound(request: Request, db: AsyncSession = Depends(get_db)):
    """Twilio inbound-message webhook for the 877 line. Logs the reply, bumps the
    conversation, and forwards it to the assigned teammate. Secured by a ?key=
    query param so only Twilio (configured with the secret) can post."""
    secret = os.getenv("SHOPS_PASSWORD", "")
    if secret and request.query_params.get("key") != secret:
        return Response(content="<Response></Response>", media_type="application/xml")
    form = await request.form()
    frm = (form.get("From") or "").strip()
    body = (form.get("Body") or "").strip()
    if not frm:
        return Response(content="<Response></Response>", media_type="application/xml")

    now = datetime.utcnow()
    from alerts import send_sms

    # Is this a teammate replying from their own phone? (their number is one of
    # the assignees on a conversation) → relay their text out to the customer they
    # are working, so they can run the whole thread from their phone.
    res = await db.execute(select(SmsConversation)
                           .where(or_(SmsConversation.assignee_phone == frm,
                                      SmsConversation.assignees.like(f'%"{frm}"%')))
                           .order_by(SmsConversation.last_at.desc()))
    target = res.scalars().first()
    if target and body:
        sender_name = next((a.get("name") for a in _assignees_of(target)
                            if a.get("phone") == frm and a.get("name")), "teammate")
        ok = send_sms(target.phone, body)  # out to the customer via the 877
        if ok:
            db.add(SmsMessage(phone=target.phone, direction="out", body=body,
                              sender=sender_name, created_at=now))
            target.last_at = now
            target.last_preview = body[:120]
            target.last_direction = "out"
            await db.commit()
        else:
            try:
                send_sms(frm, "Couldn't deliver that to the customer — try again or use the Inbox.")
            except Exception:
                pass
        return Response(content="<Response></Response>", media_type="application/xml")

    # Otherwise: a customer reply. Log it, bump the thread, forward to the teammate.
    conv = await db.get(SmsConversation, frm)
    if not conv:
        conv = SmsConversation(phone=frm, created_at=now)
        db.add(conv)
    db.add(SmsMessage(phone=frm, direction="in", body=body, created_at=now))
    conv.last_at = now
    conv.last_preview = body[:120]
    conv.last_direction = "in"
    conv.unread = (conv.unread or 0) + 1
    await db.commit()

    who = conv.name or frm
    for a in _assignees_of(conv):
        if a.get("phone"):
            try:
                send_sms(a["phone"], f"\U0001F4E9 {who} ({frm}):\n{body}\n\nJust reply here to text them back.")
            except Exception as e:
                print(f"inbound forward failed: {e}")
    return Response(content="<Response></Response>", media_type="application/xml")


# --- In-app Inbox (shared team SMS inbox for the 877 line) ---

def _assignees_of(c: SmsConversation) -> list:
    """Return [{'name','phone'}, …] follow-up teammates for a conversation,
    falling back to the legacy single assignee columns."""
    try:
        items = json.loads(c.assignees) if c.assignees else []
        if items:
            return items
    except Exception:
        pass
    if c.assignee_phone:
        return [{"name": c.assigned_to, "phone": c.assignee_phone}]
    return []


def _apply_assignees(c: SmsConversation, items: list):
    """Set a conversation's follow-up teammates from a list of {name, phone}.
    Normalizes/dedupes phones and keeps the legacy display columns in sync."""
    clean = []
    seen = set()
    for it in (items or []):
        phone = _one_phone((it or {}).get("phone"))
        if not phone or phone in seen:
            continue
        seen.add(phone)
        clean.append({"name": ((it or {}).get("name") or "").strip() or None, "phone": phone})
    c.assignees = json.dumps(clean) if clean else None
    c.assignee_phone = clean[0]["phone"] if clean else None
    c.assigned_to = ", ".join(a["name"] for a in clean if a.get("name")) or None


def _conv_dict(c: SmsConversation) -> dict:
    return {"phone": c.phone, "name": c.name, "assigned_to": c.assigned_to,
            "assignee_phone": c.assignee_phone, "assignees": _assignees_of(c),
            "unread": c.unread or 0,
            "contact_type": getattr(c, "contact_type", None), "location": getattr(c, "location", None),
            "email": getattr(c, "email", None), "notes": getattr(c, "notes", None),
            "last_preview": c.last_preview, "last_direction": c.last_direction,
            "last_at": c.last_at.isoformat() if c.last_at else None}


@app.get("/sms/conversations")
async def list_conversations(db: AsyncSession = Depends(get_db),
                             _: bool = Depends(require_shop_access)):
    # Only surface threads with real activity — broadcast recipients get a conversation
    # created for reply-routing, but it stays hidden (last_at NULL) until they reply.
    res = await db.execute(select(SmsConversation)
                           .where(SmsConversation.last_at.isnot(None))
                           .order_by(SmsConversation.last_at.desc()))
    return [_conv_dict(c) for c in res.scalars().all()]


@app.post("/admin/backfill-broadcasts")
async def backfill_broadcasts(db: AsyncSession = Depends(get_db),
                              _: bool = Depends(require_shop_access)):
    """One-time (idempotent): gather old per-recipient broadcast messages into the
    single 📣 Broadcasts thread, then hide the now-empty recipient threads. Old
    broadcasts wrote one outbound message per recipient (all sharing the same
    created_at + body = one blast); this consolidates them."""
    # Old broadcast copies live on real phone threads with sender="broadcast".
    res = await db.execute(select(SmsMessage).where(
        SmsMessage.sender == "broadcast", SmsMessage.phone != BROADCAST_THREAD))
    olds = res.scalars().all()
    if not olds:
        return {"blasts": 0, "messages_moved": 0, "threads_hidden": 0, "note": "nothing to backfill"}

    now = datetime.utcnow()
    blasts: dict = {}
    affected_phones = set()
    for m in olds:
        blasts.setdefault((m.created_at, m.body or ""), []).append(m)
        affected_phones.add(m.phone)

    bconv = await db.get(SmsConversation, BROADCAST_THREAD)
    if not bconv:
        bconv = SmsConversation(phone=BROADCAST_THREAD, name="📣 Broadcasts", created_at=now)
        db.add(bconv)
    bconv.name = "📣 Broadcasts"

    # Idempotency: don't duplicate a consolidated entry we already have at that time.
    res = await db.execute(select(SmsMessage.created_at).where(SmsMessage.phone == BROADCAST_THREAD))
    existing_ts = set(res.scalars().all())

    moved = 0
    latest_ts = bconv.last_at
    latest_body = bconv.last_preview
    for (ts, body), msgs in sorted(blasts.items(), key=lambda kv: (kv[0][0] or now)):
        n = len(msgs)
        n_txt = f"{n} recipient" + ("" if n == 1 else "s")
        if ts not in existing_ts:
            db.add(SmsMessage(phone=BROADCAST_THREAD, direction="out",
                              body=f"{body}\n\n— sent to {n_txt}", sender="broadcast", created_at=ts))
            if ts and (latest_ts is None or ts > latest_ts):
                latest_ts, latest_body = ts, f"{body}  →  {n_txt}"
        for m in msgs:                 # remove the scattered per-person copies
            await db.delete(m)
            moved += 1
    bconv.last_at = latest_ts or now
    bconv.last_preview = (latest_body or "📣 Broadcast history")[:120]
    bconv.last_direction = "out"
    await db.flush()

    # Recompute each recipient thread's last activity; hide it if nothing else remains.
    hidden = 0
    for p in affected_phones:
        conv = await db.get(SmsConversation, p)
        if not conv:
            continue
        r = await db.execute(select(SmsMessage).where(SmsMessage.phone == p)
                             .order_by(SmsMessage.created_at.desc()).limit(1))
        last = r.scalars().first()
        if last:
            conv.last_at = last.created_at
            conv.last_preview = (last.body or "")[:120]
            conv.last_direction = last.direction
        else:
            conv.last_at = None
            conv.last_preview = None
            conv.last_direction = None
            hidden += 1
    await db.commit()
    return {"blasts": len(blasts), "messages_moved": moved, "threads_hidden": hidden}


@app.get("/sms/conversation")
async def get_conversation(phone: str, db: AsyncSession = Depends(get_db),
                           _: bool = Depends(require_shop_access)):
    conv = await db.get(SmsConversation, phone)
    if not conv:
        raise HTTPException(404, "No conversation")
    conv.unread = 0  # opening the thread marks it read
    res = await db.execute(select(SmsMessage).where(SmsMessage.phone == phone).order_by(SmsMessage.created_at))
    msgs = [{"id": m.id, "direction": m.direction, "body": m.body, "sender": m.sender,
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in res.scalars().all()]
    await db.commit()
    return {"conversation": _conv_dict(conv), "messages": msgs}


class ConvSendRequest(BaseModel):
    phone: str
    body: str
    sender: Optional[str] = None


@app.post("/sms/conversation/send")
async def conversation_send(req: ConvSendRequest, db: AsyncSession = Depends(get_db),
                            _: bool = Depends(require_shop_access)):
    """A teammate replies to a customer from the in-app inbox — goes out via the 877."""
    from alerts import send_sms
    phone = (req.phone or "").strip()
    body = (req.body or "").strip()
    if not phone or not body:
        raise HTTPException(400, "Phone and message are required.")
    if phone == BROADCAST_THREAD:
        raise HTTPException(400, "That's the broadcast log — send a new blast from the Broadcast tab.")
    if not send_sms(phone, body):
        raise HTTPException(502, "Twilio failed to send the message.")
    now = datetime.utcnow()
    conv = await db.get(SmsConversation, phone)
    if not conv:
        conv = SmsConversation(phone=phone, created_at=now)
        db.add(conv)
    conv.last_at = now
    conv.last_preview = body[:120]
    conv.last_direction = "out"
    db.add(SmsMessage(phone=phone, direction="out", body=body, sender=(req.sender or "").strip() or None, created_at=now))
    await db.commit()
    return {"sent": True}


class ConvAssignRequest(BaseModel):
    phone: str
    assigned_to: Optional[str] = None
    assignee_phone: Optional[str] = None
    assignees: Optional[list[AssigneeItem]] = None
    name: Optional[str] = None


@app.put("/sms/conversation/assign")
async def conversation_assign(req: ConvAssignRequest, db: AsyncSession = Depends(get_db),
                              _: bool = Depends(require_shop_access)):
    conv = await db.get(SmsConversation, (req.phone or "").strip())
    if not conv:
        raise HTTPException(404, "No conversation")
    if req.assignees is not None:
        _apply_assignees(conv, [{"name": a.name, "phone": a.phone} for a in req.assignees])
    else:
        _apply_assignees(conv, [{"name": req.assigned_to, "phone": req.assignee_phone}] if req.assignee_phone else [])
    if req.name is not None:
        conv.name = req.name.strip() or None
    await db.commit()
    return _conv_dict(conv)


class ConvDetailsRequest(BaseModel):
    phone: str
    name: Optional[str] = None
    contact_type: Optional[str] = None
    location: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None


@app.put("/sms/conversation/details")
async def conversation_details(req: ConvDetailsRequest, db: AsyncSession = Depends(get_db),
                               _: bool = Depends(require_shop_access)):
    """Update the who-is-this info on an Inbox conversation (name, type, location,
    email, notes). Only fields provided are changed."""
    conv = await db.get(SmsConversation, (req.phone or "").strip())
    if not conv:
        raise HTTPException(404, "No conversation")
    if req.name is not None: conv.name = _blank(req.name)
    if req.contact_type is not None: conv.contact_type = _blank(req.contact_type)
    if req.location is not None: conv.location = _blank(req.location)
    if req.email is not None: conv.email = _blank(req.email)
    if req.notes is not None: conv.notes = req.notes.strip() or None
    await db.commit()
    return _conv_dict(conv)


@app.delete("/sms/conversation")
async def delete_conversation(phone: str, db: AsyncSession = Depends(get_db),
                              _: bool = Depends(require_shop_access)):
    """Remove a conversation and all of its messages from the Inbox."""
    await db.execute(sa_delete(SmsMessage).where(SmsMessage.phone == phone))
    conv = await db.get(SmsConversation, phone)
    if conv:
        await db.delete(conv)
    await db.commit()
    return {"deleted": True}


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
            "category": n.category, "buys_wax": bool(n.buys_wax),
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


class CallerCategoryUpdate(BaseModel):
    caller_name: str
    category: Optional[str] = None   # "breaker" | "shop" | None/"" to clear


@app.put("/caller-notes/category")
async def set_caller_category(req: CallerCategoryUpdate, db: AsyncSession = Depends(get_db),
                              _: bool = Depends(require_shop_access)):
    """Tag a caller as a breaker or card shop (applies to all of their notes)."""
    name = (req.caller_name or "").strip()
    # category is now a comma-separated list of type keys (a caller can be several).
    raw = (req.category or "").strip().lower()
    valid = {"breaker", "shop", "whatnot", "investor", "highend", "buyshigh"}
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if any(p not in valid for p in parts):
        raise HTTPException(400, "category keys must be one of: " + ", ".join(sorted(valid)))
    cat = ",".join(dict.fromkeys(parts)) or None
    res = await db.execute(select(CallerNote).where(CallerNote.caller_name == name))
    rows = res.scalars().all()
    for n in rows:
        n.category = cat
    await db.commit()
    return {"caller_name": name, "category": cat, "updated": len(rows)}


class CallerBuysWaxUpdate(BaseModel):
    caller_name: str
    buys_wax: bool


@app.put("/caller-notes/buys-wax")
async def set_caller_buys_wax(req: CallerBuysWaxUpdate, db: AsyncSession = Depends(get_db),
                              _: bool = Depends(require_shop_access)):
    """Flag whether a caller buys sealed wax (applies to all of their notes)."""
    name = (req.caller_name or "").strip()
    res = await db.execute(select(CallerNote).where(CallerNote.caller_name == name))
    rows = res.scalars().all()
    for n in rows:
        n.buys_wax = req.buys_wax
    await db.commit()
    return {"caller_name": name, "buys_wax": req.buys_wax, "updated": len(rows)}


# --- Wax Ladder: sold-price history for sealed wax boxes (search -> stats + chart) ---

def _wax_key(query: str) -> str:
    """Normalized dedupe key for a tracked box (lowercased, collapsed whitespace)."""
    import re
    return re.sub(r"\s+", " ", (query or "").strip().lower())


async def _compute_wax_history(query: str) -> dict:
    """Recent eBay SOLD prices for a sealed wax box, filtered to actual boxes
    (no breaks/cases/singles/graded), with summary stats for the ladder + chart.
    Shared by the /wax-history endpoint and the daily snapshot job."""
    from scrapers.ebay_scraper import get_sold_history
    from statistics import median
    import re
    q = (query or "").strip()
    if not q:
        raise HTTPException(400, "Enter a wax box to search.")
    kw = q if "box" in q.lower() else f"{q} hobby box"
    sold = await get_sold_history(kw, limit=50)
    ql = kw.lower()

    # Junk: not the item we want (breaks/lots/singles/graded).
    NOISE = ("break", "case", "single", " lot ", "lot of", "psa", "bgs", "sgc", "cgc",
             "graded", "rip", "spot", " x ", "pack war", "random", "read desc", "empty")
    # Different FORMATS of a box (priced differently than a base hobby box). Only
    # exclude a format if the shopper didn't actually ask for it.
    FORMATS = ("jumbo", "hta", "mega", "blaster", "value", "tin", "mixer", "retail",
               "cello", "hanger", "fat pack", "fatpack", "gravity", "choice",
               "update", "super box", "vip", "asia", "lite")
    bad_formats = [f for f in FORMATS if f not in ql]

    # Product tokens the title MUST contain (brand/set/sport), so a "Topps Chrome"
    # search doesn't pull in Bowman, etc. Ignore filler + parse the year loosely.
    STOP = {"box", "hobby", "factory", "sealed", "new", "brand", "the", "a", "of",
            "sports", "cards", "card", "trading", "mlb", "nba", "nfl", "nhl"}
    yr = re.search(r"\b(19|20)\d{2}\b", kw)
    year = yr.group(0) if yr else None
    y2 = year[2:] if year else None  # 2-digit for '2023-24' style
    words = [w for w in re.findall(r"[a-z]+", ql) if w not in STOP and len(w) > 2]

    def matches(title: str, p: float) -> bool:
        t = title.lower()
        if "box" not in t or p < 20:
            return False
        if any(n in t for n in NOISE):
            return False
        if any(f in t for f in bad_formats):
            return False
        # every product word must be present
        if not all(w in t for w in words):
            return False
        # if the query names a year, require it (or its 2-digit season form)
        if year and (year not in t and not (y2 and re.search(rf"\D{y2}\b", t))):
            return False
        return True

    cand = []
    for s in sold:
        p = s.get("sold_price") or 0
        if matches(s.get("title") or "", p):
            cand.append(s)

    if not cand:
        return {"query": kw, "sold": [], "stats": None}

    # Trim price outliers around the median so one mislabeled case/lot can't
    # blow out the range + average.
    med0 = median(sorted(c["sold_price"] for c in cand))
    lo, hi = med0 * 0.55, med0 * 1.8
    boxes = [c for c in cand if lo <= c["sold_price"] <= hi] or cand

    prices = sorted(s["sold_price"] for s in boxes)
    # Trimmed mean: drop the top/bottom ~10% before averaging so a lone hot or
    # lowball sale doesn't drag the "typical" price around.
    k = int(len(prices) * 0.1)
    core = prices[k: len(prices) - k] if len(prices) - 2 * k >= 1 else prices
    dated = sorted((s for s in boxes if s.get("sold_at")), key=lambda s: s["sold_at"])
    last = dated[-1] if dated else boxes[0]
    stats = {
        "count": len(prices),
        "median": round(median(prices)),
        "avg": round(sum(core) / len(core)),
        "min": round(prices[0]),
        "max": round(prices[-1]),
        "last_price": round(last["sold_price"]),
        "last_date": last.get("sold_at"),
    }
    return {"query": kw, "sold": boxes, "stats": stats}


_CARD_NOISE = ("box", "case", "break", "lot ", "lot of", "pack", "blaster",
               "hobby box", "reprint", "digital", "custom", " x ", "sticker")
_CARD_GRADED = ("psa", "bgs", "sgc", "cgc", "graded", "gem mt", "gem mint")
_CARD_STOP = {"the", "a", "of", "card", "cards", "rc", "and"}


async def _card_comps(query: str, graded=None, grade_num: str = "", search: str = None) -> list:
    """THE single source of truth for card sold-comps. Every card price in the app
    (Card Prices, Deal Check, Grading ROI, inventory market value) goes through
    this so the numbers agree. Filters out boxes/breaks/lots, requires ALL of the
    query's meaningful words in the title, enforces '/N' serials, optionally
    restricts to graded/raw and a specific grade number, then trims outliers.
    Returns the kept sold dicts (empty if none)."""
    from scrapers.ebay_scraper import get_sold_history
    from statistics import median
    import re
    ql = (query or "").lower()
    words = [w for w in re.findall(r"[a-z0-9]+", ql) if w not in _CARD_STOP and len(w) > 1]
    serials = re.findall(r"(?:^|\s)/\s*(\d+)\b", ql)
    sold = await get_sold_history(search or query, limit=50)
    keep = []
    for s in sold:
        t = (s.get("title") or "").lower(); p = s.get("sold_price") or 0
        if p < 1 or any(n in t for n in _CARD_NOISE):
            continue
        if not all(w in t for w in words):
            continue
        if serials and not all(re.search(rf"/0*{n}(?!\d)", t) for n in serials):
            continue
        has_g = any(g in t for g in _CARD_GRADED)
        if graded is True and not has_g:
            continue
        if graded is False and has_g:
            continue
        if grade_num == "10" and not re.search(r"\b10\b", t):
            continue
        if grade_num == "9" and (re.search(r"\b10\b", t) or not re.search(r"\b9(?:\.5)?\b", t)):
            continue
        keep.append(s)
    if not keep:
        return []
    med0 = median(sorted(x["sold_price"] for x in keep))
    lo, hi = med0 * 0.4, med0 * 2.5
    return [x for x in keep if lo <= x["sold_price"] <= hi] or keep


def _comp_median(sales: list):
    """(median, count) over a comp list from _card_comps."""
    from statistics import median
    if not sales:
        return None, 0
    prices = sorted(x["sold_price"] for x in sales)
    return round(median(prices)), len(prices)


async def _compute_card_history(query: str) -> dict:
    """Full stats + recent sales for a single CARD, via the shared comp method."""
    from statistics import median
    q = (query or "").strip()
    if not q:
        raise HTTPException(400, "Enter a card to search.")
    keep = await _card_comps(q)
    if not keep:
        return {"query": q, "sold": [], "stats": None}
    prices = sorted(s["sold_price"] for s in keep)
    k = int(len(prices) * 0.1)
    core = prices[k: len(prices) - k] if len(prices) - 2 * k >= 1 else prices
    dated = sorted((s for s in keep if s.get("sold_at")), key=lambda s: s["sold_at"])
    last = dated[-1] if dated else keep[0]
    stats = {"count": len(prices), "median": round(median(prices)),
             "avg": round(sum(core) / len(core)), "min": round(prices[0]),
             "max": round(prices[-1]), "last_price": round(last["sold_price"]),
             "last_date": last.get("sold_at")}
    return {"query": q, "sold": keep, "stats": stats}


async def _compute_tracked(kind: str, query: str) -> dict:
    return await (_compute_card_history(query) if kind == "card" else _compute_wax_history(query))


@app.get("/wax-history")
async def wax_history(query: str, _: bool = Depends(require_shop_access)):
    """Live sold-comp lookup for a box (point-in-time stats + recent sales)."""
    return await _compute_wax_history(query)


@app.get("/card-history")
async def card_history(query: str, _: bool = Depends(require_shop_access)):
    """Live sold-comp lookup for a single card (point-in-time stats + recent sales)."""
    return await _compute_card_history(query)


@app.get("/deal-check")
async def deal_check(query: str = "", price: float = 0, url: str = "",
                     _: bool = Depends(require_shop_access)):
    """Is a listing a good buy? Resolves a card + asking price (from a pasted eBay
    URL or a typed query + price), then scores it against recent sold comps."""
    from scrapers.ebay_scraper import get_item_by_url
    title = (query or "").strip()
    ask = price or 0
    listing_url = url or None
    image_url = None
    if url and "http" in url:
        item = await get_item_by_url(url)
        if item:
            title = item.get("title") or title
            if not ask:
                ask = item.get("price") or 0
            image_url = item.get("image_url")
            listing_url = item.get("url") or url
        elif not title:
            raise HTTPException(400, "Couldn't read that eBay link — paste the card name + price instead.")
    if not title:
        raise HTTPException(400, "Enter a card (or an eBay link).")
    data = await _compute_card_history(title)
    st = data.get("stats")
    if not st:
        return {"title": title, "ask": ask, "market": None, "comps": 0,
                "pct": None, "verdict": "unknown", "listing_url": listing_url, "image_url": image_url}
    market = st["median"]
    pct = round((ask - market) / market * 100, 1) if (ask and market) else None
    if pct is None:
        verdict = "unknown"
    elif pct <= -25:
        verdict = "steal"
    elif pct <= -8:
        verdict = "good"
    elif pct <= 12:
        verdict = "fair"
    else:
        verdict = "high"
    return {"title": title, "ask": round(ask, 2) if ask else None, "market": market,
            "comps": st["count"], "range": [st["min"], st["max"]], "pct": pct,
            "verdict": verdict, "listing_url": listing_url, "image_url": image_url}


async def _tracked_list(db, kind: str) -> dict:
    """Tracked items of one kind, each with its dated snapshot history + target."""
    from database import WaxTracked, WaxSnapshot
    rows = (await db.execute(
        select(WaxTracked).where((WaxTracked.kind == kind) | ((WaxTracked.kind == None) & (kind == "box")))
        .order_by(WaxTracked.created_at))).scalars().all()
    out = []
    for r in rows:
        snaps = (await db.execute(
            select(WaxSnapshot).where(WaxSnapshot.box_key == r.box_key).order_by(WaxSnapshot.day)
        )).scalars().all()
        hist = [{"day": s.day, "median": s.median, "avg": s.avg, "min": s.min,
                 "max": s.max, "count": s.count} for s in snaps]
        first = next((s.median for s in snaps if s.median), None)
        last = next((s.median for s in reversed(snaps) if s.median), None)
        change = round(last - first) if (first and last) else None
        change_pct = round((last - first) / first * 100, 1) if (first and last) else None
        tp = r.target_price
        out.append({
            "id": r.id, "query": r.query, "box_key": r.box_key,
            "points": len(hist), "history": hist,
            "latest": last, "first": first, "change": change, "change_pct": change_pct,
            "target_price": tp,
            "hit": bool(tp is not None and last is not None and last <= tp),
        })
    return {"tracked": out}


async def _track_add(db, kind: str, query: str) -> dict:
    from database import WaxTracked
    key = _wax_key(query)
    if not key:
        raise HTTPException(400, "Enter something to track.")
    existing = (await db.execute(select(WaxTracked).where(WaxTracked.box_key == key))).scalar_one_or_none()
    if not existing:
        db.add(WaxTracked(box_key=key, query=query.strip(), kind=kind))
        await db.commit()
    await _snapshot_one_box(db, key, query.strip(), kind)
    return {"ok": True, "box_key": key}


async def _track_remove(db, query: str, box_key: str) -> dict:
    from database import WaxTracked, WaxSnapshot
    key = box_key or _wax_key(query)
    if not key:
        raise HTTPException(400, "Nothing to untrack.")
    await db.execute(sa_delete(WaxTracked).where(WaxTracked.box_key == key))
    await db.execute(sa_delete(WaxSnapshot).where(WaxSnapshot.box_key == key))
    await db.commit()
    return {"ok": True}


async def _set_target(db, query: str, box_key: str, target: float) -> dict:
    from database import WaxTracked
    key = box_key or _wax_key(query)
    r = (await db.execute(select(WaxTracked).where(WaxTracked.box_key == key))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "That isn't tracked.")
    r.target_price = round(target, 2) if target and target > 0 else None
    r.target_hit_day = None
    await db.commit()
    return {"ok": True, "target_price": r.target_price}


@app.get("/wax-tracked")
async def wax_tracked_list(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    return await _tracked_list(db, "box")


@app.post("/wax-track")
async def wax_track_add(query: str, db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    return await _track_add(db, "box", query)


@app.delete("/wax-track")
async def wax_track_remove(query: str = "", box_key: str = "", db: AsyncSession = Depends(get_db),
                           _: bool = Depends(require_shop_access)):
    return await _track_remove(db, query, box_key)


@app.post("/wax-target")
async def wax_set_target(query: str = "", box_key: str = "", target: float = 0,
                         db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    return await _set_target(db, query, box_key, target)


@app.get("/card-tracked")
async def card_tracked_list(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    return await _tracked_list(db, "card")


@app.post("/card-track")
async def card_track_add(query: str, db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    return await _track_add(db, "card", query)


@app.delete("/card-track")
async def card_track_remove(query: str = "", box_key: str = "", db: AsyncSession = Depends(get_db),
                            _: bool = Depends(require_shop_access)):
    return await _track_remove(db, query, box_key)


@app.post("/card-target")
async def card_set_target(query: str = "", box_key: str = "", target: float = 0,
                          db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    return await _set_target(db, query, box_key, target)


async def _snapshot_one_box(db: AsyncSession, key: str, query: str, kind: str = "box"):
    """Record today's price reading for one tracked item (idempotent per Pacific day)."""
    from database import WaxSnapshot
    today = _pacific_day_str()
    exists = (await db.execute(
        select(WaxSnapshot).where(WaxSnapshot.box_key == key, WaxSnapshot.day == today)
    )).scalar_one_or_none()
    if exists:
        return False
    try:
        data = await _compute_tracked(kind, query)
    except Exception as e:
        print(f"snapshot compute error for {key}: {e}")
        return False
    st = data.get("stats")
    if not st:
        return False
    db.add(WaxSnapshot(box_key=key, day=today, median=st["median"], avg=st["avg"],
                       min=st["min"], max=st["max"], count=st["count"]))
    await db.commit()
    return st["median"]


async def _check_wax_target(db, r, median_now):
    """Email the owner once when a tracked box's median drops to/below its target."""
    from alerts import _deliver_email
    today = _pacific_day_str()
    if not (r.target_price and median_now is not None and median_now <= r.target_price):
        return
    if r.target_hit_day == today:
        return  # already alerted today
    try:
        where = "Card Ladder" if (r.kind == "card") else "Wax Ladder"
        _deliver_email(
            OWNER_EMAIL,
            f"🎯 Buy signal: {r.query} at ${round(median_now)}",
            html=f"<p><b>{r.query}</b> just hit your target.</p>"
                 f"<p>Median sold: <b>${round(median_now)}</b> (target ${round(r.target_price)}).</p>"
                 f"<p>Time to buy — check the {where} for the trend.</p>",
            text=f"{r.query} hit ${round(median_now)} (target ${round(r.target_price)}).",
        )
    except Exception as e:
        print(f"wax target email error for {r.box_key}: {e}")
    r.target_hit_day = today
    await db.commit()


async def _snapshot_wax_if_new_day(db: AsyncSession):
    """Once per Pacific day, snapshot every tracked box so the ladder gains a point."""
    from database import AppFlag, WaxTracked
    today = _pacific_day_str()
    flag = await db.get(AppFlag, "wax_snapshot_day")
    if flag and flag.value == today:
        return
    rows = (await db.execute(select(WaxTracked))).scalars().all()
    n = 0
    for r in rows:
        med = await _snapshot_one_box(db, r.box_key, r.query, r.kind or "box")
        if med:
            n += 1
            await _check_wax_target(db, r, med)
    if flag:
        flag.value = today
    else:
        db.add(AppFlag(key="wax_snapshot_day", value=today))
    await db.commit()
    print(f"Wax snapshot for {today}: {n}/{len(rows)} boxes recorded")


# --- Inventory: manual buy/sell ledger with profit (shop-gated, shared) ---

class InventoryIn(BaseModel):
    image: Optional[str] = None          # base64 data URL of the card photo
    sport: Optional[str] = None
    player: Optional[str] = None
    card_set: Optional[str] = None
    grade: Optional[str] = None
    cost: Optional[float] = None
    bought_by: Optional[str] = None
    purchase_date: Optional[str] = None
    status: Optional[str] = None          # in_stock | listed | sold
    listing_url: Optional[str] = None
    sold: Optional[bool] = None           # legacy; derived from status
    sale_price: Optional[float] = None
    fees: Optional[float] = None          # platform/selling fees
    shipping: Optional[float] = None      # shipping cost
    sold_date: Optional[str] = None
    notes: Optional[str] = None


def _inv_status(r) -> str:
    s = (getattr(r, "status", None) or "").strip()
    if s in ("in_stock", "listed", "sold"):
        return s
    return "sold" if getattr(r, "sold", False) else "in_stock"


def _days_held(a, b):
    from datetime import date
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except Exception:
        return None


def _inv_dict(r) -> dict:
    status = _inv_status(r)
    is_sold = status == "sold"
    net = gross = roi = days = None
    if is_sold and r.sale_price is not None and r.cost is not None:
        gross = round(r.sale_price - r.cost, 2)
        net = round(r.sale_price - r.cost - (r.fees or 0) - (r.shipping or 0), 2)
        if r.cost:
            roi = round(net / r.cost * 100, 1)
        days = _days_held(r.purchase_date, r.sold_date)
    mv = getattr(r, "market_value", None)
    # Unrealized profit vs cost, only meaningful while we still hold the card.
    unrealized = round(mv - r.cost, 2) if (not is_sold and mv is not None and r.cost is not None) else None
    return {
        "id": r.id, "image": r.image, "sport": r.sport, "player": r.player,
        "card_set": r.card_set, "grade": r.grade, "cost": r.cost,
        "bought_by": r.bought_by, "purchase_date": r.purchase_date,
        "status": status, "listing_url": r.listing_url,
        "sold": is_sold, "sale_price": r.sale_price,
        "fees": r.fees, "shipping": r.shipping, "sold_date": r.sold_date,
        "notes": r.notes, "profit": net, "gross_profit": gross,
        "roi": roi, "days_held": days,
        "market_value": mv, "market_comps": getattr(r, "market_comps", None),
        "valued_at": r.valued_at.isoformat() if getattr(r, "valued_at", None) else None,
        "unrealized": unrealized,
    }


def _normalize_inv(data: dict) -> dict:
    """Keep status <-> sold in sync whichever one the client sent."""
    s = data.get("status")
    if s in ("in_stock", "listed", "sold"):
        data["sold"] = (s == "sold")
    elif data.get("sold") is not None:
        data["status"] = "sold" if data["sold"] else "in_stock"
    return data


_STATUS_RANK = {"in_stock": 0, "listed": 1, "sold": 2}
_INV_SORTS = {
    "purchase_date": lambda d: (d["purchase_date"] or ""),
    "sold_date": lambda d: (d["sold_date"] or ""),
    "bought_by": lambda d: (d["bought_by"] or "").lower(),
    "status": lambda d: _STATUS_RANK.get(d["status"], 0),
    "sold": lambda d: (1 if d["sold"] else 0),
    "profit": lambda d: d["profit"] if d["profit"] is not None else float("-inf"),
    "roi": lambda d: d["roi"] if d["roi"] is not None else float("-inf"),
    "days_held": lambda d: d["days_held"] if d["days_held"] is not None else float("-inf"),
    "player": lambda d: (d["player"] or "").lower(),
    "cost": lambda d: (d["cost"] or 0),
}


@app.get("/inventory")
async def inventory_list(sort: str = "purchase_date", desc: bool = True,
                         q: str = "", status: str = "",
                         db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    """The inventory ledger, filtered + sorted, with rolled-up totals (net of fees)."""
    from database import InventoryItem
    rows = (await db.execute(select(InventoryItem))).scalars().all()
    items = [_inv_dict(r) for r in rows]
    # Filter: free-text search + status.
    term = (q or "").strip().lower()
    if term:
        def hit(i):
            return term in " ".join(str(i.get(k) or "") for k in
                                    ("player", "card_set", "sport", "grade", "bought_by", "notes")).lower()
        items = [i for i in items if hit(i)]
    if status in ("in_stock", "listed", "sold"):
        items = [i for i in items if i["status"] == status]
    keyfn = _INV_SORTS.get(sort, _INV_SORTS["purchase_date"])
    items.sort(key=keyfn, reverse=desc)
    sold_items = [i for i in items if i["sold"]]
    held = [i for i in items if not i["sold"]]  # in_stock + listed
    totals = {
        "count": len(items),
        "in_stock": sum(1 for i in items if i["status"] == "in_stock"),
        "listed": sum(1 for i in items if i["status"] == "listed"),
        "sold_count": len(sold_items),
        "total_cost": round(sum(i["cost"] or 0 for i in items), 2),
        "total_sales": round(sum(i["sale_price"] or 0 for i in sold_items), 2),
        "total_fees": round(sum((i["fees"] or 0) + (i["shipping"] or 0) for i in sold_items), 2),
        "total_profit": round(sum(i["profit"] or 0 for i in sold_items), 2),
        # Current worth of unsold cards (uses cached market value where we have it,
        # else falls back to cost so the number isn't misleadingly low).
        "shelf_value": round(sum((i["market_value"] if i["market_value"] is not None else (i["cost"] or 0)) for i in held), 2),
        "unrealized_profit": round(sum(i["unrealized"] or 0 for i in held), 2),
        "valued_count": sum(1 for i in held if i["market_value"] is not None),
        "held_count": len(held),
    }
    return {"items": items, "totals": totals}


@app.post("/inventory")
async def inventory_create(body: InventoryIn, db: AsyncSession = Depends(get_db),
                           _: bool = Depends(require_shop_access)):
    from database import InventoryItem
    data = _normalize_inv(body.model_dump(exclude_none=False))
    r = InventoryItem(**data)
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return _inv_dict(r)


class InvAutofillIn(BaseModel):
    image: str  # data URL (data:image/...;base64,...) of the card photo


@app.post("/inventory/autofill")
async def inventory_autofill(body: InvAutofillIn, _: bool = Depends(require_shop_access)):
    """Read a card photo with Groq vision and return inventory fields to prefill
    (sport, player, set, grade). Same free vision the Card Lookup tab uses."""
    import re
    m = re.match(r"data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", (body.image or "").strip(), re.DOTALL)
    if not m:
        raise HTTPException(400, "Send the card image as a data URL (data:image/...;base64,...).")
    media, b64 = m.group(1), m.group(2)
    from card_vision import identify_card
    try:
        r = await identify_card(b64, media)
    except Exception as e:
        raise HTTPException(502, f"Couldn't read the card: {e}")
    if not r.get("identified"):
        return {"identified": False, "fields": {}}
    year = (r.get("year") or "").strip()
    brand = (r.get("brand") or "").strip()
    card_set = " ".join(x for x in (year, brand) if x).strip() or None
    if r.get("is_graded") and r.get("grader"):
        grade = f"{r.get('grader')} {r.get('grade') or ''}".strip()
    elif r.get("is_graded") is False:
        grade = "Raw"
    else:
        grade = (r.get("grade") or None)
    num = str(r.get("card_number") or "").strip().lstrip("#")
    extras = [x for x in (r.get("parallel"), (f"#{num}" if num else None)) if x]
    fields = {
        "player": r.get("player") or None,
        "sport": r.get("sport") or None,
        "card_set": card_set,
        "grade": grade,
        "notes": " · ".join(extras) or None,
    }
    return {"identified": True, "confidence": r.get("confidence"), "fields": fields}


@app.put("/inventory/{item_id}")
async def inventory_update(item_id: int, body: InventoryIn, db: AsyncSession = Depends(get_db),
                           _: bool = Depends(require_shop_access)):
    from database import InventoryItem
    r = await db.get(InventoryItem, item_id)
    if not r:
        raise HTTPException(404, "Item not found.")
    for k, v in _normalize_inv(body.model_dump()).items():
        setattr(r, k, v)
    await db.commit()
    await db.refresh(r)
    return _inv_dict(r)


@app.delete("/inventory/{item_id}")
async def inventory_delete(item_id: int, db: AsyncSession = Depends(get_db),
                           _: bool = Depends(require_shop_access)):
    from database import InventoryItem
    await db.execute(sa_delete(InventoryItem).where(InventoryItem.id == item_id))
    await db.commit()
    return {"ok": True}


_INV_CSV_COLS = ["player", "sport", "card_set", "grade", "cost", "bought_by",
                 "purchase_date", "status", "sale_price", "fees", "shipping",
                 "sold_date", "market_value", "profit", "roi", "days_held",
                 "notes", "listing_url"]


@app.get("/inventory/export")
async def inventory_export(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    """Whole ledger as CSV text (image excluded). Client downloads it."""
    import csv, io
    from database import InventoryItem
    rows = (await db.execute(select(InventoryItem))).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_INV_CSV_COLS)
    for r in rows:
        d = _inv_dict(r)
        w.writerow(["" if d.get(c) is None else d.get(c) for c in _INV_CSV_COLS])
    return Response(content=buf.getvalue(), media_type="text/csv")


class CsvIn(BaseModel):
    csv: str


@app.post("/inventory/import")
async def inventory_import(body: CsvIn, db: AsyncSession = Depends(get_db),
                           _: bool = Depends(require_shop_access)):
    """Bulk-load inventory from CSV text. Recognizes the export headers (case-
    insensitive; 'set' also maps to card_set). Ignores computed columns."""
    import csv, io
    from database import InventoryItem
    text = (body.csv or "").strip()
    if not text:
        raise HTTPException(400, "No CSV provided.")
    reader = csv.DictReader(io.StringIO(text))
    alias = {"set": "card_set", "card set": "card_set", "bought by": "bought_by",
             "purchase date": "purchase_date", "sale price": "sale_price",
             "sold date": "sold_date", "listing": "listing_url", "listing_url": "listing_url"}
    text_cols = {"player", "sport", "card_set", "grade", "bought_by", "purchase_date",
                 "status", "sold_date", "notes", "listing_url"}
    num_cols = {"cost", "sale_price", "fees", "shipping"}
    imported = skipped = 0
    for raw in reader:
        row = {}
        for k, v in (raw or {}).items():
            key = alias.get((k or "").strip().lower(), (k or "").strip().lower())
            if key in text_cols and v not in (None, ""):
                row[key] = str(v).strip()
            elif key in num_cols and v not in (None, ""):
                try:
                    row[key] = float(str(v).replace("$", "").replace(",", "").strip())
                except ValueError:
                    pass
        if not any(row.get(k) for k in ("player", "card_set", "cost", "notes")):
            skipped += 1
            continue
        st = (row.get("status") or "").strip().lower()
        row["status"] = st if st in ("in_stock", "listed", "sold") else "in_stock"
        row["sold"] = row["status"] == "sold"
        db.add(InventoryItem(**row))
        imported += 1
    await db.commit()
    return {"imported": imported, "skipped": skipped}


def _card_query(r) -> str:
    """Build an eBay search string for a card from its fields."""
    grade = (r.grade or "").strip()
    parts = [r.card_set, r.player]
    if grade and grade.lower() != "raw":
        parts.append(grade)
    return " ".join(p.strip() for p in parts if p and p.strip())


async def _estimate_card_value(r) -> tuple:
    """(median_sold_price, comp_count) for an inventory card, via the shared comp
    method so it agrees with Card Prices / Deal Check / Grading ROI. A raw card
    values against raw comps; a graded card against its grade."""
    q = _card_query(r)
    if not q:
        return None, 0
    graded = None
    if r.grade and r.grade.strip().lower() == "raw":
        graded = False
    comps = await _card_comps(q, graded=graded)
    return _comp_median(comps)


@app.post("/inventory/value")
async def inventory_value(only_unvalued: bool = False, db: AsyncSession = Depends(get_db),
                          _: bool = Depends(require_shop_access)):
    """Refresh eBay sold-median market values for unsold cards (budget-guarded).
    Set only_unvalued=true to skip cards already valued and save eBay calls."""
    from database import InventoryItem
    from scrapers.ebay_scraper import _budget_available
    rows = (await db.execute(select(InventoryItem))).scalars().all()
    targets = [r for r in rows if _inv_status(r) != "sold"]
    if only_unvalued:
        targets = [r for r in targets if r.market_value is None]
    valued = skipped = 0
    for r in targets:
        if not _budget_available():
            skipped += 1
            continue
        try:
            mv, comps = await _estimate_card_value(r)
        except Exception as e:
            print(f"inventory value error for {r.id}: {e}")
            mv, comps = None, 0
        if mv is not None:
            r.market_value = mv
            r.market_comps = comps
            r.valued_at = datetime.utcnow()
            valued += 1
    await db.commit()
    return {"valued": valued, "skipped": skipped, "targets": len(targets)}


@app.get("/inventory/analytics")
async def inventory_analytics(aging_days: int = 60, db: AsyncSession = Depends(get_db),
                              _: bool = Depends(require_shop_access)):
    """Roll-up insights over the ledger: profit trends, per-teammate / per-sport
    breakdowns, days-to-sell, best/worst flips, and stale in-stock cards."""
    from database import InventoryItem
    from statistics import median
    rows = (await db.execute(select(InventoryItem))).scalars().all()
    items = [_inv_dict(r) for r in rows]
    sold = [i for i in items if i["sold"] and i["profit"] is not None]
    held = [i for i in items if not i["sold"]]

    def group(items_, key):
        agg = {}
        for i in items_:
            k = (i.get(key) or "—").strip() or "—"
            a = agg.setdefault(k, {"label": k, "count": 0, "profit": 0.0, "cost": 0.0})
            a["count"] += 1
            a["profit"] += i["profit"] or 0
            a["cost"] += i["cost"] or 0
        out = [{"label": a["label"], "count": a["count"], "profit": round(a["profit"], 2),
                "roi": round(a["profit"] / a["cost"] * 100, 1) if a["cost"] else None} for a in agg.values()]
        return sorted(out, key=lambda x: x["profit"], reverse=True)

    # Profit by sold month (YYYY-MM), chronological.
    by_month = {}
    for i in sold:
        m = (i["sold_date"] or "")[:7]
        if len(m) == 7:
            by_month[m] = round(by_month.get(m, 0) + (i["profit"] or 0), 2)
    months = [{"month": k, "profit": by_month[k]} for k in sorted(by_month)]

    days = [i["days_held"] for i in sold if i["days_held"] is not None]
    ranked = sorted(sold, key=lambda i: i["profit"])
    def slim(i):
        return {"id": i["id"], "player": i["player"], "card_set": i["card_set"],
                "profit": i["profit"], "roi": i["roi"], "days_held": i["days_held"]}

    # Aging: in-stock/listed cards held longer than aging_days.
    from datetime import date
    today = date.today()
    aging = []
    for i in held:
        d = _days_held(i["purchase_date"], today.isoformat())
        if d is not None and d >= aging_days:
            aging.append({**slim(i), "days_in_stock": d, "status": i["status"], "cost": i["cost"]})
    aging.sort(key=lambda x: x["days_in_stock"], reverse=True)

    return {
        "summary": {
            "sold_count": len(sold),
            "total_profit": round(sum(i["profit"] or 0 for i in sold), 2),
            "avg_profit": round(sum(i["profit"] or 0 for i in sold) / len(sold), 2) if sold else 0,
            "avg_days_to_sell": round(sum(days) / len(days)) if days else None,
            "median_days_to_sell": round(median(days)) if days else None,
            "held_count": len(held),
        },
        "by_month": months,
        "by_teammate": group(sold, "bought_by"),
        "by_sport": group(sold, "sport"),
        "best": [slim(i) for i in ranked[-5:][::-1]],
        "worst": [slim(i) for i in ranked[:5] if i["profit"] < 0],
        "aging": aging[:20],
        "aging_days": aging_days,
    }


@app.get("/grade-roi")
async def grade_roi(query: str, fee: float = 25.0, gem_rate: float = 0.35,
                    _: bool = Depends(require_shop_access)):
    """Is a raw card worth grading? Compares raw vs PSA 10 and PSA 9 sold comps
    (all via the shared comp method, so the numbers agree with Card Prices / Deal
    Check) and, using an adjustable gem rate, returns an EXPECTED net plus the
    best-case (PSA 10) net. `query` = the card (year + set + player + parallel)."""
    import re
    q = (query or "").strip()
    if not q:
        raise HTTPException(400, "Enter a card to check.")
    gem = min(0.9, max(0.05, gem_rate))
    base = re.sub(r"\b(psa|bgs|sgc|cgc)\s*\d*(\.\d)?\b", "", q, flags=re.I)
    base = re.sub(r"\b(raw|gem\s*mint|gem\s*mt)\b", "", base, flags=re.I).strip()
    if not base:
        base = q
    # Same card words enforced for raw/9/10 (only the grade differs), so the
    # three medians are apples-to-apples for the exact card.
    raw_med, raw_n = _comp_median(await _card_comps(base, graded=False))
    ten_med, ten_n = _comp_median(await _card_comps(base, graded=True, grade_num="10", search=f"{base} PSA 10"))
    nine_med, nine_n = _comp_median(await _card_comps(base, graded=True, grade_num="9", search=f"{base} PSA 9"))

    best_net = mult = ev_val = ev_net = None
    if raw_med is not None and ten_med is not None:
        best_net = round(ten_med - raw_med - fee, 2)
        mult = round(ten_med / raw_med, 2) if raw_med else None
        # Outcome distribution: gem_rate -> PSA 10, then most of the rest a 9,
        # and a small tail (8 or lower) worth ~ the raw card back.
        p10 = gem
        p9 = (1 - gem) * 0.6
        plow = max(0.0, 1 - p10 - p9)
        nine_val = nine_med if nine_med is not None else round((ten_med + raw_med) / 2)
        ev_val = round(p10 * ten_med + p9 * nine_val + plow * raw_med)
        ev_net = round(ev_val - raw_med - fee, 2)
    verdict = None
    if ev_net is not None:
        verdict = "grade" if ev_net >= max(15, fee * 0.5) else ("maybe" if ev_net > 0 else "skip")
    return {
        "query": base, "fee": fee, "gem_rate": round(gem, 2),
        "raw_median": raw_med, "raw_comps": raw_n,
        "graded_median": ten_med, "graded_comps": ten_n,
        "nine_median": nine_med, "nine_comps": nine_n,
        "best_net": best_net, "multiplier": mult,
        "expected_value": ev_val, "expected_net": ev_net, "verdict": verdict,
    }


# --- New Releases: AI-parse a card checklist into a filterable, targetable sheet ---

_CHECKLIST_SYSTEM = (
    "You parse sports-card checklists into JSON. Return ONLY a JSON array (no prose). "
    "For each card include these keys: "
    "player (name/subject), card_number (string or null), "
    "parallel (color/parallel/variation name like 'Gold','Orange','Superfractor','Auto'; null for plain base), "
    "numbered_to (integer print run if serial-numbered e.g. /50 -> 50, else null), "
    "subset (insert/subset name or null), team (or null). "
    "If a section lists parallels that apply to the base cards, expand each card into its parallels. "
    "Keep card numbers verbatim (e.g. 'BCA-VW', '121')."
)


def _chunk_lines(text: str, max_chars: int = 3500) -> list:
    """Split checklist text into line-aligned chunks small enough that the AI's
    JSON output for each won't get truncated."""
    chunks, cur, cur_len = [], [], 0
    for ln in (text or "").splitlines():
        if cur and cur_len + len(ln) > max_chars:
            chunks.append("\n".join(cur)); cur, cur_len = [], 0
        cur.append(ln); cur_len += len(ln) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks or ([text] if (text or "").strip() else [])


def _salvage_json_objects(raw: str) -> list:
    """Pull card objects out of an AI response even if the JSON array was cut off
    mid-stream: try the whole array first, then recover each complete {...} object."""
    import json as _json, re as _re
    raw = raw or ""
    m = _re.search(r"\[.*\]", raw, _re.DOTALL)
    if m:
        try:
            v = _json.loads(m.group(0))
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        except Exception:
            pass
    out = []
    for om in _re.finditer(r"\{[^{}]*\}", raw, _re.DOTALL):  # card rows are flat objects
        try:
            o = _json.loads(om.group(0))
            if isinstance(o, dict):
                out.append(o)
        except Exception:
            continue
    return out


def _normalize_card_row(r: dict) -> dict:
    nt = r.get("numbered_to")
    try:
        nt = int(nt) if nt not in (None, "", "null") else None
    except Exception:
        nt = None
    return {
        "player": (r.get("player") or "").strip() or None,
        "card_number": (str(r.get("card_number")).strip() if r.get("card_number") not in (None, "") else None),
        "parallel": (r.get("parallel") or "").strip() or None,
        "numbered_to": nt,
        "subset": (r.get("subset") or "").strip() or None,
        "team": (r.get("team") or "").strip() or None,
    }


def _parse_checklist_ai(text: str) -> list:
    """Turn a raw checklist into structured card rows. Chunks large pastes so the
    AI output can't be silently truncated, salvages partial JSON, and dedupes."""
    import ai
    text = (text or "")[:40000]  # allow big pastes now that we chunk them
    out, seen = [], set()
    for chunk in _chunk_lines(text, 3500):
        if not chunk.strip():
            continue
        try:
            raw = ai.generate(chunk, system=_CHECKLIST_SYSTEM, max_tokens=4000)
        except Exception:
            continue
        for r in _salvage_json_objects(raw):
            row = _normalize_card_row(r)
            if not any(row.values()):
                continue
            key = (row["player"], row["card_number"], row["parallel"], row["numbered_to"])
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        if len(out) >= 4000:  # safety cap
            break
    return out


def _release_card_dict(c: ReleaseCard) -> dict:
    return {"id": c.id, "player": c.player, "card_number": c.card_number, "parallel": c.parallel,
            "numbered_to": c.numbered_to, "subset": c.subset, "team": c.team, "targeted": bool(c.targeted)}


def _release_product_dict(p: ReleaseProduct, count: int = 0) -> dict:
    return {"id": p.id, "name": p.name, "release_date": p.release_date, "card_count": count,
            "created_at": p.created_at.isoformat() if p.created_at else None}


class ReleaseParseRequest(BaseModel):
    name: str
    release_date: Optional[str] = None
    text: str


@app.post("/releases")
async def create_release(req: ReleaseParseRequest, db: AsyncSession = Depends(get_db),
                         _: bool = Depends(require_shop_access)):
    """Parse a pasted checklist into a product + its cards."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Give the product a name.")
    if not (req.text or "").strip():
        raise HTTPException(400, "Paste a checklist to parse.")
    cards = _parse_checklist_ai(req.text)
    if not cards:
        raise HTTPException(422, "Couldn't pull any cards from that text — paste a cleaner or smaller section, or use a calendar row's auto-build.")
    prod = ReleaseProduct(name=name, release_date=(req.release_date or "").strip() or None)
    db.add(prod)
    await db.flush()
    for c in cards:
        db.add(ReleaseCard(product_id=prod.id, **c))
    await db.commit()
    await db.refresh(prod)
    return {"product": _release_product_dict(prod, len(cards)), "cards": cards}


class ReleaseAutoFetchRequest(BaseModel):
    name: str
    url: str
    release_date: Optional[str] = None


@app.post("/releases/auto-fetch")
async def auto_fetch_release_checklist(req: ReleaseAutoFetchRequest, db: AsyncSession = Depends(get_db),
                                       _: bool = Depends(require_shop_access)):
    """Fetch a ChecklistInsider release page and parse the FULL checklist — every
    base + insert card (regex), plus the set-wide parallel ladder with print runs
    (AI). Creates a product + its cards."""
    from scrapers.releases import fetch_release_checklist, fetch_release_page_text
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "Missing product name.")
    # 1) Full card list from the HTML (every numbered base/insert card).
    try:
        cards = await fetch_release_checklist(req.url)
    except Exception as e:
        raise HTTPException(502, f"Couldn't fetch that release page: {e}")
    cards = cards[:2000]  # safety cap
    # 2) Parallel ladder (Gold /50, Superfractor 1/1, …) via AI — these are set-wide
    #    rows (no card number), which the base-card regex doesn't capture.
    try:
        import ai
        text = await fetch_release_page_text(req.url)
        for c in ai.parse_release_prose(text):
            if c.get("parallel") and not c.get("card_number"):
                cards.insert(0, c)
    except Exception:
        pass
    # 3) If the regex found nothing (unusual layout), fall back to the AI sample.
    if not cards:
        try:
            import ai
            cards = ai.parse_release_prose(await fetch_release_page_text(req.url))
        except Exception:
            cards = []
    if not cards:
        raise HTTPException(422, "Couldn't pull any cards from that page — try the paste-checklist box instead.")
    prod = ReleaseProduct(name=name, release_date=(req.release_date or "").strip() or None)
    db.add(prod)
    await db.flush()
    for c in cards:
        db.add(ReleaseCard(product_id=prod.id, **c))
    await db.commit()
    await db.refresh(prod)
    return {"product": _release_product_dict(prod, len(cards)), "cards": cards}


@app.get("/releases")
async def list_releases(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    res = await db.execute(select(ReleaseProduct).order_by(ReleaseProduct.created_at.desc()))
    prods = res.scalars().all()
    out = []
    for p in prods:
        cnt = len((await db.execute(select(ReleaseCard).where(ReleaseCard.product_id == p.id))).scalars().all())
        out.append(_release_product_dict(p, cnt))
    return out


@app.get("/releases/{product_id}")
async def get_release(product_id: int, db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    p = await db.get(ReleaseProduct, product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    res = await db.execute(select(ReleaseCard).where(ReleaseCard.product_id == product_id).order_by(ReleaseCard.id))
    return {"product": _release_product_dict(p), "cards": [_release_card_dict(c) for c in res.scalars().all()]}


class ReleaseCardUpdate(BaseModel):
    targeted: Optional[bool] = None


@app.put("/releases/card/{card_id}")
async def update_release_card(card_id: int, req: ReleaseCardUpdate, db: AsyncSession = Depends(get_db),
                              _: bool = Depends(require_shop_access)):
    c = await db.get(ReleaseCard, card_id)
    if not c:
        raise HTTPException(404, "Card not found")
    if req.targeted is not None:
        c.targeted = req.targeted
    await db.commit()
    return _release_card_dict(c)


@app.delete("/releases")
async def delete_all_releases(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    """Delete every parsed product and its cards."""
    await db.execute(sa_delete(ReleaseCard))
    await db.execute(sa_delete(ReleaseProduct))
    await db.commit()
    return {"deleted_all": True}


@app.delete("/releases/{product_id}")
async def delete_release(product_id: int, db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    await db.execute(sa_delete(ReleaseCard).where(ReleaseCard.product_id == product_id))
    p = await db.get(ReleaseProduct, product_id)
    if p:
        await db.delete(p)
    await db.commit()
    return {"deleted": True}


# --- Release calendar: product + street date, extracted from a screenshot (vision) ---

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _parse_release_date(text):
    """Best-effort parse of a date string into a date. Handles 'Jul 29, 2026',
    '7/29/2026', '2026-07-29', 'July 29'. Returns a date or None."""
    import re as _re
    from datetime import date as _date
    if not text:
        return None
    s = str(text).strip().lower()
    if s in ("tbd", "tba", "n/a", ""):
        return None
    m = _re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    m = _re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
    if m:
        y = int(m.group(3)); y += 2000 if y < 100 else 0
        try:
            return _date(y, int(m.group(1)), int(m.group(2)))
        except Exception:
            return None
    m = _re.search(r"([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?", s)
    if m and m.group(1)[:3] in _MONTHS:
        mo = _MONTHS[m.group(1)[:3]]
        d = int(m.group(2))
        if m.group(3):
            y = int(m.group(3))
        else:
            today = datetime.utcnow().date()
            y = today.year if mo >= today.month else today.year + 1
        try:
            return _date(y, mo, d)
        except Exception:
            return None
    return None


def _calendar_dict(r: ReleaseCalendar) -> dict:
    return {"id": r.id, "product": r.product,
            "release_date": r.release_date.isoformat() if r.release_date else None,
            "date_text": r.date_text, "sport": r.sport, "brand": r.brand,
            "source_url": r.source_url,
            "allocated": bool(getattr(r, "allocated", False)), "price": getattr(r, "price", None),
            "alloc_qty": getattr(r, "alloc_qty", None),
            "notify_days_before": r.notify_days_before,
            "notify_user_id": r.notify_user_id,
            "notified_at": r.notified_at.isoformat() if r.notified_at else None}


class CalendarParseRequest(BaseModel):
    image: str  # data URL (data:image/...;base64,...) of a release-calendar screenshot


class CalendarRow(BaseModel):
    product: str
    date: Optional[str] = None
    sport: Optional[str] = None
    brand: Optional[str] = None


class CalendarSaveRequest(BaseModel):
    releases: list[CalendarRow]


@app.post("/release-calendar/parse")
async def parse_release_calendar(req: CalendarParseRequest, _: bool = Depends(require_shop_access)):
    """Extract release rows (product + date) from a pasted calendar screenshot.
    Returns rows for review — does NOT save."""
    import ai
    if not req.image or "base64," not in req.image:
        raise HTTPException(400, "Send a screenshot as a data URL (data:image/...;base64,...).")
    try:
        rows = ai.parse_release_screenshot(req.image)
    except Exception as e:
        raise HTTPException(502, f"Couldn't read that screenshot: {e}")
    out = []
    for r in rows:
        dt = _parse_release_date(r.get("date"))
        out.append({
            "product": (r.get("product") or "").strip(),
            "date": r.get("date"),
            "release_date": dt.isoformat() if dt else None,
            "sport": (r.get("sport") or "").strip() or None,
            "brand": (r.get("brand") or "").strip() or None,
        })
    return {"releases": out, "count": len(out)}


@app.get("/news")
async def card_news():
    """Aggregated card-world news (Google News RSS: cards, auctions, pulls,
    releases, grading). Public — it's just a reading feed."""
    from scrapers.news import fetch_card_news
    try:
        items = await fetch_card_news()
    except Exception as e:
        raise HTTPException(502, f"Couldn't load news right now: {e}")
    return {"items": items, "count": len(items)}


@app.get("/release-calendar")
async def list_release_calendar(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    res = await db.execute(
        select(ReleaseCalendar).order_by(ReleaseCalendar.release_date.asc().nulls_last(), ReleaseCalendar.id.desc()))
    return [_calendar_dict(r) for r in res.scalars().all()]


@app.post("/release-calendar")
async def save_release_calendar(req: CalendarSaveRequest, db: AsyncSession = Depends(get_db),
                                _: bool = Depends(require_shop_access)):
    """Save reviewed calendar rows, skipping duplicates (same product + date)."""
    existing = await db.execute(select(ReleaseCalendar.product, ReleaseCalendar.date_text))
    seen = {((p or "").lower().strip(), (d or "").lower().strip()) for p, d in existing.all()}
    added = 0
    for row in req.releases:
        product = (row.product or "").strip()
        if not product:
            continue
        key = (product.lower(), (row.date or "").lower().strip())
        if key in seen:
            continue
        seen.add(key)
        db.add(ReleaseCalendar(
            product=product,
            release_date=_parse_release_date(row.date),
            date_text=(row.date or "").strip() or None,
            sport=(row.sport or "").strip() or None,
            brand=(row.brand or "").strip() or "Topps",
        ))
        added += 1
    if added:
        await db.commit()
    return {"added": added}


@app.delete("/release-calendar")
async def clear_release_calendar(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    """Delete every release-calendar row."""
    await db.execute(sa_delete(ReleaseCalendar))
    await db.commit()
    return {"deleted_all": True}


class ReleaseWaxRequest(BaseModel):
    allocated: Optional[bool] = None
    price: Optional[float] = None       # send 0 to clear
    alloc_qty: Optional[int] = None     # how many boxes/units allocated; send 0 to clear


@app.put("/release-calendar/{item_id}/wax")
async def set_release_wax(item_id: int, req: ReleaseWaxRequest, db: AsyncSession = Depends(get_db),
                          _: bool = Depends(require_shop_access)):
    """Set the wax allocation flag + our price + allocated quantity on a row."""
    r = await db.get(ReleaseCalendar, item_id)
    if not r:
        raise HTTPException(404, "Calendar item not found")
    if req.allocated is not None:
        r.allocated = req.allocated
    if req.price is not None:
        r.price = req.price if req.price > 0 else None
    if req.alloc_qty is not None:
        r.alloc_qty = req.alloc_qty if req.alloc_qty > 0 else None
    await db.commit()
    await db.refresh(r)
    return _calendar_dict(r)


class ReleaseReminderRequest(BaseModel):
    user_id: Optional[int] = None       # who to notify (from the Alerts tab)
    days_before: Optional[int] = None   # lead time; null/0 turns the reminder OFF


@app.put("/release-calendar/{item_id}/notify")
async def set_release_reminder(item_id: int, req: ReleaseReminderRequest,
                               db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    """Turn a pre-release reminder on/off for one calendar row. Sends via the
    user's alert method (email/SMS) `days_before` days before the release date."""
    r = await db.get(ReleaseCalendar, item_id)
    if not r:
        raise HTTPException(404, "Calendar item not found")
    if not req.days_before or req.days_before <= 0:
        r.notify_days_before = None
        r.notify_user_id = None
        r.notified_at = None
    else:
        if not req.user_id:
            raise HTTPException(400, "Set up your email/phone in the Alerts tab first.")
        user = await db.get(User, req.user_id)
        if not user or not (user.email or user.phone):
            raise HTTPException(400, "That user has no email or phone on file — set one in the Alerts tab.")
        r.notify_user_id = req.user_id
        r.notify_days_before = req.days_before
        r.notified_at = None  # re-arm
    await db.commit()
    await db.refresh(r)
    return _calendar_dict(r)


async def _check_release_calendar(db: AsyncSession) -> int:
    """Send pre-release reminders: for each calendar row with a reminder armed and
    a known date, notify once when today falls within its lead window. Returns count."""
    from datetime import date as _date, timedelta
    result = await db.execute(select(ReleaseCalendar).where(
        ReleaseCalendar.notify_days_before.isnot(None),
        ReleaseCalendar.release_date.isnot(None),
        ReleaseCalendar.notified_at.is_(None),
    ))
    rows = result.scalars().all()
    today = _date.today()
    sent = 0
    for r in rows:
        lead = r.notify_days_before or 0
        window_start = r.release_date - timedelta(days=lead)
        if window_start <= today <= r.release_date:
            user = await db.get(User, r.notify_user_id) if r.notify_user_id else None
            if user and (user.email or user.phone):
                days_out = (r.release_date - today).days
                send_release_alert(user, r.product, r.date_text or r.release_date.isoformat(),
                                    days_out, method=user.alert_method)
                r.notified_at = datetime.utcnow()
                sent += 1
    if sent:
        await db.commit()
    return sent


async def _import_upcoming_releases(db: AsyncSession) -> dict:
    """Fetch the upcoming-release calendar and insert rows not already present.
    Returns {"fetched", "added", "new": [ {product,date_text} ... ]}."""
    from scrapers.releases import fetch_upcoming_releases
    rows = await fetch_upcoming_releases()
    existing_rows = (await db.execute(select(ReleaseCalendar))).scalars().all()
    by_key = {((r.product or "").lower().strip(), (r.release_date.isoformat() if r.release_date else "")): r
              for r in existing_rows}
    seen = set(by_key.keys())
    new_items = []
    for r in rows:
        product = (r.get("product") or "").strip()
        if not product:
            continue
        rd = _parse_release_date(r.get("release_date"))
        key = (product.lower(), rd.isoformat() if rd else "")
        if key in seen:
            # backfill the checklist URL on an existing row that's missing it
            row = by_key.get(key)
            if row is not None and r.get("url") and not row.source_url:
                row.source_url = r.get("url")
            continue
        seen.add(key)
        db.add(ReleaseCalendar(
            product=product, release_date=rd, date_text=r.get("date_text"),
            sport=r.get("sport"), brand=r.get("brand") or "Topps",
            source_url=r.get("url"),
        ))
        new_items.append({"product": product, "date_text": r.get("date_text")})
    await db.commit()  # persist new rows AND any source_url backfills
    return {"fetched": len(rows), "added": len(new_items), "new": new_items}


class AutoImportRequest(BaseModel):
    notify_user_id: Optional[int] = None   # if set, enable "new release" notifications to this user


@app.post("/release-calendar/auto-import")
async def auto_import_releases(req: AutoImportRequest, db: AsyncSession = Depends(get_db),
                               _: bool = Depends(require_shop_access)):
    """Pull the upcoming-release calendar from the web and add anything new.
    If notify_user_id is set, future daily refreshes will notify that user when
    brand-new releases are announced."""
    from database import AppFlag
    try:
        res = await _import_upcoming_releases(db)
    except Exception as e:
        raise HTTPException(502, f"Couldn't fetch the release calendar right now: {e}")
    if req.notify_user_id:
        flag = await db.get(AppFlag, "release_notify_user")
        if flag:
            flag.value = str(req.notify_user_id)
        else:
            db.add(AppFlag(key="release_notify_user", value=str(req.notify_user_id)))
        # stamp the refresh time so the daily job doesn't immediately re-run
        rf = await db.get(AppFlag, "releases_last_refresh")
        val = json.dumps({"at": datetime.utcnow().isoformat()})
        if rf:
            rf.value = val
        else:
            db.add(AppFlag(key="releases_last_refresh", value=val))
        await db.commit()
    return {"fetched": res["fetched"], "added": res["added"], "notify_on": bool(req.notify_user_id)}


async def _record_scraper_health(db: AsyncSession, deep: bool = False) -> dict:
    """Check whether the ChecklistInsider source is still returning data and store
    the verdict. `deep` also parses a checklist page. Warns if the site changed."""
    from database import AppFlag
    from scrapers.releases import fetch_upcoming_releases, fetch_release_checklist
    status, detail, cal, chk = "ok", "Release source is responding normally.", 0, None
    try:
        rows = await fetch_upcoming_releases()
        cal = len(rows)
        if cal == 0:
            status, detail = "down", "Release calendar returned 0 rows — ChecklistInsider's layout likely changed."
        elif deep:
            url = next((r.get("url") for r in rows if r.get("url")), None)
            if url:
                try:
                    chk = len(await fetch_release_checklist(url))
                    if chk == 0:
                        status, detail = "degraded", "Calendar works, but a checklist page parsed 0 cards."
                except Exception as e:
                    status, detail = "degraded", f"Calendar works, but a checklist page failed to parse ({e})."
    except Exception as e:
        status, detail = "down", f"Release source unreachable/failed: {e}"
    payload = {"status": status, "detail": detail, "calendar_count": cal, "checklist_count": chk,
               "checked_at": datetime.utcnow().isoformat()}
    flag = await db.get(AppFlag, "release_scraper_health")
    if flag:
        flag.value = json.dumps(payload)
    else:
        db.add(AppFlag(key="release_scraper_health", value=json.dumps(payload)))
    await db.commit()
    return payload


@app.get("/release-calendar/health")
async def get_scraper_health(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    """Return the last stored release-source health (fast). Runs a fresh light check
    only if we've never checked."""
    from database import AppFlag
    flag = await db.get(AppFlag, "release_scraper_health")
    if flag and flag.value:
        try:
            return json.loads(flag.value)
        except Exception:
            pass
    return await _record_scraper_health(db, deep=False)


@app.post("/release-calendar/health")
async def scan_scraper_health(db: AsyncSession = Depends(get_db), _: bool = Depends(require_shop_access)):
    """Re-check the release source now (deep: calendar + a checklist page)."""
    return await _record_scraper_health(db, deep=True)


async def _maybe_refresh_releases(db: AsyncSession, min_hours: float = 24.0) -> int:
    """Once a day, auto-pull new upcoming releases; if a notify user is set, alert
    them about brand-new products. Returns count of new releases added."""
    from database import AppFlag
    from datetime import timedelta
    try:
        flag = await db.get(AppFlag, "releases_last_refresh")
        if flag and flag.value:
            last = datetime.fromisoformat(json.loads(flag.value).get("at"))
            if (datetime.utcnow() - last).total_seconds() < min_hours * 3600:
                return 0
    except Exception:
        pass
    try:
        res = await _import_upcoming_releases(db)
    except Exception as e:
        print(f"release auto-refresh failed: {e}")
        try:
            await _record_scraper_health(db, deep=False)  # note the outage
        except Exception:
            pass
        return 0
    # The daily pull just proved the source works — record health from it.
    try:
        await _record_scraper_health(db, deep=False)
    except Exception:
        pass
    # record the run time
    val = json.dumps({"at": datetime.utcnow().isoformat()})
    rf = await db.get(AppFlag, "releases_last_refresh")
    if rf:
        rf.value = val
    else:
        db.add(AppFlag(key="releases_last_refresh", value=val))
    await db.commit()
    # notify the watcher about new products
    if res["new"]:
        nf = await db.get(AppFlag, "release_notify_user")
        if nf and nf.value:
            user = await db.get(User, int(nf.value))
            if user and (user.email or user.phone):
                send_release_new_alert(user, res["new"], method=user.alert_method)
    return res["added"]


@app.delete("/release-calendar/{item_id}")
async def delete_release_calendar(item_id: int, db: AsyncSession = Depends(get_db),
                                  _: bool = Depends(require_shop_access)):
    r = await db.get(ReleaseCalendar, item_id)
    if not r:
        raise HTTPException(404, "Calendar item not found")
    await db.delete(r)
    await db.commit()
    return {"deleted": True}


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
    kind: Optional[str] = None  # "buy" | "sell"


def _caller_deal_dict(d: CallerDeal) -> dict:
    return {"id": d.id, "caller_name": d.caller_name, "description": d.description,
            "amount": d.amount, "kind": d.kind,
            "created_at": d.created_at.isoformat() if d.created_at else None}


@app.post("/caller-deals")
async def add_caller_deal(req: CallerDealRequest, db: AsyncSession = Depends(get_db),
                          _: bool = Depends(require_shop_access)):
    name = (req.caller_name or "").strip()
    desc = (req.description or "").strip()
    if not name or not desc:
        raise HTTPException(400, "Caller name and a deal description are required")
    kind = req.kind if req.kind in ("buy", "sell") else None
    d = CallerDeal(caller_name=name, description=desc, amount=req.amount, kind=kind)
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


# --- Tasks (shared team to-do board, gated by the Shops password) ---

class TaskRequest(BaseModel):
    text: str
    assigned_to: Optional[str] = None
    created_by: Optional[str] = None


class ChecklistItem(BaseModel):
    id: str
    text: str
    done: bool = False


class TaskUpdate(BaseModel):
    text: Optional[str] = None
    assigned_to: Optional[str] = None
    done: Optional[bool] = None
    checklist: Optional[list[ChecklistItem]] = None


def _task_dict(t: Task) -> dict:
    try:
        checklist = json.loads(t.checklist) if t.checklist else []
    except Exception:
        checklist = []
    try:
        chat = json.loads(t.chat) if t.chat else []
    except Exception:
        chat = []
    return {"id": t.id, "text": t.text, "assigned_to": t.assigned_to,
            "created_by": t.created_by, "done": bool(t.done),
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "checklist": checklist, "chat": chat}


@app.post("/tasks")
async def add_task(req: TaskRequest, db: AsyncSession = Depends(get_db),
                   _: bool = Depends(require_shop_access)):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "Task text is required")
    t = Task(text=text, assigned_to=_blank(req.assigned_to), created_by=_blank(req.created_by))
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return _task_dict(t)


@app.get("/tasks")
async def list_tasks(db: AsyncSession = Depends(get_db),
                     _: bool = Depends(require_shop_access)):
    res = await db.execute(select(Task).order_by(Task.created_at.desc()))
    return [_task_dict(t) for t in res.scalars().all()]


@app.put("/tasks/{task_id}")
async def update_task(task_id: int, req: TaskUpdate, db: AsyncSession = Depends(get_db),
                      _: bool = Depends(require_shop_access)):
    t = await db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    if req.text is not None:
        text = req.text.strip()
        if not text:
            raise HTTPException(400, "Task can't be empty")
        t.text = text
    if req.assigned_to is not None:
        t.assigned_to = _blank(req.assigned_to)
    if req.done is not None:
        t.done = req.done
        t.completed_at = datetime.utcnow() if req.done else None
    if req.checklist is not None:
        t.checklist = json.dumps([item.model_dump() for item in req.checklist])
    await db.commit()
    await db.refresh(t)
    return _task_dict(t)


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db),
                      _: bool = Depends(require_shop_access)):
    t = await db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    await db.delete(t)
    await db.commit()
    return {"deleted": True}


class TaskChatRequest(BaseModel):
    message: str


@app.post("/tasks/{task_id}/chat")
async def task_chat(task_id: int, req: TaskChatRequest, db: AsyncSession = Depends(get_db),
                    _: bool = Depends(require_shop_access)):
    """Per-task AI assistant. Appends the user's message, asks the model (with the
    task as context + recent history), saves the reply, and returns the updated task."""
    t = await db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(400, "Message is required")
    try:
        history = json.loads(t.chat) if t.chat else []
    except Exception:
        history = []
    history.append({"role": "user", "text": msg})

    convo = ""
    for m in history[-10:]:
        who = "User" if m.get("role") == "user" else "Assistant"
        convo += f"{who}: {m.get('text', '')}\n"
    convo = convo.rstrip()

    ctx = f'The task is: "{t.text}"'
    if t.assigned_to:
        ctx += f' (assigned to {t.assigned_to})'
    system = ("You are a hands-on assistant helping a sports-card dealer complete a single "
              f"to-do item on their team task board. {ctx}. Help them actually get it done: "
              "suggest concrete next steps, answer their questions, and draft any messages, "
              "texts, or emails they need. Be concise and practical.")
    try:
        import ai
        reply = ai.generate(convo, system=system, max_tokens=500)
    except Exception as e:
        reply = f"Sorry, I couldn't respond right now. ({e})"
    history.append({"role": "assistant", "text": reply})

    t.chat = json.dumps(history)
    await db.commit()
    await db.refresh(t)
    return _task_dict(t)


def serialize_shop(s: CardShop) -> dict:
    return {
        "id": s.id, "name": s.name, "website": s.website, "phone": s.phone,
        "full_address": s.full_address, "city": s.city, "state": s.state,
        "rating": s.rating, "reviews": s.reviews, "email": s.email,
        "instagram": s.instagram, "tiktok": s.tiktok, "whatnot": s.whatnot,
        "contact_way": s.contact_way, "contacted": s.contacted, "active": s.active,
        "contacted_by": s.contacted_by, "call_notes": s.call_notes,
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
    active: Optional[str] = None
    contacted_by: Optional[str] = None
    call_notes: Optional[str] = None
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
    active: Optional[str] = None,     # "yes" | "no"
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
    f = dict(q=q, state=state, city=city, contacted=contacted, active=active, shop_type=shop_type,
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
    # Shops are "active" unless explicitly marked "no".
    if f.get("active") == "no":
        stmt = stmt.where(CardShop.active == "no")
    elif f.get("active") == "yes":
        stmt = stmt.where(or_(CardShop.active.is_(None), CardShop.active != "no"))
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


# --- Persistent eBay call counter -----------------------------------------
# The scraper's live counter is in-memory (resets on every restart/redeploy).
# We mirror it into an app_flags row keyed by Pacific day so the daily total
# survives restarts: seed it on startup, flush it periodically + on read.

def _ebay_usage_key(day: str) -> str:
    return f"ebay_usage:{day}"


async def _seed_ebay_usage() -> None:
    """On startup, restore today's persisted eBay call count into the scraper."""
    from scrapers import ebay_scraper
    from database import AppFlag
    day = ebay_scraper._pacific_day()
    try:
        async with AsyncSessionLocal() as session:
            f = await session.get(AppFlag, _ebay_usage_key(day))
            if f and f.value:
                ebay_scraper.seed_usage(day, int(f.value))
    except Exception as e:
        print(f"eBay usage seed failed: {e}")


async def _flush_ebay_usage() -> dict:
    """Persist the in-memory count to the DB (never lowering the stored total)."""
    from scrapers import ebay_scraper
    from database import AppFlag
    st = ebay_scraper.usage_status()
    key = _ebay_usage_key(st["day"])
    async with AsyncSessionLocal() as session:
        f = await session.get(AppFlag, key)
        stored = int(f.value) if f and f.value else 0
        val = str(max(stored, st["calls"]))
        if not f:
            session.add(AppFlag(key=key, value=val))
        else:
            f.value = val
        await session.commit()
    return {**st, "calls": int(val), "remaining": max(0, st["cap"] - int(val))}


async def _ebay_usage_flusher() -> None:
    """Background loop: persist the counter once a minute so a restart loses
    at most ~60s of calls."""
    while True:
        await asyncio.sleep(60)
        try:
            await _flush_ebay_usage()
        except Exception as e:
            print(f"eBay usage flush failed: {e}")


@app.get("/ebay-usage")
async def ebay_usage(_: User = Depends(require_owner)):
    """How many eBay Browse API searches the site has made today (Pacific day),
    vs the daily safety cap. Persisted across restarts. Reading also flushes the
    current count to the DB."""
    return await _flush_ebay_usage()


@app.get("/next-alert-check")
async def next_alert_check(_: User = Depends(require_owner)):
    """Seconds until the next automatic eBay alert sweep (15-min scheduler heartbeat).
    Owner-only — for the Alerts-tab countdown."""
    now = _time.time()
    nxt = _alert_run.get("next_run")
    if not nxt or nxt <= now:
        # Between heartbeats or a run is due/in progress — estimate from last_run.
        last = _alert_run.get("last_run")
        nxt = (last + _ALERT_INTERVAL_S) if last else (now + _ALERT_INTERVAL_S)
    return {
        "seconds_remaining": max(0, int(round(nxt - now))),
        "interval_s": _ALERT_INTERVAL_S,
        "running": bool(_alert_run.get("running")),
    }


@app.get("/twilio-balance")
async def twilio_balance(me: User = Depends(require_owner)):
    """Remaining Twilio account balance (for the SMS-budget counter). Owner-only
    since it's account financial data."""
    import httpx
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        return {"available": False}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Balance.json",
                            auth=(sid, token))
        if r.status_code != 200:
            return {"available": False}
        d = r.json()
        return {"available": True, "balance": float(d.get("balance") or 0),
                "currency": d.get("currency") or "USD"}
    except Exception as e:
        print(f"twilio-balance error: {e}")
        return {"available": False}


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


@app.delete("/shops/{shop_id}")
async def delete_shop(shop_id: int, _: bool = Depends(require_shop_access), db: AsyncSession = Depends(get_db)):
    s = await db.get(CardShop, shop_id)
    if not s:
        raise HTTPException(404, "Shop not found")
    await db.delete(s)
    await db.commit()
    return {"deleted": True}


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
async def test_email(to: str, _: bool = Depends(require_shop_access)):
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
        "image_url": "https://placehold.co/600x800/png?text=Card+Finder+Test+Card",
    }
    analysis = {"verdict": "good_deal", "avg_sold_price": 150.0}
    send_alert(user, sample, analysis, method=user.alert_method, alert_label="(test alert)")

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

    # Effective check interval = fastest budget-safe rate (by unique searches),
    # capped at a 60-min ceiling, floored by the 15-min scheduler heartbeat.
    from alert_filters import min_interval_for, build_query, _ebay_keywords

    def _skey(s):
        if (getattr(s, "source", None) or "ebay") != "ebay":
            return ("nonebay", s.id)
        return (_ebay_keywords(build_query(s)), bool(getattr(s, "include_auctions", False)))

    unique_searches = len({_skey(s) for s in searches}) if searches else 0
    floor = max(min_interval_for(max(unique_searches, 1)), 60)
    effective_interval = max(floor, 15)

    checked_ats = [s.last_checked_at for s in searches if s.last_checked_at]
    never_checked = sum(1 for s in searches if not s.last_checked_at)
    most_recent = max(checked_ats) if checked_ats else None
    oldest = min(checked_ats) if checked_ats else None

    def mins_ago(dt):
        return round((now - dt).total_seconds() / 60, 1) if dt else None

    # "stale" = past due by >2x the effective interval (the scheduler isn't firing)
    stale = 0
    for s in searches:
        if not s.last_checked_at:
            continue
        if (now - s.last_checked_at).total_seconds() / 60 > effective_interval * 2:
            stale += 1

    users = {s.user_id for s in searches}
    contactable = 0
    has_phone, has_email = {}, {}
    if users:
        ures = await db.execute(select(User).where(User.id.in_(users)))
        for u in ures.scalars().all():
            if u.email or u.phone:
                contactable += 1
            has_phone[u.id] = bool(u.phone)
            has_email[u.id] = bool(u.email)

    # Breakdown by delivery method (only eBay/auction listing alerts, which send).
    by_method = {"email": 0, "sms": 0, "both": 0, "other": 0}
    sms_sending = 0   # alerts that actually text (method sms/both AND user has a phone) — these cost Twilio
    email_sending = 0
    for s in searches:
        m = (s.alert_method or "both").lower()
        by_method[m if m in by_method else "other"] += 1
        if m in ("sms", "both") and has_phone.get(s.user_id):
            sms_sending += 1
        if m in ("email", "both") and has_email.get(s.user_id):
            email_sending += 1

    pop_res = await db.execute(select(PopWatch).where(PopWatch.active == True))
    pop_watches = len(pop_res.scalars().all())

    # Alerts sent today (Pacific) + recent daily log
    from database import AppFlag
    from datetime import timedelta
    today = (now - timedelta(hours=7)).strftime("%Y-%m-%d")
    sflag = await db.get(AppFlag, "alerts_sent_log")
    sent_log = json.loads(sflag.value) if sflag and sflag.value else {}

    return {
        "active_searches": len(searches),
        "unique_searches": unique_searches,
        "effective_interval_min": effective_interval,
        "users_with_alerts": len(users),
        "users_contactable": contactable,
        "by_method": by_method,           # counts of alerts set to email / sms / both
        "sms_sending": sms_sending,       # alerts that actually text (cost Twilio $)
        "email_sending": email_sending,   # alerts that actually email (free via Brevo)
        "never_checked": never_checked,
        "stale_searches": stale,
        "most_recent_check_mins_ago": mins_ago(most_recent),
        "oldest_check_mins_ago": mins_ago(oldest),
        "active_pop_watches": pop_watches,
        "alerts_sent_today": sent_log.get(today, 0),
        "alerts_sent_recent": sent_log,
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
            "sheet_sync_all_tabs": True,  # Final + Sheet1 + Whatnot + Sheet5 (sellers)
        },
    }


@app.get("/test-send")
async def test_send(sms: bool = False, _: bool = Depends(require_shop_access)):
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
            "26buys@gmail.com",
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
