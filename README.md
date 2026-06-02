# Card Finder

Sports card price tracker and deal finder.

## Setup

### Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys in .env
uvicorn main:app --reload
```

### Background Alert Worker (separate terminal)
```bash
cd backend
source venv/bin/activate
python worker.py
```

### Frontend (mobile app)
```bash
cd frontend
npm install
npx expo start
```

## API Keys You Need

| Service | What for | Where to get |
|---------|----------|--------------|
| eBay App ID | Search listings + sold history | developer.ebay.com |
| Anthropic | AI deal analysis | console.anthropic.com |
| Twilio | SMS alerts | twilio.com |
| SendGrid | Email alerts | sendgrid.com |
