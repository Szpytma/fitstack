# FitStack

Local, single-user aggregator for your fitness data. Reads and writes to your
Garmin account through the unofficial `python-garminconnect` library.

- **Stage 1** ✅  FastAPI backend + Garmin read endpoints
- **Stage 2** ✅  React + Vite + Tailwind frontend, multi-page dashboard
- **Stage 3** ✅  Write ops (create/schedule/push/delete workouts), activity detail pages with maps + charts
- **Stage 4** ⏸️  Strava provider (deferred — API now behind subscription)
- **Stage 5** ⏳  SQLite persistence for historical trends

## Quickstart

```bash
# One-time
cd C:\Users\szpyt\source\repos\fitstack
npm install                                        # installs concurrently at root
cd backend && python -m venv .venv --copies && .venv\Scripts\pip install -e ".[dev]"
cp .env.example .env
cd ../frontend && npm install
cd ..

# Every time
npm run dev                                        # starts backend + frontend together
```

Then open **http://localhost:5173** in your browser.

The `dev` script runs backend on port 8000 and frontend on port 5173 via `concurrently`. Both hot-reload.

## Prerequisite: cached Garmin tokens

FitStack does **not** accept your Garmin password — it reads the cached tokens
that `python-garminconnect`'s `example.py` creates. Run this once (you'll be
prompted for email/password/MFA):

```
cd C:\Users\szpyt\source\repos\python-garminconnect
.venv\Scripts\python.exe example.py
```

Tokens live at `~/.garminconnect/garmin_tokens.json` and auto-refresh, so you
only redo this when the refresh token expires. If tokens are missing, the
frontend shows a "Garmin authentication required" screen with instructions.

## Pages

| Route | What |
|---|---|
| `/` | Dashboard — today's steps/HR/distance/calories + sleep + upcoming workouts + recent activities |
| `/activities` | List of last 50 activities, click through to detail |
| `/activities/:id` | Map (Leaflet + OpenStreetMap), HR chart, pace chart, elevation chart, HR zones, splits, weather |
| `/coach` | Next 45 days of scheduled workouts (includes Garmin Coach adaptive plan) |
| `/workouts` | Workout template list (schedule / push-to-device / delete) + custom-workout builder |

## Layout

```
fitstack/
├── package.json          concurrently launcher — `npm run dev` starts both
├── backend/
│   ├── app/
│   │   ├── main.py       FastAPI app
│   │   ├── config.py     Settings (loads .env)
│   │   ├── deps.py       DI (loads provider, raises 412 if unauth)
│   │   ├── providers/
│   │   │   ├── base.py   FitnessProvider ABC (Strava will implement this)
│   │   │   └── garmin.py python-garminconnect adapter
│   │   ├── routers/      /health /activities /coach /workouts /devices
│   │   └── schemas/      Pydantic request/response models
│   └── run.py            uvicorn launcher
└── frontend/
    ├── src/
    │   ├── App.tsx       wouter router + auth-missing gate
    │   ├── api/          Typed axios client + TanStack Query hooks
    │   ├── components/
    │   └── pages/        Dashboard / ActivitiesPage / ActivityDetailPage / CoachPage / WorkoutsPage
    └── vite.config.ts    /api → :8000 proxy, Tailwind v4 plugin
```

## Extending to Strava (future)

The provider interface (`backend/app/providers/base.py`) is the seam. To add
Strava:

1. Implement `FitnessProvider` in `providers/strava.py` (Strava-specific
   methods can raise `NotImplementedError` — routers only call the ones that
   make sense).
2. Register it in `deps.py::get_provider`.
3. Frontend gains a provider toggle (query param passed through to backend).

Zero route changes required.

## Security notes

- `python-garminconnect` is unofficial. Garmin's ToS technically prohibit
  automated access; risk is your Garmin account, not this app. Enable MFA.
- Backend has zero credential handling — only reads the tokenstore.
- Backend binds only to `127.0.0.1` (localhost). Do not expose it to the
  network without adding auth first.
- Refresh token on disk = persistent Garmin access; revoke in Garmin
  account settings if leaked.
