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

            query = f"{search.sport} {search.query}" if search.sport else search.query
            listings = await search_cards(query, search.min_price, search.max_price, limit=10)
            search.last_checked_at = datetime.utcnow()

            user_result = await db.execute(select(User).where(User.id == search.user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                continue

            cutoff = datetime.utcnow() - timedelta(hours=1)

            for listing in listings:
                ext_id = listing.get("external_id")
                existing = await db.execute(
                    select(CardListing).where(
                        CardListing.external_id == ext_id,
                        CardListing.source == "ebay"
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                record = CardListing(
                    source="ebay",
                    external_id=ext_id,
                    title=listing.get("title"),
                    price=listing.get("price"),
                    listing_url=listing.get("listing_url"),
                    image_url=listing.get("image_url"),
                    seller_name=listing.get("seller_name"),
                    condition=listing.get("condition"),
                )
                db.add(record)

                from scrapers.ebay_scraper import get_sold_history
                sold = await get_sold_history(query, limit=10)
                analysis = analyze_deal(listing, sold)

                send_alert(user, listing, analysis)

        await db.commit()


async def main():
    await init_db()
    print("Worker started. Checking every 15 minutes...")
    while True:
        print(f"[{datetime.utcnow().isoformat()}] Checking saved searches...")
        try:
            await check_saved_searches()
        except Exception as e:
            print(f"Worker error: {e}")
        await asyncio.sleep(900)


if __name__ == "__main__":
    asyncio.run(main())
