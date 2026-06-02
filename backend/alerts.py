import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from twilio.rest import Client as TwilioClient

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_MESSAGING_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")
SENDGRID_KEY = os.getenv("SENDGRID_API_KEY", "")
FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "alerts@cardfinderapp.com")


def send_email_alert(to_email: str, card_title: str, price: float, listing_url: str, verdict: str, avg_price: float):
    verdict_labels = {
        "great_deal": "GREAT DEAL",
        "good_deal": "Good Deal",
        "fair": "Fair Price",
        "overpriced": "Overpriced",
    }
    label = verdict_labels.get(verdict, "New Listing")

    html = f"""
    <h2>Card Finder Alert: {label}</h2>
    <p><strong>{card_title}</strong></p>
    <p>Listed at: <strong>${price:.2f}</strong></p>
    <p>Average sold price: <strong>${avg_price:.2f}</strong></p>
    <p><a href="{listing_url}">View Listing</a></p>
    <hr>
    <small>Card Finder App — manage your alerts in the app.</small>
    """

    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=f"Card Finder: [{label}] {card_title[:60]}",
        html_content=html,
    )
    try:
        sg = SendGridAPIClient(SENDGRID_KEY)
        sg.send(message)
    except Exception as e:
        print(f"Email alert failed: {e}")


def send_sms_alert(to_phone: str, card_title: str, price: float, listing_url: str, verdict: str):
    verdict_labels = {
        "great_deal": "GREAT DEAL",
        "good_deal": "Good Deal",
        "fair": "Fair Price",
        "overpriced": "Overpriced",
    }
    label = verdict_labels.get(verdict, "New Listing")
    body = f"Card Finder [{label}]: {card_title[:60]} — ${price:.2f}\n{listing_url}"

    try:
        client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=body, messaging_service_sid=TWILIO_MESSAGING_SID, to=to_phone)
    except Exception as e:
        print(f"SMS alert failed: {e}")


def send_alert(user, listing: dict, analysis: dict):
    title = listing.get("title", "")
    price = listing.get("price", 0)
    url = listing.get("listing_url", "")
    verdict = analysis.get("verdict", "unknown")
    avg = analysis.get("avg_sold_price", 0)

    if user.alert_method in ("email", "both") and user.email:
        send_email_alert(user.email, title, price, url, verdict, avg)
    if user.alert_method in ("sms", "both") and user.phone:
        send_sms_alert(user.phone, title, price, url, verdict)
