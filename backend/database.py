from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, Text, Numeric, Numeric
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
    password_hash = Column(String, nullable=True)  # pbkdf2 "salt$hash" for email+password login
    phone = Column(String, unique=True, nullable=True)
    carrier = Column(String, nullable=True)  # for free email-to-SMS texts
    extra_emails = Column(String, nullable=True)  # additional alert recipients, newline/comma-separated
    extra_phones = Column(String, nullable=True)  # additional alert SMS recipients, newline/comma-separated
    alert_method = Column(String, default="email")  # "email", "sms", or "both"
    digest = Column(Boolean, default=False)             # also send a once-a-day summary of the day's finds
    reset_code = Column(String, nullable=True)          # 6-digit password-reset code (hashed-not-needed, short-lived)
    reset_expires = Column(DateTime, nullable=True)     # when the reset code expires
    created_at = Column(DateTime, default=datetime.utcnow)


class AuthSession(Base):
    """A logged-in session. The token lives in the browser's localStorage and is
    sent as a Bearer header; it maps back to a user."""
    __tablename__ = "auth_sessions"
    token = Column(String, primary_key=True)
    user_id = Column(Integer, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)


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
    catch_misspellings = Column(Boolean, default=False)  # also search misspelled variants (eBay listings)
    deal_threshold_pct = Column(Integer, nullable=True)  # ebay: only alert if listing is >= N% below market
    folder = Column(String, nullable=True)  # optional group name to organize alerts
    include_auctions = Column(Boolean, default=False)  # also watch eBay auctions (off by default)
    check_interval_minutes = Column(Float, default=60.0)
    last_checked_at = Column(DateTime, nullable=True)
    alert_method = Column(String, default="both")  # "email", "sms", or "both"
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    alerts_sent_count = Column(Integer, default=0)      # lifetime alerts emailed for this search
    last_match_at = Column(DateTime, nullable=True)     # last time any listing passed the filters
    health_status = Column(String, nullable=True)       # "ok" | "narrow" | "dead" — from the daily health scan
    health_detail = Column(String, nullable=True)       # short explanation of the status
    health_checked_at = Column(DateTime, nullable=True)


class PopLookup(Base):
    """A saved Pop Report lookup (screenshot thumbnail + its result), per user."""
    __tablename__ = "pop_lookups"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    thumb = Column(Text)          # small downscaled data-URL of the screenshot
    result_json = Column(Text)    # the CardLookupResult, JSON-encoded
    created_at = Column(DateTime, default=datetime.utcnow)


class AppFlag(Base):
    __tablename__ = "app_flags"
    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)


class CallerNote(Base):
    """A timestamped note taken during a call, grouped by caller name. Shared
    team data (gated by the Shops password)."""
    __tablename__ = "caller_notes"
    id = Column(Integer, primary_key=True)
    caller_name = Column(String, index=True)
    caller_phone = Column(String, nullable=True)
    instagram = Column(String, nullable=True)
    facebook = Column(String, nullable=True)
    email = Column(String, nullable=True)
    category = Column(String, nullable=True)  # "breaker" | "shop" | None
    buys_wax = Column(Boolean, default=False)  # does this caller buy sealed wax?
    note = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class CallerDeal(Base):
    """A closed deal with a caller (what was bought/sold + optional amount)."""
    __tablename__ = "caller_deals"
    id = Column(Integer, primary_key=True)
    caller_name = Column(String, index=True)
    description = Column(String)
    amount = Column(Float, nullable=True)
    kind = Column(String, nullable=True)  # "buy" (we bought) | "sell" (we sold) | None
    created_at = Column(DateTime, default=datetime.utcnow)


class SmsConversation(Base):
    """A 1:1 SMS thread between the 877 business line and a customer, with an
    assigned team member who follows up. Shared (Shops-password gated)."""
    __tablename__ = "sms_conversations"
    phone = Column(String, primary_key=True)          # customer E.164
    name = Column(String, nullable=True)              # display name if known
    assigned_to = Column(String, nullable=True)       # display: combined teammate names
    assignee_phone = Column(String, nullable=True)    # display/back-compat: first teammate phone
    assignees = Column(Text, nullable=True)           # JSON list of {"name","phone"} follow-up teammates
    contact_type = Column(String, nullable=True)      # what they are: shop / breaker / collector / seller…
    location = Column(String, nullable=True)          # city/state
    email = Column(String, nullable=True)
    notes = Column(Text, nullable=True)               # free-text notes about this person
    last_at = Column(DateTime, default=datetime.utcnow)
    last_preview = Column(String, nullable=True)
    last_direction = Column(String, nullable=True)    # "in" | "out"
    unread = Column(Integer, default=0)               # inbound msgs since last viewed
    created_at = Column(DateTime, default=datetime.utcnow)


class SmsMessage(Base):
    """One SMS on the 877 line, inbound (from customer) or outbound (team/broadcast)."""
    __tablename__ = "sms_messages"
    id = Column(Integer, primary_key=True)
    phone = Column(String, index=True)                # customer E.164
    direction = Column(String)                        # "in" | "out"
    body = Column(Text)
    sender = Column(String, nullable=True)            # teammate name (outbound) or "broadcast"
    created_at = Column(DateTime, default=datetime.utcnow)


class BroadcastGroup(Base):
    """A saved, reusable audience for Broadcast (e.g. 'Whatnot buyers', 'Shop leads')."""
    __tablename__ = "broadcast_groups"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    folder = Column(String, nullable=True)   # optional category to organize groups
    created_at = Column(DateTime, default=datetime.utcnow)


class BroadcastContact(Base):
    """A phone (optionally named) saved inside a BroadcastGroup."""
    __tablename__ = "broadcast_contacts"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, index=True)
    phone = Column(String)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BroadcastLog(Base):
    """A record of a message blasted to a saved group — what was said, when, how many."""
    __tablename__ = "broadcast_logs"
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, index=True)
    message = Column(Text)
    sent_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class BroadcastTemplate(Base):
    """A saved, reusable broadcast message (e.g. 'New drop — DM for prices')."""
    __tablename__ = "broadcast_templates"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    body = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class ScheduledBroadcast(Base):
    """A broadcast queued to send at a future time. Dispatched by run-alert-check."""
    __tablename__ = "scheduled_broadcasts"
    id = Column(Integer, primary_key=True)
    recipients = Column(Text)                 # raw pasted phone blob
    message = Column(Text)
    image = Column(Text, nullable=True)       # optional MMS image as a data URL
    assignees = Column(Text, nullable=True)   # JSON [{name, phone}]
    save_as_group = Column(String, nullable=True)
    send_at = Column(DateTime, index=True)    # UTC
    status = Column(String, default="pending")  # pending | sent | canceled | failed
    result = Column(Text, nullable=True)      # summary after send
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)


class ReleaseProduct(Base):
    """A card product whose checklist was parsed (e.g. '2025-26 Bowman Chrome')."""
    __tablename__ = "release_products"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    release_date = Column(String, nullable=True)   # free text, e.g. "2025-11-05"
    created_at = Column(DateTime, default=datetime.utcnow)


class ReleaseCalendar(Base):
    """A row on the release calendar (product + street date), extracted from a
    screenshot the user pastes (Topps blocks server-side scraping). Feeds the
    'what's dropping & when' view; a row can seed a checklist parse."""
    __tablename__ = "release_calendar"
    id = Column(Integer, primary_key=True)
    product = Column(String)                        # "2026 Topps Chrome Baseball"
    release_date = Column(Date, nullable=True)      # parsed street date (for sorting/badges)
    date_text = Column(String, nullable=True)       # raw date as shown ("Jul 29", "TBD")
    sport = Column(String, nullable=True)
    brand = Column(String, default="Topps")
    source_url = Column(String, nullable=True)          # checklist page URL (for auto-checklist)
    allocated = Column(Boolean, default=False)          # wax: we have an allocation for this product
    price = Column(Float, nullable=True)                # wax: our allocation/target price per box
    alloc_qty = Column(Integer, nullable=True)          # wax: how many boxes/units allocated
    notify_user_id = Column(Integer, nullable=True)     # who to remind (User.id); null = no reminder
    notify_days_before = Column(Integer, nullable=True) # lead time in days; null = no reminder
    notified_at = Column(DateTime, nullable=True)       # set once the reminder has been sent
    created_at = Column(DateTime, default=datetime.utcnow)


class ReleaseCard(Base):
    """One card from a parsed checklist. `targeted` marks it for the go-after sheet."""
    __tablename__ = "release_cards"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, index=True)
    player = Column(String, nullable=True)
    card_number = Column(String, nullable=True)
    parallel = Column(String, nullable=True)
    numbered_to = Column(Integer, nullable=True)
    subset = Column(String, nullable=True)
    team = Column(String, nullable=True)
    targeted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Task(Base):
    """A shared to-do item for the team (gated by the Shops password). Anyone on
    the 26buys account can add a task and assign it to a teammate by name."""
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True)
    text = Column(String)
    assigned_to = Column(String, nullable=True)   # who should do it (free text, blank = anyone)
    created_by = Column(String, nullable=True)     # who added it
    done = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    # Optional checklist of sub-parts: JSON list of {"id","text","done"}.
    checklist = Column(Text, nullable=True)
    # Per-task AI assistant history: JSON list of {"role","text"}.
    chat = Column(Text, nullable=True)


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


class SentAlert(Base):
    """One row per alert email/text actually sent — the audit log of finds."""
    __tablename__ = "sent_alerts"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    search_id = Column(Integer, nullable=True)
    query = Column(String, nullable=True)        # the alert's query (label)
    title = Column(String, nullable=True)        # card listing title
    price = Column(Float, nullable=True)
    listing_url = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    verdict = Column(String, nullable=True)      # great_deal / auction / …
    pct_vs_market = Column(Float, nullable=True)  # deal score
    is_auction = Column(Boolean, default=False)
    sent_at = Column(DateTime, default=datetime.utcnow)


class WatchedAuction(Base):
    """A live eBay auction a user starred — we text them ~30 min before it ends."""
    __tablename__ = "watched_auctions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    external_id = Column(String, nullable=True)   # eBay itemId
    title = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    listing_url = Column(String, nullable=True)
    price = Column(Float, nullable=True)           # current bid when watched
    end_date = Column(String, nullable=True)       # ISO auction end time
    notified = Column(Boolean, default=False)      # reminder already sent
    created_at = Column(DateTime, default=datetime.utcnow)


class WaxTracked(Base):
    """A sealed box the team is tracking on the Wax Ladder. Each tracked box gets
    a daily price snapshot so we build a true dated price history (a real ladder)."""
    __tablename__ = "wax_tracked"
    id = Column(Integer, primary_key=True)
    box_key = Column(String, unique=True, index=True)   # normalized query (dedupe key)
    query = Column(String)                               # the search string we snapshot
    added_by = Column(String, nullable=True)
    target_price = Column(Float, nullable=True)          # alert when median drops to/below this
    target_hit_day = Column(String, nullable=True)       # Pacific day we last alerted (dedupe)
    created_at = Column(DateTime, default=datetime.utcnow)


class WaxSnapshot(Base):
    """One day's price reading for a tracked box — the points on the ladder chart."""
    __tablename__ = "wax_snapshots"
    id = Column(Integer, primary_key=True)
    box_key = Column(String, index=True)
    day = Column(String, index=True)     # YYYY-MM-DD (Pacific) — one per box per day
    median = Column(Float, nullable=True)
    avg = Column(Float, nullable=True)
    min = Column(Float, nullable=True)
    max = Column(Float, nullable=True)
    count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class PopWatch(Base):
    """Watch a single graded card (by PSA cert number) and alert the user when
    its population increases — i.e. another copy of that exact card+grade gets
    graded. Useful for 'pop 1' cards in a live auction."""
    __tablename__ = "pop_watches"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    cert_number = Column(String)            # PSA cert number being tracked
    label = Column(String, nullable=True)   # e.g. "2023 Topps Chrome Wembanyama #1 PSA 10"
    grade = Column(String, nullable=True)   # e.g. "PSA 10"
    last_population = Column(Integer, nullable=True)         # pop at this exact grade
    last_population_higher = Column(Integer, nullable=True)  # # graded higher
    auction_url = Column(String, nullable=True)             # optional listing being watched
    auction_ends_at = Column(DateTime, nullable=True)       # optional — stop watching after this
    check_interval_minutes = Column(Float, default=60.0)
    last_checked_at = Column(DateTime, nullable=True)
    alert_method = Column(String, default="both")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PortfolioCard(Base):
    """A card the user owns (their inventory). We value it against eBay sold
    comps so they can see total portfolio value + gain/loss vs what they paid."""
    __tablename__ = "portfolio_cards"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    name = Column(String)                       # search text, e.g. "2023 Prizm Wembanyama Silver PSA 10"
    paid = Column(Float, nullable=True)         # cost basis per card
    qty = Column(Integer, default=1)
    notes = Column(String, nullable=True)
    market_value = Column(Float, nullable=True)  # cached median of sold comps (per card)
    comps = Column(Integer, nullable=True)       # how many comps backed the value
    valued_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class InventoryItem(Base):
    """A single card the team owns/flipped — manual buy/sell ledger with profit.
    Shared by the 26buys account (gated by the Shops password), not per-user."""
    __tablename__ = "inventory_items"
    id = Column(Integer, primary_key=True)
    image = Column(Text, nullable=True)          # base64 data URL of the card photo
    sport = Column(String, nullable=True)
    player = Column(String, nullable=True)
    card_set = Column(String, nullable=True)     # the set (e.g. "2023 Prizm")
    grade = Column(String, nullable=True)        # e.g. "PSA 10", "Raw"
    cost = Column(Float, nullable=True)          # what we paid
    bought_by = Column(String, nullable=True)    # which teammate bought it
    purchase_date = Column(String, nullable=True)  # YYYY-MM-DD
    status = Column(String, default="in_stock")  # in_stock | listed | sold
    listing_url = Column(String, nullable=True)  # where it's currently listed
    sold = Column(Boolean, default=False)        # kept in sync with status == sold
    sale_price = Column(Float, nullable=True)    # what it sold for (gross)
    fees = Column(Float, nullable=True)          # platform/selling fees
    shipping = Column(Float, nullable=True)      # shipping cost we ate
    sold_date = Column(String, nullable=True)    # YYYY-MM-DD
    notes = Column(String, nullable=True)
    market_value = Column(Float, nullable=True)   # cached eBay sold-median estimate
    market_comps = Column(Integer, nullable=True) # how many comps backed the value
    valued_at = Column(DateTime, nullable=True)   # when we last valued it
    created_at = Column(DateTime, default=datetime.utcnow)


class SellerWatch(Base):
    """Watch a specific eBay seller — alert the user when that seller posts new
    listings. `seen_ids` is a JSON list of item ids already alerted on."""
    __tablename__ = "seller_watches"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    seller_name = Column(String)
    label = Column(String, nullable=True)      # optional note
    seen_ids = Column(Text, nullable=True)     # JSON list of external_ids already seen
    last_checked_at = Column(DateTime, nullable=True)
    alert_method = Column(String, default="both")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


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
    contacted = Column(String, nullable=True)         # set = we've contacted them (flag)
    active = Column(String, nullable=True)            # "no" = shop is not active; else active
    contacted_by = Column(String, nullable=True)      # who on our team contacted them
    call_notes = Column(Text, nullable=True)          # notes from our call(s)
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
    "email", "instagram", "tiktok", "whatnot", "contact_way", "contacted", "active",
    "contacted_by", "call_notes",
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
    user_cols = {c["name"] for c in insp.get_columns("users")}
    if "password_hash" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR"))
    if "extra_emails" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN extra_emails VARCHAR"))
    if "extra_phones" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN extra_phones VARCHAR"))
    if "reset_code" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN reset_code VARCHAR"))
    if "reset_expires" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN reset_expires TIMESTAMP"))
    if "digest" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN digest BOOLEAN DEFAULT FALSE"))

    try:
        note_cols = {c["name"] for c in insp.get_columns("caller_notes")}
        for col in ("instagram", "facebook", "email", "category"):
            if col not in note_cols:
                conn.execute(text(f"ALTER TABLE caller_notes ADD COLUMN {col} VARCHAR"))
        if "buys_wax" not in note_cols:
            conn.execute(text("ALTER TABLE caller_notes ADD COLUMN buys_wax BOOLEAN DEFAULT FALSE"))
    except Exception:
        pass  # table may not exist yet on a fresh DB; create_all handles it

    try:
        deal_cols = {c["name"] for c in insp.get_columns("caller_deals")}
        if "kind" not in deal_cols:
            conn.execute(text("ALTER TABLE caller_deals ADD COLUMN kind VARCHAR"))
    except Exception:
        pass

    try:
        cal_cols = {c["name"] for c in insp.get_columns("release_calendar")}
        if "notify_user_id" not in cal_cols:
            conn.execute(text("ALTER TABLE release_calendar ADD COLUMN notify_user_id INTEGER"))
        if "notify_days_before" not in cal_cols:
            conn.execute(text("ALTER TABLE release_calendar ADD COLUMN notify_days_before INTEGER"))
        if "notified_at" not in cal_cols:
            conn.execute(text("ALTER TABLE release_calendar ADD COLUMN notified_at TIMESTAMP"))
        if "source_url" not in cal_cols:
            conn.execute(text("ALTER TABLE release_calendar ADD COLUMN source_url VARCHAR"))
        if "allocated" not in cal_cols:
            conn.execute(text("ALTER TABLE release_calendar ADD COLUMN allocated BOOLEAN DEFAULT FALSE"))
        if "price" not in cal_cols:
            conn.execute(text("ALTER TABLE release_calendar ADD COLUMN price FLOAT"))
        if "alloc_qty" not in cal_cols:
            conn.execute(text("ALTER TABLE release_calendar ADD COLUMN alloc_qty INTEGER"))
    except Exception:
        pass  # table may not exist yet on a fresh DB; create_all handles it

    try:
        task_cols = {c["name"] for c in insp.get_columns("tasks")}
        if "checklist" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN checklist VARCHAR"))
        if "chat" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN chat VARCHAR"))
    except Exception:
        pass

    try:
        sc_cols = {c["name"] for c in insp.get_columns("sms_conversations")}
        if "assignees" not in sc_cols:
            conn.execute(text("ALTER TABLE sms_conversations ADD COLUMN assignees VARCHAR"))
        for col in ("contact_type", "location", "email", "notes"):
            if col not in sc_cols:
                conn.execute(text(f"ALTER TABLE sms_conversations ADD COLUMN {col} VARCHAR"))
    except Exception:
        pass

    try:
        bg_cols = {c["name"] for c in insp.get_columns("broadcast_groups")}
        if "folder" not in bg_cols:
            conn.execute(text("ALTER TABLE broadcast_groups ADD COLUMN folder VARCHAR"))
    except Exception:
        pass  # table may not exist yet on a fresh DB; create_all handles it

    try:
        inv_cols = {c["name"] for c in insp.get_columns("inventory_items")}
        if "status" not in inv_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN status VARCHAR DEFAULT 'in_stock'"))
            conn.execute(text("UPDATE inventory_items SET status = CASE WHEN sold THEN 'sold' ELSE 'in_stock' END WHERE status IS NULL"))
        if "listing_url" not in inv_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN listing_url VARCHAR"))
        if "fees" not in inv_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN fees FLOAT"))
        if "shipping" not in inv_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN shipping FLOAT"))
        if "market_value" not in inv_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN market_value FLOAT"))
        if "market_comps" not in inv_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN market_comps INTEGER"))
        if "valued_at" not in inv_cols:
            conn.execute(text("ALTER TABLE inventory_items ADD COLUMN valued_at TIMESTAMP"))
    except Exception:
        pass  # table may not exist yet on a fresh DB; create_all handles it

    try:
        wt_cols = {c["name"] for c in insp.get_columns("wax_tracked")}
        if "target_price" not in wt_cols:
            conn.execute(text("ALTER TABLE wax_tracked ADD COLUMN target_price FLOAT"))
        if "target_hit_day" not in wt_cols:
            conn.execute(text("ALTER TABLE wax_tracked ADD COLUMN target_hit_day VARCHAR"))
    except Exception:
        pass  # table may not exist yet on a fresh DB; create_all handles it

    existing = {c["name"] for c in insp.get_columns("card_shops")}
    if "shop_type" not in existing:
        conn.execute(text("ALTER TABLE card_shops ADD COLUMN shop_type VARCHAR"))
        conn.execute(text("UPDATE card_shops SET shop_type = 'shop' WHERE shop_type IS NULL"))
    if "contacted_by" not in existing:
        conn.execute(text("ALTER TABLE card_shops ADD COLUMN contacted_by VARCHAR"))
    if "call_notes" not in existing:
        conn.execute(text("ALTER TABLE card_shops ADD COLUMN call_notes VARCHAR"))
    if "active" not in existing:
        conn.execute(text("ALTER TABLE card_shops ADD COLUMN active VARCHAR"))

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
    if "catch_misspellings" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN catch_misspellings BOOLEAN DEFAULT FALSE"))
    if "deal_threshold_pct" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN deal_threshold_pct INTEGER"))
    if "folder" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN folder VARCHAR"))
    if "include_auctions" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN include_auctions BOOLEAN DEFAULT FALSE"))
    if "alerts_sent_count" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN alerts_sent_count INTEGER DEFAULT 0"))
    if "last_match_at" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN last_match_at TIMESTAMP"))
    if "health_status" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN health_status VARCHAR"))
    if "health_detail" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN health_detail VARCHAR"))
    if "health_checked_at" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN health_checked_at TIMESTAMP"))


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
