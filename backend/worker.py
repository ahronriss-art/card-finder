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

from database import AsyncSessionLocal, User, SavedSearch, CardListing, init_db
from scrapers.ebay_scraper import search_cards
from agents.price_analyst import analyze_deal
from alerts import send_alert


async def check_saved_searches():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(SavedSearch).where(SavedSearch.active == True))
        searches = result.scalars().all()

        for search in searches:
            # Respect each search's custom interval
            if search.last_checked_at:
                elapsed = (datetime.utcnow() - search.last_checked_at).total_seconds() / 60
                if elapsed < search.check_interval_minutes:
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
                existing = await db.execute(
                    select(CardListing).where(
                        CardListing.external_id == ext_id,
                        CardListing.source == src
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
                if not passes_deal_threshold(search, src, analysis):
                    continue  # not enough of a discount to alert on
                send_alert(user, listing, analysis, method=search.alert_method)

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
