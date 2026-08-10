"""
Background worker: runs every 15 minutes, checks saved searches,
and sends alerts when new listings appear.
"""
import asyncio
import os
from datetime import datetime, timedelta
from sqlalchemy import select
from dotenv import load_dotenv

load_dotenv()

from database import (AsyncSessionLocal, User, SavedSearch, CardListing, AlertSeen, SentAlert,
                      relist_key_for, RELIST_WINDOW_DAYS, init_db)
from scrapers.ebay_scraper import search_cards
from agents.price_analyst import analyze_deal
from alerts import send_alert


async def check_saved_searches():
    async with AsyncSessionLocal() as db:
        from database import AppFlag
        pause = await db.get(AppFlag, "alerts_paused")
        if pause and pause.value == "yes":
            return  # global pause
        result = await db.execute(select(SavedSearch).where(SavedSearch.active == True))
        searches = result.scalars().all()

        # Auto-stretch checks to keep the day's eBay calls under budget.
        from alert_filters import min_interval_for
        floor_interval = min_interval_for(len(searches))

        for search in searches:
            # Respect each search's custom interval, but never below the 60-min min or budget floor
            if search.last_checked_at:
                elapsed = (datetime.utcnow() - search.last_checked_at).total_seconds() / 60
                if elapsed < max(search.check_interval_minutes or 30, floor_interval):
                    continue

            from alert_filters import build_query, gather_alert_listings, passes_deal_threshold
            is_first_check = search.last_checked_at is None
            src, listings = await gather_alert_listings(search)
            search.last_checked_at = datetime.utcnow()

            user_result = await db.execute(select(User).where(User.id == search.user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                continue

            for listing in listings:
                ext_id = listing.get("external_id")
                # Dedup PER SEARCH — see the matching comment in main.py. Keyed
                # globally, one alert seeing a listing silenced it for all others.
                already = await db.execute(
                    select(AlertSeen.id).where(
                        AlertSeen.search_id == search.id,
                        AlertSeen.external_id == ext_id,
                        AlertSeen.source == src,
                    )
                )
                if already.scalar_one_or_none():
                    continue
                db.add(AlertSeen(search_id=search.id, source=src, external_id=ext_id))

                known = await db.execute(
                    select(CardListing.id).where(
                        CardListing.external_id == ext_id,
                        CardListing.source == src,
                    )
                )
                if not known.scalar_one_or_none():
                    db.add(CardListing(
                        source=src, external_id=ext_id,
                        title=listing.get("title"), price=listing.get("price"),
                        listing_url=listing.get("listing_url"), image_url=listing.get("image_url"),
                        seller_name=listing.get("seller_name"), condition=listing.get("condition"),
                    ))

                # One alert per card per person — see main.py. Without this the
                # per-search dedup lets one listing email a user once per matching
                # alert. worker.py also has to WRITE SentAlert now, or its sends
                # would be invisible to the check and duplicate freely.
                from main import _alert_item_key
                item_key = _alert_item_key(listing)
                told = await db.execute(select(SentAlert.id).where(
                    SentAlert.user_id == search.user_id,
                    SentAlert.external_id == item_key))
                if told.scalar_one_or_none():
                    continue

                # Relist under a new item id — see main.py.
                relist = relist_key_for(listing.get("title"), listing.get("seller_name"))
                if relist:
                    since = datetime.utcnow() - timedelta(days=RELIST_WINDOW_DAYS)
                    seen_before = await db.execute(select(SentAlert.id).where(
                        SentAlert.user_id == search.user_id,
                        SentAlert.relist_key == relist,
                        SentAlert.sent_at >= since))
                    if seen_before.scalar_one_or_none():
                        continue

                if is_first_check:
                    continue  # baseline silently on first run
                if src == "goldin":
                    analysis = {"verdict": "auction", "avg_sold_price": 0,
                                "last_sold_price": listing.get("last_sold_price"),
                                "last_sold_at": listing.get("last_sold_at")}
                else:
                    from scrapers.ebay_scraper import get_sold_history
                    sold = await get_sold_history(build_query(search), limit=10)
                    analysis = analyze_deal(listing, sold)
                # Auctions are gated on their own current bid against the alert's
                # floor, in gather_alert_listings — same rule as fixed-price. The
                # avg-sold-price gate that used to live here is gone (it judged rare
                # parallels against the base cards a broad query comps out to).
                # Keep in step with main.py.
                if not passes_deal_threshold(search, src, analysis):
                    continue  # not enough of a discount to alert on
                send_alert(user, listing, analysis, method=search.alert_method, alert_label=search.query)
                db.add(SentAlert(
                    user_id=user.id, search_id=search.id, query=search.query,
                    title=listing.get("title"), price=listing.get("price"),
                    listing_url=listing.get("listing_url"), image_url=listing.get("image_url"),
                    verdict=analysis.get("verdict"), pct_vs_market=analysis.get("pct_vs_market"),
                    is_auction=bool(listing.get("is_auction")), external_id=item_key,
                    seller_name=listing.get("seller_name"), relist_key=relist,
                ))

        await db.commit()


async def main():
    await init_db()
    print("Worker started. Polling every 30 seconds...")
    while True:
        try:
            await check_saved_searches()
        except Exception as e:
            print(f"Worker error: {e}")
        await asyncio.sleep(30)


if __name__ == "__main__":
    asyncio.run(main())
