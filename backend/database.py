from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, Text, Numeric, UniqueConstraint
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


# How long a relisted card stays suppressed. A seller who relists the same card
# months later at a different price is genuinely new news; same card back within
# this window is the same card.
RELIST_WINDOW_DAYS = 30

_AUCTION_TAG = __import__("re").compile(r"^[^\w]*\[auction\]\s*", __import__("re").I)


def relist_key_for(title, seller_name):
    """Identity of the physical card: seller + normalized title.

    A relist gets a brand-new eBay item id and URL, so item-id dedup can't see
    it. Seller is required, and that requirement is the safety rail — two
    DIFFERENT sellers listing the same card are two real opportunities and must
    both alert; only the same seller re-posting the same title is a relist.

    Returns "" when either part is missing, and callers treat "" as "can't
    judge, send it" — a missed duplicate is a far cheaper mistake here than a
    suppressed find.
    """
    import re
    t = _AUCTION_TAG.sub("", str(title or ""))       # our own "🔨 [Auction] " prefix
    t = re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
    seller = str(seller_name or "").strip().lower()
    if not t or not seller:
        return ""
    return f"{seller}|{t}"


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
    # Only alert on the players in alert_filters.PLAYER_ALLOWLIST. Per-user, so
    # one account narrowing its focus never silences another's alerts.
    player_filter = Column(Boolean, default=False)
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
    # Always on. Misspelling tolerance is unconditional in passes_filters; the
    # column is kept so existing rows/queries don't break.
    catch_misspellings = Column(Boolean, default=True)
    deal_threshold_pct = Column(Integer, nullable=True)  # ebay: only alert if listing is >= N% below market
    folder = Column(String, nullable=True)  # optional group name to organize alerts
    include_auctions = Column(Boolean, default=False)  # also watch eBay auctions (off by default)
    # New-release watch: check as fast as the scheduler allows and never get
    # slowed down to fit the eBay budget — the stretch falls on normal alerts
    # instead. A fresh release is the one window where minutes actually matter.
    priority = Column(Boolean, default=False)
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
    image = Column(Text, nullable=True)               # MMS picture as a data URL, either direction
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


class ChecklistUpload(Base):
    """A checklist parsed from an uploaded Beckett-style .xlsx. Distinct from the
    Releases target-sheet: this feeds the Checklists tab (upload -> AI search ->
    push matches to alerts)."""
    __tablename__ = "checklist_uploads"
    id = Column(Integer, primary_key=True)
    name = Column(String)                           # product name (defaults to filename)
    filename = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChecklistCard(Base):
    """One card from an uploaded checklist."""
    __tablename__ = "checklist_cards"
    id = Column(Integer, primary_key=True)
    upload_id = Column(Integer, index=True)
    player = Column(String, nullable=True)
    card_number = Column(String, nullable=True)
    parallel = Column(String, nullable=True)
    numbered_to = Column(Integer, nullable=True)
    subset = Column(String, nullable=True)
    team = Column(String, nullable=True)
    rookie = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChecklistSavedSearch(Base):
    """A named, reusable search saved inside a checklist. Stores the resolved
    filter so re-running is instant (no AI call needed)."""
    __tablename__ = "checklist_saved_searches"
    id = Column(Integer, primary_key=True)
    upload_id = Column(Integer, index=True)
    name = Column(String)
    query = Column(Text, nullable=True)         # the original plain-English request
    filter_json = Column(Text, nullable=True)   # the resolved filter, JSON-encoded
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


class AlertSeen(Base):
    """One row per (saved search, listing) already evaluated for an alert.

    This is the alert dedup key. It used to live in CardListing, matched on
    external_id + source alone — so whichever search saw a listing first
    consumed it for every OTHER search and every other user, even when that
    first search never sent anything (baseline first check, price floor, deal
    threshold). Overlapping alerts on a hot release silently cannibalized each
    other. Scoping the key to search_id means each alert decides independently.
    """
    __tablename__ = "alert_seen"
    __table_args__ = (UniqueConstraint("search_id", "source", "external_id",
                                       name="uq_alert_seen_search_listing"),)
    id = Column(Integer, primary_key=True)
    search_id = Column(Integer, index=True)
    source = Column(String)
    external_id = Column(String, index=True)
    seen_at = Column(DateTime, default=datetime.utcnow)


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
    # The eBay item id this alert was about. Used to guarantee a user is told
    # about a given card ONCE, even when several of their alerts all match it.
    external_id = Column(String, nullable=True, index=True)
    seller_name = Column(String, nullable=True)
    # seller + normalized title. A relisted card keeps neither its item id nor
    # its listing URL, so external_id alone can't recognise it the second time.
    relist_key = Column(String, nullable=True, index=True)
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
    kind = Column(String, default="box")                # "box" | "card"
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
    call_recap = Column(Text, nullable=True)          # summary of the intro call
    contact_name = Column(String, nullable=True)      # name of the person we contacted AT the shop
    contact_phone = Column(String, nullable=True)     # that contact person's direct number
    topps_fanatics = Column(String, nullable=True)
    tcg_account = Column(String, nullable=True)
    buys_wholesale = Column(String, nullable=True)
    willing_to_wholesale = Column(String, nullable=True)
    collectors = Column(String, nullable=True)
    shop_type = Column(String, default="shop")      # "shop" | "whatnot_breaker"
    list_name = Column(String, default="main", index=True)  # "main" (Shops tab) | "tcg" (TCG Shops List tab)
    # --- open/sells-sports-cards check (see places_verify.py) ---
    verification_status = Column(String, nullable=True)  # "Verified (Google)" | "Confirmed Closed" | ...
    last_verified = Column(String, nullable=True)        # ISO date of the last check
    place_id = Column(String, nullable=True)             # Google Places id, so re-checks skip the search
    google_maps_url = Column(String, nullable=True)
    sells_sports_cards = Column(String, nullable=True)   # "yes" | "no" | "unknown"
    products_note = Column(Text, nullable=True)          # what the check saw it selling
    notes = Column(Text, nullable=True)            # running free-text log
    update_log = Column(Text, nullable=True)        # JSON history of AI updates
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Fields the AI update box / manual edits may write to (keeps routes & prompts in sync)
SHOP_EDITABLE_FIELDS = [
    "name", "website", "phone", "full_address", "city", "state", "rating", "reviews",
    "email", "instagram", "tiktok", "whatnot", "contact_way", "contacted", "active",
    "contacted_by", "call_notes", "call_recap", "contact_name", "contact_phone",
    "topps_fanatics", "tcg_account", "buys_wholesale", "willing_to_wholesale",
    "collectors", "notes",
]


class MasterShop(Base):
    """The 'New Shops List' — the Sports Card Shop Master Database, two-way synced
    with a Google Sheet. `record_id` (the sheet's 'Record ID', e.g. R-0001) is the
    stable key that maps each sheet row to a DB row. Sheet-owned columns mirror the
    sheet; the site-owned block (contacted/contact_name/… ) lives only here and is
    never written back over sheet columns."""
    __tablename__ = "master_shops"
    id = Column(Integer, primary_key=True)
    record_id = Column(String, unique=True, index=True)  # sheet 'Record ID' (R-0001)
    # --- identity / location ---
    name = Column(String, index=True)
    owner_name = Column(String, nullable=True)
    store_type = Column(String, nullable=True)
    street_address = Column(String, nullable=True)
    city = Column(String, nullable=True, index=True)
    state = Column(String, nullable=True, index=True)
    zip_code = Column(String, nullable=True)
    county = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    metro_area = Column(String, nullable=True)
    # --- contact / web ---
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)
    facebook = Column(String, nullable=True)
    instagram = Column(String, nullable=True)
    twitter = Column(String, nullable=True)
    youtube = Column(String, nullable=True)
    ebay_store = Column(String, nullable=True)
    whatnot = Column(String, nullable=True)
    google_maps_url = Column(String, nullable=True)
    google_rating = Column(Float, nullable=True)
    num_reviews = Column(Integer, nullable=True)
    # --- profile / flags (stored as sheet text, usually "Yes"/blank) ---
    years_in_business = Column(String, nullable=True)
    store_hours = Column(String, nullable=True)
    appointment_only = Column(String, nullable=True)
    buying_cards = Column(String, nullable=True)
    selling_wax = Column(String, nullable=True)
    high_end = Column(String, nullable=True)
    pokemon = Column(String, nullable=True)
    sports_cards = Column(String, nullable=True)
    tcg_other = Column(String, nullable=True)
    memorabilia = Column(String, nullable=True)
    autograph_auth = Column(String, nullable=True)
    psa_dealer = Column(String, nullable=True)
    beckett_dealer = Column(String, nullable=True)
    sgc_dealer = Column(String, nullable=True)
    cgc_dealer = Column(String, nullable=True)
    comc_partner = Column(String, nullable=True)
    card_show_vendor = Column(String, nullable=True)
    price_tier = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    data_sources = Column(String, nullable=True)
    last_verified = Column(String, nullable=True)
    verification_status = Column(String, nullable=True)
    confidence_score = Column(Integer, nullable=True)
    place_id = Column(String, nullable=True)        # Google Places id, so re-checks skip the search
    duplicate_check_id = Column(String, nullable=True)
    # --- site-owned (never overwritten by the sheet) ---
    contacted = Column(String, nullable=True)
    contacted_by = Column(String, nullable=True)
    contact_name = Column(String, nullable=True)
    contact_phone = Column(String, nullable=True)
    call_notes = Column(Text, nullable=True)
    call_recap = Column(Text, nullable=True)       # summary of the intro call
    active = Column(String, nullable=True)
    moved_to_tcg = Column(String, nullable=True)   # "yes" = copied to the TCG Shops List, hidden here
    # Our own answer, kept separate from the sheet-owned `sports_cards` column so a
    # check can never overwrite what someone typed in the Google Sheet.
    sells_sports_cards = Column(String, nullable=True)   # "yes" | "no" | "unknown"
    products_note = Column(Text, nullable=True)
    # --- sync bookkeeping ---
    sheet_row = Column(Integer, nullable=True)     # 1-based row in the sheet (fast writes)
    synced_at = Column(DateTime, nullable=True)    # last sheet<->db reconcile
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VFileCard(Base):
    """One contact card filed into a day's "V File" — the running batch built up
    while working the shop lists, sent out at end of day as a single multi-contact
    .vcf that a phone imports in one go.

    The card fields are a SNAPSHOT taken when it was filed, not a live reference to
    the shop: editing (or deleting) the shop afterwards must not silently rewrite a
    card that has already been filed or sent. `source` + `shop_id` are kept only so
    the same shop can't be filed twice in one day."""
    __tablename__ = "vfile_cards"
    id = Column(Integer, primary_key=True)
    day = Column(String, index=True)          # 'YYYY-MM-DD' in the filer's local time
    source = Column(String, nullable=True)    # "main" | "tcg" (card_shops) | "master"
    shop_id = Column(Integer, nullable=True)
    # --- snapshot of the card ---
    store = Column(String)
    owner = Column(String, nullable=True)
    contact_name = Column(String, nullable=True)
    number = Column(String, nullable=True)
    email = Column(String, nullable=True)
    state = Column(String, nullable=True)
    city = Column(String, nullable=True)
    address = Column(String, nullable=True)
    ig = Column(String, nullable=True)
    website = Column(String, nullable=True)
    recap = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Soft delete. Removing a card — and especially clearing a whole day — must be
    # undoable: a day's file is an hour of someone's work and there is no other
    # record of what was in it.
    deleted_at = Column(DateTime, nullable=True, index=True)


# sheet header (lowercased/trimmed) -> MasterShop attribute. Header-based so the
# sheet can add/reorder columns without breaking the sync. Site-owned fields and
# sync bookkeeping are intentionally NOT here.
MASTER_SHEET_MAP = {
    "record id": "record_id",
    "shop name": "name",
    "owner name": "owner_name",
    "store type": "store_type",
    "street address": "street_address",
    "city": "city",
    "state": "state",
    "zip code": "zip_code",
    "county": "county",
    "latitude": "latitude",
    "longitude": "longitude",
    "metro area": "metro_area",
    "phone number": "phone",
    "email": "email",
    "website": "website",
    "facebook": "facebook",
    "instagram": "instagram",
    "x (twitter)": "twitter",
    "youtube": "youtube",
    "ebay store": "ebay_store",
    "whatnot": "whatnot",
    "google maps url": "google_maps_url",
    "google rating": "google_rating",
    "number of reviews": "num_reviews",
    "years in business": "years_in_business",
    "store hours": "store_hours",
    "appointment only?": "appointment_only",
    "buying cards?": "buying_cards",
    "selling sealed wax?": "selling_wax",
    "high-end inventory?": "high_end",
    "pokemon": "pokemon",
    "sports cards": "sports_cards",
    "tcg (other)": "tcg_other",
    "memorabilia": "memorabilia",
    "autograph auth. services": "autograph_auth",
    "psa dealer?": "psa_dealer",
    "beckett dealer?": "beckett_dealer",
    "sgc dealer?": "sgc_dealer",
    "cgc dealer?": "cgc_dealer",
    "comc partner?": "comc_partner",
    "card show vendor?": "card_show_vendor",
    "est. price tier (1-5)": "price_tier",
    "notes": "notes",
    "data source(s)": "data_sources",
    "last verified date": "last_verified",
    "verification status": "verification_status",
    "confidence score (0-100)": "confidence_score",
    "duplicate check id": "duplicate_check_id",
}
# Numeric fields (parsed/formatted specially during sync).
MASTER_NUMERIC = {"latitude", "longitude", "google_rating", "num_reviews", "confidence_score"}


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
    if "player_filter" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN player_filter BOOLEAN DEFAULT FALSE"))

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
        msg_cols = {c["name"] for c in insp.get_columns("sms_messages")}
        if "image" not in msg_cols:
            conn.execute(text("ALTER TABLE sms_messages ADD COLUMN image TEXT"))
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
        if "kind" not in wt_cols:
            conn.execute(text("ALTER TABLE wax_tracked ADD COLUMN kind VARCHAR DEFAULT 'box'"))
            conn.execute(text("UPDATE wax_tracked SET kind = 'box' WHERE kind IS NULL"))
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
    if "contact_name" not in existing:
        conn.execute(text("ALTER TABLE card_shops ADD COLUMN contact_name VARCHAR"))
    if "contact_phone" not in existing:
        conn.execute(text("ALTER TABLE card_shops ADD COLUMN contact_phone VARCHAR"))
    if "call_recap" not in existing:
        conn.execute(text("ALTER TABLE card_shops ADD COLUMN call_recap VARCHAR"))
    if "list_name" not in existing:
        conn.execute(text("ALTER TABLE card_shops ADD COLUMN list_name VARCHAR"))
        conn.execute(text("UPDATE card_shops SET list_name = 'main' WHERE list_name IS NULL"))
    for col in ("verification_status", "last_verified", "place_id", "google_maps_url",
                "sells_sports_cards", "products_note"):
        if col not in existing:
            conn.execute(text(f"ALTER TABLE card_shops ADD COLUMN {col} VARCHAR"))

    try:
        ms_cols = {c["name"] for c in insp.get_columns("master_shops")}
        if "call_recap" not in ms_cols:
            conn.execute(text("ALTER TABLE master_shops ADD COLUMN call_recap VARCHAR"))
        if "moved_to_tcg" not in ms_cols:
            conn.execute(text("ALTER TABLE master_shops ADD COLUMN moved_to_tcg VARCHAR"))
        for col in ("place_id", "sells_sports_cards", "products_note"):
            if col not in ms_cols:
                conn.execute(text(f"ALTER TABLE master_shops ADD COLUMN {col} VARCHAR"))
    except Exception:
        pass  # table may not exist yet on a fresh DB; create_all handles it

    try:
        vf_cols = {c["name"] for c in insp.get_columns("vfile_cards")}
        if "deleted_at" not in vf_cols:
            conn.execute(text("ALTER TABLE vfile_cards ADD COLUMN deleted_at TIMESTAMP"))
    except Exception:
        pass  # table may not exist yet on a fresh DB; create_all handles it

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
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN catch_misspellings BOOLEAN DEFAULT TRUE"))
    # Misspelling tolerance is unconditional now; flip any row still sitting on
    # the old default so the stored data matches what actually happens.
    conn.execute(text("UPDATE saved_searches SET catch_misspellings = true "
                      "WHERE catch_misspellings IS NOT true"))
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
    if "priority" not in saved_cols:
        conn.execute(text("ALTER TABLE saved_searches ADD COLUMN priority BOOLEAN DEFAULT FALSE"))

    _seed_alert_seen(conn)
    _add_sent_alert_item_id(conn)
    _add_sent_alert_relist_key(conn)


def _add_sent_alert_item_id(conn):
    """Add sent_alerts.external_id and backfill it from the stored listing URL.

    Without the backfill the "one alert per card per user" rule would only start
    applying to cards seen after this deploy, and every card already alerted
    tonight could be sent a second time.
    """
    from sqlalchemy import text, inspect
    import re as _re
    try:
        insp = inspect(conn)
        cols = {c["name"] for c in insp.get_columns("sent_alerts")}
        if "external_id" not in cols:
            conn.execute(text("ALTER TABLE sent_alerts ADD COLUMN external_id VARCHAR"))
        rows = conn.execute(text(
            "SELECT id, listing_url FROM sent_alerts "
            "WHERE external_id IS NULL AND listing_url IS NOT NULL")).fetchall()
        n = 0
        for rid, url in rows:
            m = _re.search(r"/itm/(\d+)", url or "")
            if m:
                conn.execute(text("UPDATE sent_alerts SET external_id = :e WHERE id = :i"),
                             {"e": m.group(1), "i": rid})
                n += 1
        if n:
            print(f"sent_alerts.external_id backfilled for {n} rows")
    except Exception as e:
        print(f"sent_alerts.external_id migration skipped: {type(e).__name__}: {e}")


def _add_sent_alert_relist_key(conn):
    """Add sent_alerts.seller_name / relist_key and backfill the recent window.

    SentAlert never stored the seller, so the key is recovered by joining the
    already-backfilled external_id against card_listings, which does. Bounded to
    the relist window — older rows can no longer suppress anything, so computing
    keys for them would be wasted work.
    """
    from sqlalchemy import text, inspect
    from datetime import timedelta
    import re as _re
    try:
        insp = inspect(conn)
        cols = {c["name"] for c in insp.get_columns("sent_alerts")}
        for col in ("seller_name", "relist_key"):
            if col not in cols:
                conn.execute(text(f"ALTER TABLE sent_alerts ADD COLUMN {col} VARCHAR"))
        if conn.execute(text("SELECT 1 FROM sent_alerts WHERE relist_key IS NOT NULL LIMIT 1")).first():
            return  # already backfilled
        cutoff = datetime.utcnow() - timedelta(days=RELIST_WINDOW_DAYS)
        sellers = {}
        for ext, seller in conn.execute(text(
                "SELECT external_id, seller_name FROM card_listings WHERE seller_name IS NOT NULL")):
            m = _re.search(r"(\d{9,})", str(ext or ""))
            if m:
                sellers[m.group(1)] = seller
        n = 0
        for rid, ext, title in conn.execute(text(
                "SELECT id, external_id, title FROM sent_alerts "
                "WHERE external_id IS NOT NULL AND sent_at >= :c"), {"c": cutoff}):
            key = relist_key_for(title, sellers.get(str(ext)))
            if key:
                conn.execute(text("UPDATE sent_alerts SET seller_name = :s, relist_key = :k WHERE id = :i"),
                             {"s": sellers.get(str(ext)), "k": key, "i": rid})
                n += 1
        if n:
            print(f"sent_alerts.relist_key backfilled for {n} rows")
    except Exception as e:
        print(f"sent_alerts.relist_key migration skipped: {type(e).__name__}: {e}")


def _seed_alert_seen(conn):
    """One-time backfill when alert_seen (the new per-search dedup key) is empty.

    Alert dedup used to be global, so switching to a per-search key makes every
    listing look unseen to every alert — on the first cycle after deploy each
    alert would replay its entire window at once. Seeding from the listings we
    already recorded prevents that stampede.

    The last SEED_GRACE_HOURS are deliberately left unseeded: those are exactly
    the listings the global key may have swallowed without telling anyone, so
    they should still get their one alert. Bounded to the widest alert window
    (7 days) on both ends — anything older can't alert anyway, so seeding it
    would just be a large pointless cross join.
    """
    from sqlalchemy import text
    from datetime import timedelta
    SEED_GRACE_HOURS = 6
    try:
        if conn.execute(text("SELECT 1 FROM alert_seen LIMIT 1")).first():
            return  # already populated — never re-run
        now = datetime.utcnow()
        rows = conn.execute(text(
            "INSERT INTO alert_seen (search_id, source, external_id, seen_at) "
            "SELECT s.id, c.source, c.external_id, :now "
            "FROM saved_searches s JOIN card_listings c "
            "  ON c.listed_at < :recent AND c.listed_at > :oldest "
            "WHERE s.active = true AND c.external_id IS NOT NULL"
        ), {"now": now, "recent": now - timedelta(hours=SEED_GRACE_HOURS),
            "oldest": now - timedelta(days=7)})
        print(f"alert_seen seeded: {rows.rowcount} rows "
              f"(listings older than {SEED_GRACE_HOURS}h; newer ones stay alertable)")
    except Exception as e:
        # A fresh DB has no card_listings yet, and a failed seed must never block
        # startup — worst case is the one-time catch-up burst this avoids.
        print(f"alert_seen seed skipped: {type(e).__name__}: {e}")


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
