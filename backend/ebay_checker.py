"""Polls eBay API every 5 minutes. When key activates: switches to real data, pushes to GitHub, restarts backend."""
import asyncio, os, httpx, subprocess
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

APP_ID = os.getenv("EBAY_APP_ID")
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
MESSAGING_SID = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
TO_PHONE = "+18187409787"
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


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
        return resp.status_code == 200 and "findItemsByKeywordsResponse" in data


def send_sms(message):
    client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
    client.messages.create(body=message, messaging_service_sid=MESSAGING_SID, to=TO_PHONE)


def switch_to_real_data():
    main_path = os.path.join(os.path.dirname(__file__), "main.py")

    # 1. Update main.py to disable mock mode
    with open(main_path, "r") as f:
        content = f.read()
    content = content.replace(
        "USE_MOCK = True  # switch to False once eBay key is active",
        "USE_MOCK = False  # eBay key active — real data only"
    )
    with open(main_path, "w") as f:
        f.write(content)
    print("Switched main.py to real data.")

    # 2. Commit and push to GitHub — triggers Render auto-deploy
    subprocess.run(["git", "add", "backend/main.py"], cwd=REPO_ROOT)
    subprocess.run(["git", "commit", "-m", "Switch to real eBay data — key is now active"], cwd=REPO_ROOT)
    subprocess.run(["git", "push"], cwd=REPO_ROOT)
    print("Pushed to GitHub — Render will auto-deploy in ~2 minutes.")

    # 3. Restart local backend too
    os.system("pm2 restart card-finder-backend")
    print("Local backend restarted.")


async def main():
    print("Polling eBay every 5 minutes...")
    while True:
        try:
            active = await check_ebay()
            if active:
                switch_to_real_data()
                send_sms(
                    "Card Finder: eBay key is LIVE! "
                    "Switching to real card listings now. "
                    "Website updates in ~2 minutes."
                )
                print("eBay key active! Switched to real data, pushed to GitHub, sent SMS.")
                break
            else:
                print("eBay key still pending...")
        except Exception as e:
            print(f"Check failed: {e}")
        await asyncio.sleep(300)


asyncio.run(main())
