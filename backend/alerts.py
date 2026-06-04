import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from twilio.rest import Client as TwilioClient

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_MESSAGING_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")

# Gmail SMTP
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")


def send_email_alert(to_email: str, card_title: str, price: float, listing_url: str, verdict: str, avg_price: float):
    verdict_labels = {
        "great_deal": "GREAT DEAL",
        "good_deal": "Good Deal",
        "fair": "Fair Price",
        "overpriced": "Overpriced",
    }
    label = verdict_labels.get(verdict, "New Listing")

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 500px;">
      <h2 style="color: #1e3a8a;">Card Finder Alert: {label}</h2>
      <p style="font-size: 16px;"><strong>{card_title}</strong></p>
      <p>Listed at: <strong style="font-size: 20px; color: #16a34a;">${price:.2f}</strong></p>
      <p>Average sold price: <strong>${avg_price:.2f}</strong></p>
      <p><a href="{listing_url}" style="background: #2563eb; color: #fff; padding: 10px 20px; border-radius: 8px; text-decoration: none; display: inline-block;">View Listing on eBay</a></p>
      <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
      <small style="color: #94a3b8;">Card Finder — manage your alerts in the app.</small>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Card Finder: [{label}] {card_title[:60]}"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())
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


def send_alert(user, listing: dict, analysis: dict, method: str = None):
    title = listing.get("title", "")
    price = listing.get("price", 0)
    url = listing.get("listing_url", "")
    verdict = analysis.get("verdict", "unknown")
    avg = analysis.get("avg_sold_price", 0)

    # Per-alert method overrides the user's global default
    delivery = method or user.alert_method

    if delivery in ("email", "both") and user.email:
        send_email_alert(user.email, title, price, url, verdict, avg)
    if delivery in ("sms", "both") and user.phone:
        send_sms_alert(user.phone, title, price, url, verdict)
