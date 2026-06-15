import os
import httpx
from twilio.rest import Client as TwilioClient

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_MESSAGING_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")

# SendGrid HTTP API (works on Render — uses HTTPS, not blocked SMTP ports)
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "")


def send_email_alert(to_email: str, card_title: str, price: float, listing_url: str, verdict: str, avg_price: float, note: str = ""):
    verdict_labels = {
        "great_deal": "GREAT DEAL",
        "good_deal": "Good Deal",
        "fair": "Fair Price",
        "overpriced": "Overpriced",
        "auction": "🔨 LIVE AUCTION",
    }
    label = verdict_labels.get(verdict, "New Listing")
    avg_line = f'<p>Average sold price: <strong>${avg_price:.2f}</strong></p>' if avg_price else ""
    price_label = "Current bid" if verdict == "auction" else "Listed at"
    note_line = f'<p style="color:#475569;">{note}</p>' if note else ""

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 500px;">
      <h2 style="color: #1e3a8a;">Card Finder Alert: {label}</h2>
      <p style="font-size: 16px;"><strong>{card_title}</strong></p>
      <p>{price_label}: <strong style="font-size: 20px; color: #16a34a;">${price:.2f}</strong></p>
      {avg_line}
      {note_line}
      <p><a href="{listing_url}" style="background: #2563eb; color: #fff; padding: 10px 20px; border-radius: 8px; text-decoration: none; display: inline-block;">View Listing</a></p>
      <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
      <small style="color: #94a3b8;">Card Finder — manage your alerts in the app.</small>
    </div>
    """

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": SENDGRID_FROM_EMAIL, "name": "Card Finder"},
        "subject": f"Card Finder: [{label}] {card_title[:60]}",
        "content": [{"type": "text/html", "value": html}],
    }

    try:
        resp = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        if resp.status_code >= 400:
            print(f"Email alert failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Email alert failed: {e}")


# Carrier email-to-SMS gateways (free texts via email)
CARRIER_GATEWAYS = {
    "att": "txt.att.net",
    "tmobile": "tmomail.net",
    "verizon": "vtext.com",
    "sprint": "messaging.sprintpcs.com",
    "cricket": "sms.cricketwireless.net",
    "boost": "sms.myboostmobile.com",
    "uscellular": "email.uscc.net",
    "metropcs": "mymetropcs.com",
    "googlefi": "msg.fi.google.com",
}


def _send_via_gateway(to_phone: str, carrier: str, body: str) -> bool:
    """Send a text for free via the carrier's email-to-SMS gateway (using SendGrid)."""
    gateway = CARRIER_GATEWAYS.get(carrier.lower())
    if not gateway:
        return False
    digits = "".join(c for c in to_phone if c.isdigit())[-10:]  # last 10 digits
    sms_email = f"{digits}@{gateway}"
    payload = {
        "personalizations": [{"to": [{"email": sms_email}]}],
        "from": {"email": SENDGRID_FROM_EMAIL, "name": "Card Finder"},
        "subject": "Card Alert",
        "content": [{"type": "text/plain", "value": body}],
    }
    try:
        resp = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        if resp.status_code >= 400:
            print(f"Gateway SMS failed: {resp.status_code} {resp.text}")
            return False
        return True
    except Exception as e:
        print(f"Gateway SMS failed: {e}")
        return False


def send_sms_alert(to_phone: str, card_title: str, price: float, listing_url: str, verdict: str, carrier: str = None, note: str = ""):
    verdict_labels = {
        "great_deal": "GREAT DEAL",
        "good_deal": "Good Deal",
        "fair": "Fair Price",
        "overpriced": "Overpriced",
        "auction": "🔨 AUCTION",
    }
    label = verdict_labels.get(verdict, "New Listing")
    body = f"Card Finder [{label}]: {card_title[:60]} — ${price:.2f}"
    if note:
        body += f"\n{note}"
    body += f"\n{listing_url}"

    # If the user told us their carrier, send a free text via the email gateway
    if carrier and _send_via_gateway(to_phone, carrier, body):
        return

    # Otherwise fall back to Twilio (requires A2P/toll-free verification to deliver)
    try:
        client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=body, messaging_service_sid=TWILIO_MESSAGING_SID, to=to_phone)
    except Exception as e:
        print(f"SMS alert failed: {e}")


def _last_sold_note(analysis: dict) -> str:
    """Build a 'Last sold $X — N months ago' line from auction analysis data."""
    price = analysis.get("last_sold_price")
    at = analysis.get("last_sold_at")
    if not at:
        return "No recorded Goldin sales." if analysis.get("verdict") == "auction" else ""
    from datetime import datetime
    try:
        d = datetime.strptime(str(at)[:10], "%Y-%m-%d")
        months = max(0, (datetime.utcnow() - d).days // 30)
        if months == 0:
            ago = "this month"
        elif months >= 18:
            years = months // 12
            ago = f"~{years} year{'s' if years != 1 else ''} ago"
        else:
            ago = f"{months} month{'s' if months != 1 else ''} ago"
        amt = f"${price:,.0f} " if price else ""
        return f"Last sold {amt}— {ago} ({str(at)[:10]})"
    except Exception:
        return ""


def send_alert(user, listing: dict, analysis: dict, method: str = None):
    title = listing.get("title", "")
    price = listing.get("price", 0)
    url = listing.get("listing_url", "")
    verdict = analysis.get("verdict", "unknown")
    avg = analysis.get("avg_sold_price", 0)
    note = _last_sold_note(analysis)

    # Per-alert method overrides the user's global default
    delivery = method or user.alert_method

    # SMS first — it works reliably; email may be blocked on some hosts
    if delivery in ("sms", "both") and user.phone:
        send_sms_alert(user.phone, title, price, url, verdict, carrier=getattr(user, "carrier", None), note=note)
    if delivery in ("email", "both") and user.email:
        send_email_alert(user.email, title, price, url, verdict, avg, note=note)
