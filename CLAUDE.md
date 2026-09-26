# FitStack

Local, single-user aggregator for your Garmin fitness data. FastAPI backend + React
frontend, plus an MCP server so Claude clients can query/mutate your data as tools.

Provider abstraction (`backend/app/providers/base.py::FitnessProvider`) leaves a slot
for Strava, but Strava is **not** implemented (their API moved behind subscription).

## Stack

- **Backend** — Python 3.13, FastAPI, Pydantic 2, `garminconnect` (unofficial
  Garmin Connect wrapper, MIT). Runs on `127.0.0.1:8000`.
- **Frontend** — React 19, Vite 6, TypeScript, Tailwind CSS v4, TanStack Query 5,
  wouter (router — react-router-dom had active CVEs), Recharts, Leaflet, lucide-react.
  Runs on `localhost:5173` (Windows quirk: Vite listens IPv6-only, don't use
  `127.0.0.1:5173`).
- **MCP** — `mcp>=2.0.0` (`mcp.server.MCPServer`), stdio transport.
  20 tools exposed in `backend/app/mcp_server.py`.

## Layout

```
fitstack/
├── .mcp.json                   # Claude Code MCP config (auto-detected)
├── package.json                # concurrently: npm run dev = backend + frontend
├── backend/
│   ├── .venv/                  # python venv (use its python.exe, not system)
│   ├── pyproject.toml
│   ├── run.py                  # uvicorn entrypoint
│   └── app/
│       ├── main.py             # FastAPI app, version="0.3.0"
│       ├── config.py           # Settings, reads .env
│       ├── deps.py             # get_garmin() → HTTP 412 if not authed
│       ├── mcp_server.py       # MCP stdio server, reuses GarminProvider
│       ├── planner.py          # race-plan engine — pure computation, no I/O
│       ├── base_plan.py        # zone 2 base block — HR in, minutes out
│       ├── adapt.py            # week-to-week adaptation rules (deterministic)
│       ├── active_plan.py      # the rolling plan's pinned anchor (only persisted state)
│       ├── providers/
│       │   ├── base.py         # FitnessProvider ABC
│       │   └── garmin.py       # GarminProvider — the workhorse
│       ├── routers/            # health, activities, coach, workouts, devices, plan
│       └── schemas/            # Pydantic response models
└── frontend/
    ├── vite.config.ts          # /api → 127.0.0.1:8000 proxy
    └── src/
        ├── App.tsx             # wouter routes: /, /activities/:id, /sleep, /coach, /workouts, /plan
        ├── api/{client,hooks,types}.ts
        ├── components/         # layout/{Sidebar,AuthMissing}, SectionCard, StatCard, ...
        └── pages/              # Dashboard, ActivitiesPage, ActivityDetailPage, SleepPage, CoachPage, WorkoutsPage, PlanPage
```

## Running

```powershell
# One-time: create venv + install deps + seed Garmin tokens
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
# Then run python-garminconnect's example.py once to write ~/.garminconnect/garmin_tokens.json

cd ../frontend && npm install
cd .. && npm install

# Every session:
npm run dev        # starts backend + frontend concurrently
```

Backend must be launched via the venv Python, not system Python:
`backend/.venv/Scripts/python.exe backend/run.py` if running solo.

## Auth model

**Zero password handling in FitStack.** Both the backend and the MCP server read
cached tokens from `~/.garminconnect/garmin_tokens.json`. Seed them by running
`python-garminconnect`'s `example.py` interactively (it prompts, MFA-aware,
writes the tokens file).

Missing tokens → backend returns HTTP 412, frontend `App.tsx` detects via
`isAuthMissing()` and renders `<AuthMissing />` with the exact command to run.

## MCP integration

The MCP server exposes 20 tools (15 read + 5 Garmin writes). Any Claude client can use it
to build training plans, correlate sleep/HR, create/schedule workouts, etc. **No
Anthropic API key needed** — the client handles the LLM side.

- **Claude Code**: `.mcp.json` at repo root is auto-detected. First launch prompts
  to trust the server.
- **Claude Desktop**: paste the JSON block shown on the `/plan` page into
  `%APPDATA%\Claude\claude_desktop_config.json`, then restart.

Write tools (`create_running_workout`, `schedule_workout`, `unschedule_workout`,
`delete_workout`, `push_workout_to_device`) mutate Garmin state — always confirm
before calling them.

## Race planning — two paths, deliberately

The UI cannot call MCP tools: MCP needs an LLM to drive it, and the backend takes
no API key. So `/plan` offers both halves instead:

- **"Build the plan here"** → `POST /plan/preview` → `planner.py`. Deterministic,
  computed from Garmin history, no LLM anywhere. Writes nothing.
- **"Copy prompt"** → hands a filled-in prompt to Claude Code/Desktop, which reads
  the same data through the MCP tools and authors the plan itself.

`POST /plan/apply` is the only write path: it dedupes sessions by spec so a 12-week
plan uploads a handful of templates rather than ~50, then schedules each on every
date it recurs. Garmin is happy to hold one template on many dates — each scheduling
call returns its own instance id. `generate_race_plan` is the MCP mirror of `/plan/preview` — it also
writes nothing.

## Rolling weekly plans

The whole block at once, or a week at a time — Garmin Coach style. `POST /plan/start`
(MCP: `start_training_plan`) computes the full periodised block but returns only the
current week and pins an anchor; `GET /plan/week` (MCP: `get_training_week`) hands
back each later week, rebuilt against fresh Garmin history. `GET /plan/status` and
`DELETE /plan/active` round it out. Nothing here writes to Garmin — the returned
sessions still carry a `spec`, so scheduling goes through the usual confirmed
`create_running_workout` + `schedule_workout`.

**Paces float, volume is pinned.** Each rebuild re-derives threshold from recent
runs, so the plan tracks fitness; the volume ramp stays anchored to the start week,
so one sick or heavy week cannot drag the whole block up or down.

## Aerobic base mode (`base_plan.py`)

`mode: "base"` is a different planner, not a flag on the race one. No race, no
taper, no endpoint: an open-ended zone 2 block for building aerobic base. Three
inversions, and they are the whole point:

- **HR is the input, pace is the output.** `target_mode: "hr"` on a *race* plan takes
  pace-derived sessions and translates them to bpm. Here the band is the
  prescription — whatever pace it produces today is the correct pace today.
- **Progression is in minutes.** At fixed HR distance is an outcome. Prescribing km
  would force the athlete out of the zone to hit them on a slow day, which is the
  exact habit this exists to break. `planned_minutes` is the target; `planned_km` is
  an estimate from current EF, shown only so the week has a distance on it.
- **Progress is EF, not pace.** `adapt.efficiency_factor` rising at constant HR *is*
  the adaptation. Chasing pace directly puts you back in zone 3.

The zone 2 band comes from `provider.heart_rate_zones()` and is **never** inferred —
`zone2_band` raises without configured zones, because here the band is the workout.
The long run may drift to the zone 2/3 boundary: cardiac drift does that anyway past
an hour, and pretending otherwise has the athlete walking to hold a number.

Output shape matches `build_plan` deliberately, so the rolling-week machinery,
adaptation and the Garmin push all work on it unchanged. Sessions are a single
time-based step with an `HrTarget`, which is what the watch wants anyway.

Why it exists: the mode was written for an account whose easy runs almost all
landed in zone 3 rather than zone 2. That is the grey-zone trap, and a race plan
with threshold and VO2 work stacked on top of it is how people get cooked. Check
the zone split of recent runs before reaching for a race plan.

## Adaptation (`adapt.py`)

Each week is checked against what actually happened, Garmin-Coach style. Pure
functions of (plan, activities) — no I/O, no LLM — because six weeks into a block
"why was week 5 lighter?" must give the same answer every time.

**Conservative: every rule needs the same signal in two consecutive weeks.** With
four runs a week one week is too small a sample, and a plan that lurches every seven
days has stopped being a plan.

| signal (×2 weeks) | action |
|---|---|
| under 70% of planned km | hold — level at the previous week |
| no runs at all | step back to 75% |
| over 130% of plan | hold, so the extra does not compound |
| EF under 95% of baseline | hold at 90% — same work, more heartbeats |

Effort is **efficiency factor**: metres per minute per heartbeat. Only aerobic runs
count (60-85% of max HR — a 5K time trial posts a high EF and means nothing here), a
week is its *median*, and the comparison is against a baseline median from before the
plan, never the week before.

Two mechanical points that are easy to get wrong:

- **A hold must never raise volume.** Levelling at the previous week lands *above*
  plan whenever the upcoming week is already lighter — any down week, every taper
  week. `_hold_scale` clamps to 1.0.
- **Never re-level against an already-adjusted block.** `adapted_view` builds the
  block unadjusted first and measures decisions against *that*, then rebuilds with
  the accumulated scales. Otherwise each hold becomes the new normal and the plan
  ratchets downwards.

Decisions feed back through `PlanInput.week_scale`, so the planner shapes the
sessions at the adjusted volume — long-run caps and spill logic still apply. Scaling
the sessions afterwards would break both.

The calendar never moves. Weeks are anchored backwards from the race date, so
inserting a repeat week would have to steal one from the peak phase; re-levelling the
week in place keeps the taper where it belongs.

`last_week` reports the raw numbers alongside the decision, so a week that fell short
without triggering a rule still says so.

`build_plan` needed no changes for any of this — it already anchors weeks *backwards*
from the race date, so replaying it with the original `start_date` reproduces the
same calendar weeks with the same phases.

`target_mode: "hr"` retargets every session by heart rate. The retarget runs
**last**, after all distances and durations are derived from pace — only what the
watch chases changes, so pace-mode and HR-mode plans have identical volume. Bands
come from `provider.heart_rate_zones()` (the athlete's configured Garmin max HR and
zone floors); if Garmin has no zone setup it falls back to the median of the three
highest run HRs, and says so in `warnings`.

## Tests

```powershell
cd backend
.venv\Scripts\python.exe -m pytest        # ~0.2s, no network, no Garmin
```

`backend/tests/` covers the planning core — the pure, deterministic half of the
app, which is both the easiest to test and the part where a silent regression
costs a training block. Fixtures are literal activity dicts (`tests/conftest.py`),
so nothing needs an account.

What is pinned, and why each one:

- **A golden 24-week marathon block** — phase, `planned_km` and long run for
  every week. Not sacred numbers; a change to `volume_curve` or `long_run_curve`
  simply has to say out loud which weeks it moved.
- **Taper never rises**, in volume or long run. The same failure `_hold_scale`
  guards on the adaptation side.
- **Long-run progression survives the spill rule.** Use a history whose longest
  recent run is well under what the curve wants (`runs=6, long_share=8/40`),
  or the clamp never binds and the test proves nothing.
- **Replay identity**, and that a *stateless* rebuild loses the taper — the
  failure `active_plan.py`'s pins exist to prevent, stated as a test.
- **One bad week changes nothing**; two consecutive ones hold. Plus a hold into
  a down week never lifting it.
- **EF rejects time trials and interval sessions**, because both post numbers
  that say nothing about easy running.
- **`zone2_band` refuses to guess** — base mode will not build without
  configured zones.

Measure the long run by `kind == "long"`, never by the longest session: an early
threshold workout with warmup and cooldown can out-distance it.

## Non-obvious things

- **Garmin weather temp** — comes back in the user's account unit. Heuristic in
  `garmin.py::activity_detail`: if `temp > 45`, treat as Fahrenheit and convert.
- **`get_activity_details()`** returns time-series but no summary — we also call
  `get_activity()` for the summaryDTO (name, duration, HR).
- **Coach targets** are `"no.target"` in templates because Garmin Coach pushes
  targets to the watch at runtime based on current fitness.
- **Adaptive training plan endpoints** (`/trainingplan/plans/{id}`, `/fbt-adaptive/{id}`)
  404 for the user's ATP — library gap. Workout templates + scheduled workouts work.
- **Steps not showing** usually means Bluetooth sync is off on the watch, not a
  code bug.
- **Hot reload is off by default** (`FITSTACK_RELOAD`). uvicorn's reloader has
  been seen to log a detected change and never start the replacement worker,
  leaving the old one holding `127.0.0.1:8000` — so the backend answers from
  stale code while looking healthy, and a fresh start fails with `[Errno 10048]`.
  If that happens, find the orphan before restarting:
  `Get-CimInstance Win32_Process -Filter "Name='python.exe'"`.
- **`/health/sleep-history` and `/summary-history`** walk back one provider call
  per day — 14 days ≈ 4s, and `days` accepts up to 60. Gaps are normal (watch off
  the wrist) so a short list is valid, but `_collect_days` logs every skipped day
  and 502s if *nothing* came back. Don't reintroduce a bare `except: continue`.
- **Chart colors** — emerald `#10b981` fails the dark-surface lightness band; bars
  use `#059669` (emerald-600). HR series is `#ef4444` everywhere. Single-series
  charts only — no dual-axis.
- **Max HR: read it, don't infer it.** `get_heart_rate_zones()` returns the
  athlete's configured `maxHeartRateUsed` and `zone{1..5}Floor`. Always read it at
  runtime via `provider.heart_rate_zones()` — never quote or hardcode the number,
  here or anywhere else; it drifts with age and fitness and any copy goes stale.
  Inferring from activity history under-reads badly for anyone training
  deliberately easy, which is why `estimate_max_hr()` is the fallback for accounts
  with no zone setup, not the default path. Trap: the `hr_zones` embedded in an
  *activity* is a historical snapshot of the zones in force that day, not current
  config — reading it as current is what makes plans silently wrong.
  `_HR_BANDS` ratio cut-points are calibrated against the planner's own emitted
  pace bands (recovery ≈0.69 of threshold speed, long 0.74, easy 0.76, threshold
  0.98, interval 1.07); guess them and every aerobic session collapses into one band.
- **A rolling plan cannot be stateless.** Regenerating a week with
  `start_date = today` looks right and is silently broken: `total_weeks` shrinks by
  one each week, so `phase_for(0, total, taper)` returns `"base"` forever and
  `volume_curve` restarts its four-week cycle before a down week ever lands. You get
  a plan that never progresses and never tapers. `active_plan.py` pins `start_date`
  and `anchor_weekly_km` to prevent exactly this — don't "simplify" them away.
- **Anchor on `planned_km`, not `volume_km`.** A week's `volume_km` is the sum of its
  rounded session distances; `planned_km` is the volume curve's actual target. Only
  the latter replays the block identically.
- **`PlanWeek.index` is 1-based** (`planner.py:860`), unlike the 0-based `week_idx`
  that `phase_for` and `volume_curve` take internally.
- **Never key scheduled workouts on `workout_id`** — anywhere. One template
  legitimately recurs across many dates, so keying on it drops every date after the
  first. `UpcomingWorkouts` uses `scheduled_id` for its React keys, and
  `GarminProvider.upcoming_workouts` deduplicates on the calendar item's `id` for
  the same reason. It did key on `workoutId` once, which silently hid one day of
  every base week — the sessions were scheduled correctly in Garmin the whole time,
  they just never came back from the read.

## Constraints

- Don't accept or forward passwords anywhere. Ever. Tokens only.
- Don't add API keys or LLM calls on the backend — the MCP path is deliberate.
- Don't add Strava code until the API access story changes; keep the ABC slot warm.
- Provider methods on `FitnessProvider` are the contract; new features go through it.
- TanStack Query hooks live in `src/api/hooks.ts`; add mutations with proper
  `invalidateQueries` so the UI stays fresh after writes.

## Current state (2026-07-29)

v0.3.0 shipped. Dashboard (stat tiles + intraday HR chart + 14-day steps trend +
sleep + upcoming + recent), Activities list + detail (map + charts + splits + HR
zones + weather), Sleep page (14-night history), Coach view, Workouts (list +
create + schedule + push + delete), AI Plan (`/plan` — local planner + MCP
handoff), and MCP server with 20 tools. Sidebar footer reads `v0.3.0 · Garmin`.

Wired but never exercised against live Garmin: `POST /plan/apply` and the
unschedule control on `UpcomingWorkouts`. Both are real writes; they typecheck and
render, but no one has clicked them yet.

**Rolling weekly plans (2026-09-16)** — backend, MCP and UI, verified end to end
against the live account: the block advances base→build→peak→taper across weekly
calls, replay is identical to the original, and paces move with fitness while volume
holds. `/plan` gets a "Start weekly plan" button beside "Build the plan here" (same
form) and a `RollingPlanCard` with week navigation and a per-week Garmin push.

The UI is the default path, not chat: asking Claude for the same week costs tokens and
an LLM round-trip to return what the planner computed anyway. MCP earns its place only
when something the planner cannot measure — illness, travel, a niggle — should change
the week.

Still unexercised against live Garmin: the actual write. "Schedule this week" is the
much safer first test of `/plan/apply` — four sessions instead of fifty.
