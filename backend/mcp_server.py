"""Remote MCP server — lets someone add Card Finder as a custom connector in Claude.

A user pastes `https://<backend>/mcp` into Claude's Settings -> Connectors -> "Add
custom connector" and authenticates with the shops password, entered once in that
dialog's **Request headers** section. Claude then sends it on every request, which
is the same secret the shop routes already gate on.

Claude only lets a connector send header names from its own allowlist (`authorization`,
`x-api-key`, `x-auth-token`, …), and `X-Shops-Password` is not on it — so this endpoint
accepts the secret three ways: `Authorization: Bearer <password>` (the form to use in
Claude), `X-Api-Key`, or the site's own `X-Shops-Password` for local testing and curl.

The wire protocol is JSON-RPC 2.0 over a single POST, so this is implemented
directly rather than via the `mcp` SDK — that package needs Python 3.10+ and would
be a new dependency for what amounts to a method dispatch table.

Every tool here is READ-ONLY. Claude can look things up and answer questions about
the shop lists, alerts, and eBay prices; nothing it does through this endpoint can
change the database. That matters more than usual: shop websites and listing titles
are attacker-controlled text that ends up in Claude's context, so a write tool here
would be reachable by prompt injection.

If the Request-headers beta isn't available on an account, the 401 emitted by
`_unauthorized()` already carries the RFC 9728 `resource_metadata` pointer that
Claude's OAuth discovery looks for — adding an OAuth authorization server later
means filling in that document, not reworking this file.
"""
import os
from typing import Any, Callable, Optional

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from database import AsyncSessionLocal, CardShop, MasterShop, SavedSearch, SentAlert, User

router = APIRouter()

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "card-finder"
SERVER_VERSION = "1.0.0"

# Cap every result set — a connector reply is fed straight into Claude's context,
# and "list all shops" against 900+ rows would blow the window for no benefit.
MAX_LIMIT = 50


def _public_base(request: Request) -> str:
    """Public origin of this server, for the OAuth metadata pointer. PUBLIC_BASE_URL
    wins because Render terminates TLS upstream, so request.url can read as http."""
    base = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    return base or str(request.base_url).rstrip("/")


# --- auth ------------------------------------------------------------------

def _shops_password() -> str:
    return os.getenv("SHOPS_PASSWORD", "")


def _authorized(x_shops_password: Optional[str], authorization: Optional[str],
                x_api_key: Optional[str]) -> bool:
    """Accept the shops password under any of the header names Claude will actually
    send. `Authorization: Bearer <password>` is the one to use in the connector
    dialog; the others exist for curl and for whichever names the dialog offers."""
    import secrets

    expected = _shops_password()
    if not expected:
        return False          # never authorize against an unset secret

    candidates = [(x_shops_password or "").strip(), (x_api_key or "").strip()]
    auth = (authorization or "").strip()
    if auth:
        # Tolerate a value pasted with or without the "Bearer " scheme — Claude
        # sends the header value verbatim, and pasting the bare token is a
        # documented, easy mistake.
        candidates.append(auth[7:].strip() if auth.lower().startswith("bearer ") else auth)

    return any(c and secrets.compare_digest(c, expected) for c in candidates)


def _unauthorized(request: Request) -> JSONResponse:
    """401 in the shape Claude's OAuth discovery expects, so the same endpoint can
    grow an authorization server later without changing how clients find it."""
    meta = f"{_public_base(request)}/.well-known/oauth-protected-resource"
    return JSONResponse(
        {"error": "unauthorized", "detail": "Missing or invalid X-Shops-Password header."},
        status_code=401,
        headers={"WWW-Authenticate": f'Bearer resource_metadata="{meta}"'},
    )


# --- tool helpers ----------------------------------------------------------

def _clamp(limit: Any, default: int = 20) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, MAX_LIMIT))


def _shop_summary(s: CardShop) -> dict:
    """Compact projection of a Shops/TCG row. Full column dumps are mostly empty
    strings and crowd out the rows that matter."""
    return {
        "id": s.id,
        "list": "TCG Shops List" if s.list_name == "tcg" else "Shops List",
        "name": s.name,
        "city": s.city,
        "state": s.state,
        "address": s.full_address,
        "phone": s.phone,
        "email": s.email,
        "website": s.website,
        "instagram": s.instagram,
        "whatnot": s.whatnot,
        "rating": s.rating,
        "reviews": s.reviews,
        "contacted": s.contacted,
        "contacted_by": s.contacted_by,
        "contact_name": s.contact_name,
        "contact_phone": s.contact_phone,
        "call_notes": s.call_notes,
        "active": s.active,
        "sells_sports_cards": s.sells_sports_cards,
        "verification_status": s.verification_status,
    }


def _master_summary(s: MasterShop) -> dict:
    """Compact projection of a New Shops List row."""
    return {
        "id": s.id,
        "list": "New Shops List",
        "record_id": s.record_id,
        "name": s.name,
        "owner_name": s.owner_name,
        "city": s.city,
        "state": s.state,
        "address": s.street_address,
        "zip": s.zip_code,
        "county": s.county,
        "metro_area": s.metro_area,
        "phone": s.phone,
        "email": s.email,
        "website": s.website,
        "instagram": s.instagram,
        "facebook": s.facebook,
        "whatnot": s.whatnot,
        "ebay_store": s.ebay_store,
        "store_hours": s.store_hours,
        "google_rating": s.google_rating,
        "num_reviews": s.num_reviews,
        "contacted": s.contacted,
        "contacted_by": s.contacted_by,
        "contact_name": s.contact_name,
        "contact_phone": s.contact_phone,
        "call_notes": s.call_notes,
        "active": s.active,
        "sells_sports_cards": s.sells_sports_cards,
        "buying_cards": s.buying_cards,
        "selling_wax": s.selling_wax,
        "pokemon": s.pokemon,
        "sports_cards": s.sports_cards,
        "tcg_other": s.tcg_other,
        "notes": s.notes,
    }


async def _resolve_user(db, email: Optional[str]) -> Optional[User]:
    """Alerts are per-user. Fall back to OWNER_EMAIL so the common case ('my
    alerts') works without the caller knowing which account owns them."""
    from sqlalchemy import func

    target = (email or os.getenv("OWNER_EMAIL") or "").strip().lower()
    if not target:
        return None
    r = await db.execute(select(User).where(func.lower(User.email) == target))
    return r.scalar_one_or_none()


# --- tools -----------------------------------------------------------------

async def _tool_search_shops(args: dict, db) -> dict:
    name = (args.get("name") or "").strip()
    city = (args.get("city") or "").strip()
    state = (args.get("state") or "").strip()
    which = (args.get("list") or "all").strip().lower()
    contacted = args.get("contacted")
    limit = _clamp(args.get("limit"))

    rows: list = []

    if which in ("all", "shops", "tcg"):
        q = select(CardShop)
        if which == "shops":
            q = q.where(CardShop.list_name != "tcg")
        elif which == "tcg":
            q = q.where(CardShop.list_name == "tcg")
        if name:
            q = q.where(CardShop.name.ilike(f"%{name}%"))
        if city:
            q = q.where(CardShop.city.ilike(f"%{city}%"))
        if state:
            q = q.where(CardShop.state.ilike(state))
        r = await db.execute(q.limit(MAX_LIMIT * 2))
        rows += [_shop_summary(s) for s in r.scalars().all()]

    if which in ("all", "new", "master", "new shops"):
        q = select(MasterShop)
        if name:
            q = q.where(MasterShop.name.ilike(f"%{name}%"))
        if city:
            q = q.where(MasterShop.city.ilike(f"%{city}%"))
        if state:
            q = q.where(MasterShop.state.ilike(state))
        r = await db.execute(q.limit(MAX_LIMIT * 2))
        rows += [_master_summary(s) for s in r.scalars().all()]

    # Contacted is a free-text flag across both tables ("yes", a name, a date, …),
    # so filter on presence rather than trying to match a value.
    if contacted is True:
        rows = [x for x in rows if (x.get("contacted") or "").strip()]
    elif contacted is False:
        rows = [x for x in rows if not (x.get("contacted") or "").strip()]

    if args.get("include_inactive") is not True:
        rows = [x for x in rows if (x.get("active") or "").strip().lower() != "no"]

    total = len(rows)
    return {
        "total_matches": total,
        "returned": min(total, limit),
        "truncated": total > limit,
        "shops": rows[:limit],
    }


async def _tool_get_shop(args: dict, db) -> dict:
    shop_id = args.get("id")
    which = (args.get("list") or "").strip().lower()
    record_id = (args.get("record_id") or "").strip()

    if record_id:
        r = await db.execute(select(MasterShop).where(MasterShop.record_id == record_id))
        s = r.scalar_one_or_none()
        return {"shop": _master_summary(s)} if s else {"error": f"No New Shops row {record_id}."}

    if shop_id is None:
        return {"error": "Pass either `id` (with `list`) or `record_id`."}

    if which in ("new", "master", "new shops"):
        s = await db.get(MasterShop, int(shop_id))
        return {"shop": _master_summary(s)} if s else {"error": f"No New Shops row id {shop_id}."}

    s = await db.get(CardShop, int(shop_id))
    return {"shop": _shop_summary(s)} if s else {"error": f"No shop id {shop_id}."}


async def _tool_list_alerts(args: dict, db) -> dict:
    user = await _resolve_user(db, args.get("email"))
    if not user:
        return {"error": "No such user. Pass `email`, or set OWNER_EMAIL on the server."}
    q = select(SavedSearch).where(SavedSearch.user_id == user.id)
    if args.get("include_inactive") is not True:
        q = q.where(SavedSearch.active == True)  # noqa: E712 — SQLAlchemy needs ==
    r = await db.execute(q.order_by(SavedSearch.created_at.desc()).limit(MAX_LIMIT * 2))
    searches = r.scalars().all()
    limit = _clamp(args.get("limit"))
    return {
        "user": user.email,
        "total": len(searches),
        "alerts": [
            {
                "id": s.id,
                "query": s.query,
                "sport": s.sport,
                "brand": s.brand,
                "year": s.year,
                "min_price": s.min_price,
                "max_price": s.max_price,
                "numbered_to": s.numbered_to,
                "insert_type": s.insert_type,
                "exclude": s.exclude,
                "source": s.source,
                "folder": s.folder,
                "active": s.active,
                "alerts_sent": s.alerts_sent_count,
                "last_match_at": s.last_match_at.isoformat() if s.last_match_at else None,
                "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
                "health": s.health_status,
                "health_detail": s.health_detail,
            }
            for s in searches[:limit]
        ],
    }


async def _tool_recent_matches(args: dict, db) -> dict:
    user = await _resolve_user(db, args.get("email"))
    if not user:
        return {"error": "No such user. Pass `email`, or set OWNER_EMAIL on the server."}
    limit = _clamp(args.get("limit"))
    q = select(SentAlert).where(SentAlert.user_id == user.id)
    if args.get("search_id"):
        q = q.where(SentAlert.search_id == int(args["search_id"]))
    r = await db.execute(q.order_by(SentAlert.sent_at.desc()).limit(limit))
    return {
        "user": user.email,
        "matches": [
            {
                "alert": a.query,
                "title": a.title,
                "price": a.price,
                "url": a.listing_url,
                "verdict": a.verdict,
                "pct_vs_market": a.pct_vs_market,
                "is_auction": a.is_auction,
                "sent_at": a.sent_at.isoformat() if a.sent_at else None,
            }
            for a in r.scalars().all()
        ],
    }


async def _tool_search_ebay(args: dict, db) -> dict:
    from scrapers.ebay_scraper import search_cards

    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "`query` is required."}
    limit = _clamp(args.get("limit"), default=10)
    listings = await search_cards(query, args.get("min_price"), args.get("max_price"))
    return {
        "query": query,
        "total": len(listings),
        "listings": [
            {
                "title": l.get("title"),
                "price": l.get("price"),
                "url": l.get("listing_url"),
                "condition": l.get("condition"),
                "seller": l.get("seller_name"),
            }
            for l in listings[:limit]
        ],
    }


async def _tool_sold_comps(args: dict, db) -> dict:
    from scrapers.ebay_scraper import get_sold_history

    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "`query` is required."}
    limit = _clamp(args.get("limit"), default=20)
    sold = await get_sold_history(query, limit=limit)
    prices = [s["sold_price"] for s in sold if s.get("sold_price")]
    return {
        "query": query,
        "count": len(sold),
        "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
        "low": min(prices) if prices else None,
        "high": max(prices) if prices else None,
        "sales": [
            {"title": s.get("title"), "sold_price": s.get("sold_price"),
             "sold_at": s.get("sold_at"), "url": s.get("listing_url")}
            for s in sold[:limit]
        ],
    }


TOOLS: list[dict] = [
    {
        "name": "search_shops",
        "description": (
            "Search the card shop database by name, city, or state. Covers all three "
            "lists: the Shops List, the TCG Shops List, and the New Shops List "
            "(~900 shops). Returns contact details, call notes, and whether the shop "
            "has been contacted. Closed shops are excluded unless include_inactive is true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Shop name, partial match."},
                "city": {"type": "string", "description": "City, partial match."},
                "state": {"type": "string", "description": "Two-letter state code, e.g. TX."},
                "list": {
                    "type": "string",
                    "enum": ["all", "shops", "tcg", "new"],
                    "description": "Which list to search. Defaults to all.",
                },
                "contacted": {
                    "type": "boolean",
                    "description": "true = only shops already contacted; false = only ones not yet contacted.",
                },
                "include_inactive": {
                    "type": "boolean",
                    "description": "Include shops marked closed/inactive. Defaults to false.",
                },
                "limit": {"type": "integer", "description": "Max shops to return (1-50, default 20)."},
            },
        },
        "_fn": _tool_search_shops,
    },
    {
        "name": "get_shop",
        "description": (
            "Get the full record for one shop, including call notes and contact history. "
            "Identify it by `record_id` (New Shops List, e.g. R-0123) or by `id` plus `list`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Numeric shop id."},
                "list": {
                    "type": "string",
                    "enum": ["shops", "tcg", "new"],
                    "description": "Which list the id belongs to. Defaults to the Shops/TCG table.",
                },
                "record_id": {"type": "string", "description": "New Shops List record id, e.g. R-0123."},
            },
        },
        "_fn": _tool_get_shop,
    },
    {
        "name": "list_alerts",
        "description": (
            "List the saved card searches (alerts) that watch eBay and auctions, with "
            "their filters, health status, and when each last matched. Defaults to the "
            "owner account unless `email` is given."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Account whose alerts to list."},
                "include_inactive": {"type": "boolean", "description": "Include paused/deleted alerts."},
                "limit": {"type": "integer", "description": "Max alerts to return (1-50, default 20)."},
            },
        },
        "_fn": _tool_list_alerts,
    },
    {
        "name": "recent_matches",
        "description": (
            "Recent cards that alerts actually fired on — the log of finds, newest first, "
            "with price and how far below market each was."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Account whose matches to list."},
                "search_id": {"type": "integer", "description": "Only matches from this alert id."},
                "limit": {"type": "integer", "description": "Max matches to return (1-50, default 20)."},
            },
        },
        "_fn": _tool_recent_matches,
    },
    {
        "name": "search_ebay",
        "description": "Search live eBay listings for a card. Use sold_comps for what cards actually sell for.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Card to search, e.g. '2023 Bowman Chrome Wyatt Langford auto'."},
                "min_price": {"type": "number"},
                "max_price": {"type": "number"},
                "limit": {"type": "integer", "description": "Max listings to return (1-50, default 10)."},
            },
            "required": ["query"],
        },
        "_fn": _tool_search_ebay,
    },
    {
        "name": "sold_comps",
        "description": (
            "Recent SOLD prices for a card, with average, low, and high — the market "
            "value read. Use this to judge whether a listing is a deal."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Card to price."},
                "limit": {"type": "integer", "description": "Max sales to return (1-50, default 20)."},
            },
            "required": ["query"],
        },
        "_fn": _tool_sold_comps,
    },
]

_TOOL_FNS: dict[str, Callable] = {t["name"]: t["_fn"] for t in TOOLS}
_TOOL_SPECS = [{k: v for k, v in t.items() if not k.startswith("_")} for t in TOOLS]


# --- JSON-RPC plumbing -----------------------------------------------------

def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _dispatch(method: str, params: dict, req_id: Any, db) -> Optional[dict]:
    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Card Finder: sports-card shop database and eBay price tools. "
                "Shop data spans three lists (Shops, TCG Shops, New Shops). All tools "
                "are read-only."
            ),
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None                     # notifications take no response

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": _TOOL_SPECS})

    if method == "tools/call":
        name = params.get("name")
        fn = _TOOL_FNS.get(name)
        if not fn:
            return _error(req_id, -32602, f"Unknown tool: {name}")
        try:
            payload = await fn(params.get("arguments") or {}, db)
        except Exception as e:                                  # noqa: BLE001
            # Surface failures as tool errors, not transport errors — Claude can
            # read and route around these; a JSON-RPC error just kills the turn.
            import json as _json
            return _result(req_id, {
                "content": [{"type": "text", "text": _json.dumps({"error": f"{type(e).__name__}: {e}"})}],
                "isError": True,
            })
        import json as _json
        return _result(req_id, {
            "content": [{"type": "text", "text": _json.dumps(payload, default=str)}],
            "isError": bool(isinstance(payload, dict) and payload.get("error")),
        })

    return _error(req_id, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    x_shops_password: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
):
    """Single JSON-RPC entry point for the MCP connector."""
    if not _authorized(x_shops_password, authorization, x_api_key):
        return _unauthorized(request)

    try:
        body = await request.json()
    except Exception:                                            # noqa: BLE001
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)

    batch = isinstance(body, list)
    messages = body if batch else [body]

    replies = []
    async with AsyncSessionLocal() as db:
        for msg in messages:
            if not isinstance(msg, dict):
                replies.append(_error(None, -32600, "Invalid Request"))
                continue
            reply = await _dispatch(msg.get("method") or "", msg.get("params") or {},
                                    msg.get("id"), db)
            if reply is not None:
                replies.append(reply)

    if not replies:
        return Response(status_code=202)     # notification-only batch
    return JSONResponse(replies if batch else replies[0])


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource_metadata(request: Request):
    """RFC 9728 metadata. Present so Claude's discovery has something to read; the
    `authorization_servers` list stays empty while this server uses header auth,
    and gets filled in if an OAuth authorization server is added later."""
    base = _public_base(request)
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [],
        "bearer_methods_supported": ["header"],
        "resource_name": "Card Finder",
    }
