import os
import re
import httpx
from twilio.rest import Client as TwilioClient

# EMERGENCY KILL SWITCH: when True, NO alert emails or texts go out at all.
# Set False only when the user explicitly says to resume alerts.
ALERTS_KILLED = False

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_MESSAGING_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID", "")

# Email HTTP APIs (work on Render — HTTPS, not blocked SMTP ports).
# Brevo is preferred (300/day free, single-sender, no domain required); SendGrid
# is the fallback. Both send from the same verified FROM_EMAIL.
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL", "")
FROM_EMAIL = os.getenv("EMAIL_FROM") or SENDGRID_FROM_EMAIL or os.getenv("BREVO_FROM_EMAIL", "")


def _deliver_email(to_email: str, subject: str, html: str = None, text: str = None, list_unsub: bool = False) -> bool:
    """Send one email via Brevo (preferred) or SendGrid. Returns True on success.
    Pass html and/or text; set list_unsub=True for real alerts (adds a
    List-Unsubscribe header)."""
    unsub = f"mailto:{FROM_EMAIL}?subject=unsubscribe" if FROM_EMAIL else "mailto:unsubscribe@example.com"
    extra_headers = {
        "List-Unsubscribe": f"<{unsub}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    } if list_unsub else {}

    if BREVO_API_KEY:
        body = {
            "sender": {"name": "Card Finder", "email": FROM_EMAIL},
            "replyTo": {"name": "Card Finder", "email": FROM_EMAIL},
            "to": [{"email": to_email}],
            "subject": subject,
        }
        if html:
            body["htmlContent"] = html
        if text:
            body["textContent"] = text
        if not html and not text:
            body["textContent"] = subject
        if extra_headers:
            body["headers"] = extra_headers
        try:
            resp = httpx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json", "accept": "application/json"},
                json=body, timeout=15,
            )
            if resp.status_code >= 400:
                print(f"Brevo email failed: {resp.status_code} {resp.text}")
                return False
            return True
        except Exception as e:
            print(f"Brevo email failed: {e}")
            return False

    if SENDGRID_API_KEY:
        content = []
        if text:
            content.append({"type": "text/plain", "value": text})  # text MUST precede html
        if html:
            content.append({"type": "text/html", "value": html})
        if not content:
            content = [{"type": "text/plain", "value": subject}]
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": FROM_EMAIL, "name": "Card Finder"},
            "reply_to": {"email": FROM_EMAIL, "name": "Card Finder"},
            "subject": subject,
            "content": content,
        }
        if extra_headers:
            payload["headers"] = extra_headers
        try:
            resp = httpx.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
                json=payload, timeout=15,
            )
            if resp.status_code >= 400:
                print(f"SendGrid email failed: {resp.status_code} {resp.text}")
                return False
            return True
        except Exception as e:
            print(f"SendGrid email failed: {e}")
            return False

    print("No email provider configured (set BREVO_API_KEY or SENDGRID_API_KEY)")
    return False


def send_email_alert(to_email: str, card_title: str, price: float, listing_url: str, verdict: str, avg_price: float, note: str = "", alert_label: str = "", image_url: str = "", pct=None):
    if ALERTS_KILLED:
        return  # emergency kill switch — no alerts go out
    avg_line = f'<p>Average sold price: <strong>${avg_price:.2f}</strong></p>' if avg_price else ""
    price_label = "Current bid" if verdict == "auction" else "Listed at"
    note_line = f'<p style="color:#475569;">{note}</p>' if note else ""
    alert_line = (f'<p style="color:#64748b; font-size:13px; margin-top:14px;">'
                  f'Matched your alert: <strong>{alert_label}</strong></p>') if alert_label else ""

    # Card photo (image proxies are widely supported in email clients)
    image_block = (f'<p style="margin:10px 0;"><img src="{image_url}" alt="" '
                   f'style="max-width:280px; width:100%; border-radius:10px; border:1px solid #e2e8f0;"></p>') if image_url else ""

    # Deal score: how the price compares to the market (avg sold). Negative = below market.
    deal_block = ""
    deal_text = ""
    if pct is not None and verdict != "auction":
        p = round(pct)
        if p <= -5:
            color, msg = "#16a34a", f"{abs(p)}% below market"
        elif p <= 15:
            color, msg = "#0891b2", "around market value"
        else:
            color, msg = "#dc2626", f"{p}% above market"
        deal_block = (f'<p style="margin:6px 0;"><span style="background:{color}; color:#fff; '
                      f'padding:3px 10px; border-radius:6px; font-size:13px; font-weight:600;">'
                      f'Deal score: {msg}</span></p>')
        deal_text = f"Deal score: {msg}"

    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 500px;">
      <h2 style="color: #1e3a8a;">Card Finder Alert</h2>
      {image_block}
      <p style="font-size: 16px;"><strong>{card_title}</strong></p>
      <p>{price_label}: <strong style="font-size: 20px; color: #16a34a;">${price:.2f}</strong></p>
      {deal_block}
      {avg_line}
      {note_line}
      <p><a href="{listing_url}" style="background: #2563eb; color: #fff; padding: 10px 20px; border-radius: 8px; text-decoration: none; display: inline-block;">View Listing</a></p>
      {alert_line}
      <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
      <small style="color: #94a3b8;">Card Finder — manage your alerts in the app.</small>
    </div>
    """

    text_lines = [card_title, f"{price_label}: ${price:.2f}"]
    if deal_text:
        text_lines.append(deal_text)
    if avg_price:
        text_lines.append(f"Average sold price: ${avg_price:.2f}")
    if note:
        text_lines.append(note)
    text_lines += ["", f"View listing: {listing_url}"]
    if alert_label:
        text_lines.append(f"Matched your alert: {alert_label}")
    text_lines += ["", "Card Finder — manage your alerts in the app.", "Unsubscribe: reply to this email with 'unsubscribe'."]
    text_body = "\n".join(text_lines)

    _deliver_email(
        to_email,
        subject=f"Card Finder: {card_title[:60]}",
        html=html,
        text=text_body,
        list_unsub=True,
    )


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


def send_sms(to_phone: str, body: str) -> bool:
    """Send a plain SMS via Twilio (used by broadcasts — not gated by the alert
    kill switch). Returns True on success. Delivery needs A2P/toll-free reg."""
    try:
        client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(body=body, messaging_service_sid=TWILIO_MESSAGING_SID, to=to_phone)
        return True
    except Exception as e:
        print(f"SMS send failed for {to_phone}: {e}")
        return False


def _send_via_gateway(to_phone: str, carrier: str, body: str) -> bool:
    """Send a text for free via the carrier's email-to-SMS gateway (Brevo/SendGrid)."""
    gateway = CARRIER_GATEWAYS.get(carrier.lower())
    if not gateway:
        return False
    digits = "".join(c for c in to_phone if c.isdigit())[-10:]  # last 10 digits
    sms_email = f"{digits}@{gateway}"
    return _deliver_email(sms_email, subject="Card Alert", text=body)


def send_sms_alert(to_phone: str, card_title: str, price: float, listing_url: str, verdict: str, carrier: str = None, note: str = "", alert_label: str = "", image_url: str = ""):
    if ALERTS_KILLED:
        return  # emergency kill switch — no alerts go out
    body = f"Card Finder: {card_title[:60]} — ${price:.2f}"
    if note:
        body += f"\n{note}"
    if alert_label:
        body += f"\nAlert: {alert_label}"
    body += f"\n{listing_url}\nReply STOP to opt out"

    # The free carrier email-to-SMS gateway is text-only, so only use it when there's
    # no card image. With an image we go straight to Twilio MMS so the picture shows.
    if not image_url and carrier and _send_via_gateway(to_phone, carrier, body):
        return

    # Twilio (requires A2P/toll-free verification to deliver). With an image_url we
    # attach it as MMS media so the card photo shows up in the text.
    try:
        client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        kwargs = {"body": body, "messaging_service_sid": TWILIO_MESSAGING_SID, "to": to_phone}
        if image_url:
            kwargs["media_url"] = [image_url]
        client.messages.create(**kwargs)
    except Exception as e:
        print(f"SMS alert failed: {e}")
        # If MMS failed (e.g. media issue), retry as a plain text so the alert still lands.
        if image_url:
            try:
                TwilioClient(TWILIO_SID, TWILIO_TOKEN).messages.create(
                    body=body, messaging_service_sid=TWILIO_MESSAGING_SID, to=to_phone)
            except Exception as e2:
                print(f"SMS fallback failed: {e2}")


# Punchy deal grades shown at the front of every alert.
DEAL_GRADES = {
    "great_deal": "🔥 STEAL",
    "good_deal": "✅ GOOD BUY",
    "fair": "FAIR",
    "overpriced": "⚠️ PASS",
    "auction": "🔨 AUCTION",
}


def deal_grade_label(verdict: str) -> str:
    return DEAL_GRADES.get(verdict, "🆕 NEW")


def deal_grade_line(analysis: dict) -> str:
    """One-line comp for an alert, e.g. '35% under market · avg $1,770 (5 sold)'.
    Empty when there's no sold-comp data to grade against."""
    pct = analysis.get("pct_vs_market")
    avg = analysis.get("avg_sold_price") or 0
    n = analysis.get("sample_size") or 0
    if pct is None or not avg:
        return ""
    p = round(pct)
    if p <= -5:
        rel = f"{abs(p)}% under market"
    elif p <= 15:
        rel = "around market"
    else:
        rel = f"{p}% over market"
    return f"{rel} · avg ${avg:,.0f}" + (f" ({n} sold)" if n else "")


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


def send_pop_alert(user, label: str, old_pop, new_pop, cert_url: str, grade: str = "", method: str = None):
    if ALERTS_KILLED:
        return  # emergency kill switch — no alerts go out
    """Notify a user that a watched card's PSA population went up (a new copy of
    the same card+grade was graded)."""
    g = grade or "this grade"
    headline = f"New {g} graded"
    delivery = method or user.alert_method

    if delivery in ("sms", "both") and user.phone:
        body = f"Card Finder [POP UP]: {label[:60]}\nPop {old_pop} -> {new_pop} ({g})\n{cert_url}\nReply STOP to opt out"
        if not (getattr(user, "carrier", None) and _send_via_gateway(user.phone, user.carrier, body)):
            try:
                client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
                client.messages.create(body=body, messaging_service_sid=TWILIO_MESSAGING_SID, to=user.phone)
            except Exception as e:
                print(f"Pop SMS alert failed: {e}")

    if delivery in ("email", "both") and user.email:
        html = f"""
        <div style="font-family: -apple-system, sans-serif; max-width: 500px;">
          <h2 style="color: #b91c1c;">Card Finder: 📈 {headline}</h2>
          <p style="font-size: 16px;"><strong>{label}</strong></p>
          <p>PSA population at {g}: <strong style="font-size: 20px; color:#dc2626;">{old_pop} &rarr; {new_pop}</strong></p>
          <p style="color:#475569;">Another copy of this exact card and grade was just graded. If you're bidding on a pop-{old_pop} card, the scarcity just changed.</p>
          <p><a href="{cert_url}" style="background: #2563eb; color: #fff; padding: 10px 20px; border-radius: 8px; text-decoration: none; display: inline-block;">View PSA cert / pop</a></p>
          <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
          <small style="color: #94a3b8;">Card Finder — manage your pop watches in the app.</small>
        </div>
        """
        text = f"{headline}\n{label}\nPSA population at {g}: {old_pop} -> {new_pop}\nAnother copy of this exact card and grade was just graded.\n\nView PSA cert: {cert_url}"
        _deliver_email(
            user.email,
            subject=f"Card Finder: [POP UP] {label[:55]} ({old_pop}->{new_pop})",
            html=html,
            text=text,
            list_unsub=True,
        )


def send_release_alert(user, product: str, date_label: str, days_before: int, method: str = None):
    """Remind a user that a card product is about to drop (N days before its
    release date on the release calendar)."""
    if ALERTS_KILLED:
        return
    when = f"in {days_before} day{'s' if days_before != 1 else ''}" if days_before and days_before > 0 else "today"
    delivery = method or user.alert_method

    if delivery in ("sms", "both") and user.phone:
        body = f"Card Finder [RELEASE]: {product[:70]} drops {when} ({date_label}).\nReply STOP to opt out"
        if not (getattr(user, "carrier", None) and _send_via_gateway(user.phone, user.carrier, body)):
            try:
                client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
                client.messages.create(body=body, messaging_service_sid=TWILIO_MESSAGING_SID, to=user.phone)
            except Exception as e:
                print(f"Release SMS alert failed: {e}")

    if delivery in ("email", "both") and user.email:
        html = f"""
        <div style="font-family: -apple-system, sans-serif; max-width: 500px;">
          <h2 style="color: #7c3aed;">Card Finder: 🗓️ Release coming up</h2>
          <p style="font-size: 16px;"><strong>{product}</strong></p>
          <p>Drops <strong style="color:#7c3aed;">{when}</strong> — release date {date_label}.</p>
          <p style="color:#475569;">Time to line up your target sheet and presale searches.</p>
          <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;">
          <small style="color: #94a3b8;">Card Finder — manage release reminders in the Releases tab.</small>
        </div>
        """
        text = f"Release coming up: {product}\nDrops {when} — release date {date_label}.\nTime to line up your target sheet."
        _deliver_email(
            user.email,
            subject=f"Card Finder: [RELEASE] {product[:55]} drops {when}",
            html=html,
            text=text,
            list_unsub=True,
        )


def _recipients(primary, extra) -> list:
    """Primary contact plus any extras (newline/comma-separated), de-duped, in order."""
    out, seen = [], set()
    for v in [primary] + re.split(r"[,\n]+", extra or ""):
        v = (v or "").strip()
        key = v.lower()
        if v and key not in seen:
            seen.add(key)
            out.append(v)
    return out


def send_alert(user, listing: dict, analysis: dict, method: str = None, alert_label: str = ""):
    if ALERTS_KILLED:
        return  # emergency kill switch — no alerts go out
    title = listing.get("title", "")
    price = listing.get("price", 0)
    url = listing.get("listing_url", "")
    verdict = analysis.get("verdict", "unknown")
    avg = analysis.get("avg_sold_price", 0)
    pct = analysis.get("pct_vs_market")
    image_url = listing.get("image_url")
    last_sold = _last_sold_note(analysis)
    # SMS shows the deal grade comp inline (email renders its own deal-score block).
    grade_line = deal_grade_line(analysis)
    sms_note = "\n".join(x for x in [grade_line, last_sold] if x)

    # Per-alert method overrides the user's global default
    delivery = method or user.alert_method

    # SMS first — it works reliably; email may be blocked on some hosts.
    # Deliver to the primary contact plus any extra phones/emails on the account.
    if delivery in ("sms", "both"):
        for phone in _recipients(user.phone, getattr(user, "extra_phones", None)):
            send_sms_alert(phone, title, price, url, verdict, carrier=getattr(user, "carrier", None), note=sms_note, alert_label=alert_label, image_url=image_url)
    if delivery in ("email", "both"):
        for email in _recipients(user.email, getattr(user, "extra_emails", None)):
            send_email_alert(email, title, price, url, verdict, avg, note=last_sold, alert_label=alert_label,
                             image_url=image_url, pct=pct)
