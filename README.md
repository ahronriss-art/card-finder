# Card Finder

Sports card deal finder. Watches eBay (and Fanatics) for listings matching saved
searches and texts/emails the moment one appears, plus a set of tools around that
for a card-buying business: photo price lookup, shop directories, auction
tracking, inventory and P&L.

> **New here? Read the [Field Manual](https://claude.ai/code/artifact/9f083078-4fce-43a6-9c14-44587445e0d2) first.**
> It covers the architecture, the deploy quirks, and the mistakes that have
> already cost real data. This README is only enough to get the app running.

## Layout

| Path | What it is |
|---|---|
| `web/` | **The live frontend** (React + Vite + TypeScript). Always edit this one. |
| `frontend/`, `frontend-new/` | Abandoned Expo apps. Not deployed, not maintained. |
| `backend/` | FastAPI app. `main.py` is the bulk of it; `alert_filters.py` holds the matching rules. |
| `backend/worker.py` | **Dead code** — not in `render.yaml`, never runs in production, drifted from `main.py`. Don't use it as a reference. |

## Setup

### Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Real values come from the Render dashboard → Environment.
# Locally you can skip Postgres entirely and run on SQLite:
DATABASE_URL="sqlite+aiosqlite:///./cardfinder.db" uvicorn main:app --reload
```

The alert scan runs *inside* the web app (an asyncio loop started in the FastAPI
lifespan), so there is no separate worker process to start.

### Frontend

```bash
cd web
npm install
npm run dev
```

Verify TypeScript changes with `npm run build` (`tsc -b && vite build`) — **not**
`tsc --noEmit`. Build mode is what Vercel runs and is stricter; a change that
passes `--noEmit` can still fail the deploy and leave the old bundle serving.

## Deploys

Both halves deploy from `main` on push, and **both auto-deploys are unreliable** —
assume your push did not ship until you verify it.

| Half | Host | URL |
|---|---|---|
| `web/` | Vercel | `26cards.vercel.app` |
| `backend/` | Render | `card-finder-backend.onrender.com` |
| Database | Neon Postgres | via `DATABASE_URL` on Render |

- **Backend:** after pushing, use Render → Manual Deploy → Deploy latest commit.
  Confirm by probing a route that only exists in the new code.
- **Frontend:** `vercel deploy --prod --yes` from the repo root. Never pass
  `--prebuilt` — it bakes an empty `VITE_API_URL` and points production at
  `localhost:8000`. See the Field Manual.

## Services

Secrets live in the Render dashboard under Environment; nothing sensitive is in
the repo.

| Service | What for | Notes |
|---|---|---|
| eBay Browse API | Live listings — the only reliable source | Quota is **per application**, shared with your laptop |
| Brevo | All outgoing email | HTTP API, not SMTP (Render blocks SMTP ports) |
| Twilio | Alert SMS/MMS | Toll-free verified |
| Groq | Most AI features (vision, chat, parsing) | Free tier |
| Neon | Production Postgres | Point-in-time branch restore is the recovery path |
| PSA API | Cert lookup + population | Free tier is ~1 call/day; degrades gracefully |

## Health checks

| Endpoint | Tells you |
|---|---|
| `/health` | Process is up (stays 200 even if the database is down) |
| `/health/db` | Database is actually reachable, and the driver's error if not |
| `/alert-status` | Alert pipeline health: staleness, call budget, sends per day |

When alerts stop, check `/health/db` first.
