import anthropic
import os
import json
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))


def analyze_deal(listing: dict, sold_history: list[dict]) -> dict:
    """Use Claude to analyze whether a listing is a good deal based on sold history."""
    if not sold_history:
        return {"verdict": "unknown", "summary": "No recent sales data available to compare."}

    sold_prices = [s["sold_price"] for s in sold_history if s.get("sold_price")]
    most_recent_sold = sold_history[0].get("sold_price") if sold_history else None
    most_recent_date = sold_history[0].get("sold_at") if sold_history else None
    avg_price = sum(sold_prices) / len(sold_prices) if sold_prices else 0
    current_price = listing.get("price", 0)

    prompt = f"""You are a sports card market expert. Analyze this card listing and tell the buyer if it's a good deal.

Card listing:
- Title: {listing.get('title')}
- Current price: ${current_price:.2f}
- Source: {listing.get('source')}

Recent sold prices for similar cards ({len(sold_prices)} sales):
{json.dumps(sold_prices, indent=2)}

Average sold price: ${avg_price:.2f}

Give a brief 2-3 sentence analysis:
1. Is this a good deal, fair, or overpriced?
2. What's the % difference from average?
3. One recommendation for the buyer.

Keep it simple and direct."""

    pct_diff = ((current_price - avg_price) / avg_price * 100) if avg_price else 0

    if pct_diff <= -15:
        verdict = "great_deal"
    elif pct_diff <= 0:
        verdict = "good_deal"
    elif pct_diff <= 15:
        verdict = "fair"
    else:
        verdict = "overpriced"

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = message.content[0].text
    except Exception:
        if pct_diff <= -15:
            summary = f"This card is listed {abs(pct_diff):.0f}% below the average sold price of ${avg_price:.2f} — an excellent deal."
        elif pct_diff <= 0:
            summary = f"Listed at or below the average sold price of ${avg_price:.2f}. A solid buy."
        elif pct_diff <= 15:
            summary = f"Priced close to the average of ${avg_price:.2f}. Fair market value."
        else:
            summary = f"Listed {pct_diff:.0f}% above the average sold price of ${avg_price:.2f}. Consider negotiating or waiting for a better deal."

    return {
        "verdict": verdict,
        "avg_sold_price": round(avg_price, 2),
        "most_recent_sold": most_recent_sold,
        "most_recent_date": most_recent_date,
        "pct_vs_market": round(pct_diff, 1),
        "summary": summary,
        "sample_size": len(sold_prices),
    }
