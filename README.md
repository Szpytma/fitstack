# FitStack

A local dashboard for your own Garmin data — and an MCP server, so Claude can
read the same data as tools and help you plan training around it.

Everything runs on your machine. There is no hosted instance, no account with
anyone, and no API key: the backend talks to Garmin, the frontend talks to the
backend, and if you want the Claude side, your own Claude client drives the MCP
server locally.

- **Stage 1** ✅  FastAPI backend + Garmin read endpoints
- **Stage 2** ✅  React + Vite + Tailwind frontend, multi-page dashboard
- **Stage 3** ✅  Write ops (create/schedule/push/delete workouts), activity detail pages with maps + charts
- **Stage 4** ⏸️  Strava provider (deferred — API now behind subscription)
- **Stage 5** ⏳  SQLite persistence for historical trends

## What you need

- **Python 3.13+** and **Node 20+**
- A **Garmin Connect account** with some activity history
- Optional: **Claude Code** or **Claude Desktop**, if you want the MCP tools

Windows, macOS and Linux all work. Where the commands differ, both are shown.

## 1. Get Garmin tokens

FitStack **never asks for your Garmin password** — not in the UI, not in the
API, not anywhere. It reads the cached token file that
[`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect)
writes when *you* log in, in your own terminal:

```bash
git clone https://github.com/cyberjunky/python-garminconnect
cd python-garminconnect
pip install -e .
python example.py          # prompts for email, password, MFA code
```

That writes `~/.garminconnect/garmin_tokens.json`. The tokens refresh
themselves, so you normally do this once. `python-garminconnect` is an
unofficial client — see [Security notes](#security-notes).

## 2. Install and run

```bash
git clone https://github.com/Szpytma/fitstack
cd fitstack
npm install                        # root: the `concurrently` launcher only

cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"     # Windows
.venv/bin/python -m pip install -e ".[dev]"             # macOS / Linux
cp .env.example .env

cd ../frontend && npm install
cd ..

npm run dev                        # backend :8000 + frontend :5173, both hot-reload
```

Open **http://localhost:5173**.

> On Windows, Vite listens on IPv6 — use `localhost:5173`, not `127.0.0.1:5173`.

To run the backend alone, call the venv interpreter directly
(`backend/.venv/Scripts/python.exe backend/run.py`, or `.venv/bin/python` on
macOS/Linux) — the system Python does not have the dependencies.

## 3. First run: sign in

By default FitStack requires a login (`FITSTACK_REQUIRE_AUTH=true`). The first
time you open it, it offers to create the first account, which becomes the
admin. Whoever reaches an unconfigured instance first claims it, so create that
account before the app is reachable by anyone else.

Accounts are FitStack's own — **entirely separate from Garmin**. Each account
connects its own Garmin tokens by uploading `garmin_tokens.json` on the
**Account** page; the admin account also falls back to `~/.garminconnect`, so a
single-user setup needs no upload at all.

Running solo on a machine only you use? Set `FITSTACK_REQUIRE_AUTH=false` in
`backend/.env` and every request is served as the owner, straight from
`GARMINTOKENS`. The accounts code stays intact either way — that flag only
decides whether it is consulted.

## Configuration

`backend/.env`, copied from `backend/.env.example`:

| Variable | Default | What |
|---|---|---|
| `GARMINTOKENS` | `~/.garminconnect` | Directory holding `garmin_tokens.json` |
| `FITSTACK_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Origins allowed to call the API |
| `FITSTACK_STATE_DIR` | `~/.fitstack` | Accounts, per-user tokens, the active plan |
| `FITSTACK_REQUIRE_AUTH` | `true` | Whether callers must sign in |
| `STRAVA_CLIENT_ID` / `_SECRET` | empty | Reserved; Strava is not implemented |

Nothing sensitive lives inside the repo: tokens, password hashes and plan state
all sit under your home directory.

## Pages

| Route | What |
|---|---|
| `/` | Dashboard — today's steps/HR/distance/calories + sleep + upcoming workouts + recent activities |
| `/activities` | Last 50 activities, click through to detail |
| `/activities/:id` | Map (Leaflet + OpenStreetMap), HR / pace / elevation charts, HR zones, splits, weather |
| `/sleep` | 14-night sleep history |
| `/coach` | Next 45 days of scheduled workouts (includes a Garmin Coach adaptive plan) |
| `/workouts` | Workout templates — schedule / push to watch / delete, plus a builder |
| `/plan` | Training plans: build one locally, or hand the data to Claude over MCP |
| `/account` | Your Garmin connection, and (admin) the other accounts |

## Training plans

`/plan` computes plans locally — a periodised race block, or an open-ended
zone 2 base block. It is plain arithmetic over your Garmin history: no LLM, no
API key, and it writes nothing to Garmin until you explicitly schedule a week.

The same page hands you a prompt for Claude if you would rather have a plan
authored than computed, plus the MCP config for your client. `CLAUDE.md`
explains how the planner, the rolling-week anchor and the weekly adaptation
rules actually work.

## MCP server

`backend/app/mcp_server.py` exposes 20 tools over stdio — 15 reads and 5 Garmin
writes. Any MCP-capable Claude client can use them; the client brings the LLM,
so FitStack needs no API key of its own.

Claude Code and Claude Desktop want the same JSON block, with **absolute** paths
to this machine's venv interpreter and its `backend` directory. Rather than
guessing them, open `/plan` — the page prints that block filled in with the
paths of the backend you are actually running.

- **Claude Code** — copy `.mcp.json.example` to `.mcp.json` in the repo root and
  paste the block in. Sessions started in this directory pick it up, and prompt
  once to trust the server.
- **Claude Desktop** — paste it into
  `%APPDATA%\Claude\claude_desktop_config.json` (Windows) or
  `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS),
  then fully quit and restart.

The MCP server reads `GARMINTOKENS` directly and has no notion of FitStack
accounts, so it always acts as the owner of the machine it runs on.

## Layout

```
fitstack/
├── package.json           concurrently launcher — `npm run dev` starts both
├── backend/
│   ├── app/
│   │   ├── main.py        FastAPI app
│   │   ├── config.py      Settings (loads .env)
│   │   ├── auth.py        FitStack accounts — scrypt hashes, signed cookies
│   │   ├── deps.py        DI (resolves the provider, 412 if no Garmin tokens)
│   │   ├── mcp_server.py  MCP stdio server
│   │   ├── planner.py     race plan engine — pure computation
│   │   ├── base_plan.py   zone 2 base block
│   │   ├── adapt.py       week-to-week adaptation rules
│   │   ├── active_plan.py the rolling plan's pinned anchor
│   │   ├── providers/
│   │   │   ├── base.py    FitnessProvider ABC (Strava will implement this)
│   │   │   └── garmin.py  python-garminconnect adapter
│   │   ├── routers/       /auth /health /activities /coach /workouts /devices /plan
│   │   └── schemas/       Pydantic request/response models
│   └── run.py             uvicorn launcher
└── frontend/
    ├── src/
    │   ├── App.tsx        wouter router + auth gate
    │   ├── api/           typed axios client + TanStack Query hooks
    │   ├── components/
    │   └── pages/
    └── vite.config.ts     /api → :8000 proxy, Tailwind v4 plugin
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
  automated access; the risk is to your Garmin account, not to this app. Enable
  MFA.
- FitStack has zero Garmin credential handling — it only ever reads a token file
  you produced yourself.
- A refresh token on disk is persistent Garmin access. If one leaks, revoke it
  in your Garmin account settings.
- `run.py` binds `127.0.0.1` only. Exposing it on a LAN means editing that host,
  widening `FITSTACK_CORS_ORIGINS`, keeping `FITSTACK_REQUIRE_AUTH=true` and
  creating the admin account *first*. Session cookies are not `Secure`, because
  this is plain HTTP on a trusted network — do not put it on the open internet.
- Multi-user caveat: the rolling training plan is stored once per instance, not
  per account, so two accounts running rolling plans on one instance would
  overwrite each other. One account per instance is fine.

## License

MIT — see [LICENSE](LICENSE).
