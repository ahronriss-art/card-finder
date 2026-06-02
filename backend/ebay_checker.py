"""Polls eBay API every 5 minutes and texts when the key activates."""
import asyncio, os, httpx
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

APP_ID = os.getenv("EBAY_APP_ID")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
MESSAGING_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
TO_PHONE = "+18187409787"

async def check_ebay():
    params = {
        "OPERATION-NAME": "findItemsByKeywords",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "keywords": "LeBron James rookie card",
        "categoryId": "212",
        "paginationInput.entriesPerPage": "1",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get("https://svcs.ebay.com/services/search/FindingService/v1", params=params)
        data = resp.json()
        if resp.status_code == 200 and "findItemsByKeywordsResponse" in data:
            return True
        return False

def send_sms(message):
    client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
    client.messages.create(body=message, messaging_service_sid=MESSAGING_SID, to=TO_PHONE)

def switch_to_real_data():
    main_path = os.path.join(os.path.dirname(__file__), "main.py")
    with open(main_path, "r") as f:
        content = f.read()
    content = content.replace(
        "USE_MOCK = True  # switch to False once eBay key is active",
        "USE_MOCK = False  # eBay key active"
    )
    with open(main_path, "w") as f:
        f.write(content)
    print("Switched main.py to real data.")
    os.system("pm2 restart card-finder-backend")
    print("Backend restarted with real data.")

async def main():
    print("Polling eBay every 5 minutes...")
    while True:
        try:
            active = await check_ebay()
            if active:
                switch_to_real_data()
                send_sms("Card Finder: Your eBay API key is now active! The app is now showing real card listings.")
                print("eBay key is active! Switched to real data and sent SMS.")
                break
            else:
                print("eBay key still pending...")
        except Exception as e:
            print(f"Check failed: {e}")
        await asyncio.sleep(300)

asyncio.run(main())
