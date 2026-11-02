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
  23 tools exposed in `backend/app/mcp_server.py`.

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
│       ├── strength_plan.py    # gym block on the running days
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

The MCP server exposes 23 tools (17 read + 6 Garmin writes). Any Claude client can use it
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

## Strength (`strength_plan.py`)

Gym work placed on the days the athlete already runs — lifting in the evening,
running in the morning — so the rest days stay genuinely restful. Spreading the
sessions out instead leaves no day where the body is left alone.

**The long-run day carries no loaded leg work.** That single rule shapes the whole
module: squats on the evening of the week's longest run buy soreness that costs
the next two runs and return nothing. That day gets upper body and hips instead.
The rule follows the *day*, not the label — move the long run and the leg work
moves off it, which is what `test_long_run_day_rule_follows_the_day_not_the_name`
pins.

Volume is low and reps few on purpose: strength for a runner, not hypertrophy.
Weights are never prescribed — the athlete's working loads are theirs to know, and
a number invented here would be useless or dangerous. Progression runs in
four-week blocks whose down weeks line up with `base_plan.minutes_curve`, so the
easy week is easy in both disciplines at once.

`strength_days` lives on `ActivePlan`, not in a second state file, so the strength
block shares the running block's `start_date` and `weeks` by construction. Two
anchors would drift apart within a month.

### Garmin's exercise catalogue, the hard way

- **The (category, exercise) pair is validated.** Pass an exercise with a category
  it does not belong to and the upload succeeds while silently dropping the
  exercise name — the watch then shows a blank movement. Never override
  `category`; let the provider resolve it from the display name.
- **An exercise whose key equals its category comes back blank** (`CALF_RAISE`,
  `CARDIO`, `INDOOR_BIKE`). Harmless: the category alone renders correctly.
- **A rowing machine is not representable.** It exists only as "Calorie Row",
  which the catalogue files under `LATERAL_RAISE` — Garmin's own miscategorisation.
  **A ski erg is absent entirely.** Machines that do round-trip cleanly:
  `Treadmill`, `Stair Stepper`, `Elliptical`, `Indoor Bike`. Use `Cardio` for
  anything else and let the athlete pick the machine.
- **Warm-ups are time-based, every strength builder is rep-based.** The timed step
  is assembled by hand in `GarminProvider.create_strength_workout`; `ExecutableStep`
  allows extras, which is how the exercise category rides along with it.

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

**EF is the whole-activity figure, and must stay that way.** Measuring only the
steady kilometres — dropping an easy run's strides and their jog-backs, as
`laps.steady_laps` once did — is more faithful to any single run, and was tried
and reverted. `decide` compares the week against `ef_baseline`, the four weeks
*before* the block, and `history.attach_laps` reaches 8 runs within 56 days, so
the baseline can never be lapped however the limits are tuned. That leaves a
lap-aware numerator over a whole-activity denominator: a ~4% methodology gap
against the 5% `EF_DECLINE` rule, enough to hold volume for no reason or to mask
a real decline. It also makes a *past* week's EF move whenever a new run pushes
an old one out of the lapped set, so "why was week 5 lighter?" stops having one
answer. If this is ever revisited, both sides of the comparison have to be
measured the same way first.

A strides session is not the problem it looks like. Its surges do not reliably
lift the blended figure: on a real one the surge block read EF 0.807 against the
easy kilometres' 0.895, because heart rate rockets through six accelerations
while the average pace over surges *and* recoveries does not. The bias is
small, constant week to week, and conservative.

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

**Compliance is judged in the unit the plan prescribes**, and there is exactly one
place that decides which: `adapt.report_week`. `active_plan.compliance` delegates to
it rather than counting kilometres itself, which is what it used to do — so a base
week run slower than planned showed as *over* target on the `/plan` card while the
engine saw a shortfall. At a fixed heart rate distance is an outcome, so the two
units disagree by design, and the athlete was being shown the one the engine
ignores. `PlanCompliance.unit` carries the answer to the UI; read `ratio` against
it, never against `actual_km`.

`build_plan` needed no changes for any of this — it already anchors weeks *backwards*
from the race date, so replaying it with the original `start_date` reproduces the
same calendar weeks with the same phases.

`target_mode: "hr"` retargets every session by heart rate. The retarget runs
**last**, after all distances and durations are derived from pace — only what the
watch chases changes, so pace-mode and HR-mode plans have identical volume. Bands
come from `provider.heart_rate_zones()` (the athlete's configured Garmin max HR and
zone floors); if Garmin has no zone setup it falls back to the median of the three
highest run HRs, and says so in `warnings`.

## Training metrics (`/stats`)

Garmin's own read of where the athlete is: VO2max, training status and load
balance, HRV, training readiness, fitness age, race predictions, weigh-ins.
None of it is reproducible from activity history — the watch computes these from
data the API never exposes per sample — so they are read, not derived.

Six provider methods rather than one fat call, so a provider can serve the ones
it has; each defaults to `NotImplementedError` like `create_strength_workout`,
which keeps the Strava slot warm without stub methods.

- **`GET /stats/overview` tolerates partial failure on purpose.** It stitches
  six independent upstream endpoints together, and any of them can be missing
  for an account (no HRV-capable watch, no fitness age before enough data
  accumulates) or simply down. Each block is nullable, `warnings` names what did
  not arrive, and only an empty result 502s. Don't "simplify" this into one
  try/except around the lot — one dead endpoint would blank the page.
- **`GET /stats/weeks` applies the adaptation scales.** Planned minutes come
  from replaying the block *and then* `adapt.scales_through`, because that is
  what the athlete was actually given; `/plan/week` serves the adapted figure,
  so quoting the unadjusted one here would disagree with the calendar and the
  watch. Two passes, same as `active_plan.adapted_view`, and for the same
  reason — see "Never re-level against an already-adjusted block".
- **Read height, never derive it.** `get_user_profile()["userData"]["height"]`
  is centimetres. Body-mass targets are meaningless without it, and working it
  back out of a reported BMI is circular (that BMI came from the height) and
  breaks silently when Garmin changes its rounding. BMI 30 is the only
  body-mass reference line on the chart with a clinical meaning; Garmin's own
  fitness-age model targets BMI 21, which is not a realistic goal for most
  people and belongs in the component table, not as a line.

### Garmin's shapes, the hard way

- **Readiness is a list, and the score collapses after a session.** Garmin
  rewrites it several times a day. One hard run took this account from 70 to 22
  with a 46-hour recovery time — that reading says the run was hard, not that
  the athlete is unready. Take the `AFTER_WAKEUP_RESET` entry. The midnight
  reading is no good either: it lands before sleep is scored, so `validSleep`
  is false and there is no sleep score at all. The provider still returns the
  day's last reading as `latest_score`/`latest_recovery_time_min`, which is the
  honest way to show "today's session cost this much".
- **Acute and chronic load are nested.** `acwrStatus`,
  `dailyTrainingLoadAcute`, `dailyTrainingLoadChronic` and
  `dailyAcuteChronicWorkloadRatio` live under `acuteTrainingLoadDTO`, not on the
  training-status entry. Reading them off the entry gives null and looks like an
  account without the metric.
- **Several metrics are keyed by device.** `latestTrainingStatusData` and
  `metricsTrainingLoadBalanceDTOMap` are maps of `deviceId` to entry. An account
  with two watches gets two entries; take the freshest `calendarDate`, because
  `primaryTrainingDevice` is not always set.
- **`trainingStatus` is an opaque integer.** The meaning is in
  `trainingStatusFeedbackPhrase` (`RECOVERY_2`, `STRAINED_3`), so both travel
  together and neither is interpreted in the backend.
- **`vo2MaxValue` is rounded, `vo2MaxPreciseValue` is what the watch shows.**
- **Weigh-ins are manual and sparse, and a day can hold several.**
  `get_body_composition` returns grams. Keep the first entry per day (the
  morning one) and expect long gaps — this is not a continuous series, so a
  chart must not interpolate it into one.

### `adapt.week_series` vs `adapt.report_week`

`report_week` answers "how did plan week 5 go". `week_series` answers "what has
the training looked like" — calendar weeks, spanning the time before the block
opened, with no opinion about what was planned.

- **Weeks with no runs are absent, not zero.** A gap in training is not a week
  of zero volume; drawing it as one implies a measurement nobody took, and a
  reader cannot tell "ran nothing" from "no data".
- **EF is not comparable across training eras,** which is why `since` exists.
  It rises with intensity *inside* the aerobic window, so short efforts near the
  top of the band out-score genuinely easy running: this account reads 0.95-1.0
  for 2025's 5K efforts and 0.78-0.86 through the base block, and the earlier
  figure is not the better fitness. The UI starts the chart at the current era
  and says so on the card.

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

- **Garmin weather temp** — comes back in the account's unit, and the payload
  names no unit anywhere. `garmin.py::weather_temps_celsius` infers it **once
  per reading**, never per field: the unit is one account-level setting, so a
  reading is wholly Fahrenheit or wholly Celsius. Deciding per value splits one
  reading across both scales as soon as one field crosses the threshold and
  another does not — `46/43/43` came back as 7.8 C beside a literal 43 C "feels
  like", on a 7 C London morning. `dewPoint` is read as evidence only and never
  reported; three fields are much harder to fool than one. Residual limit: a
  cold Fahrenheit reading whose every field sits below the threshold is
  indistinguishable from Celsius and stays unconverted.
  **`windSpeed` has the same root cause and is not handled.** It is mapped
  straight to `wind_kph`, so a Fahrenheit account's figure is really mph.
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
- **`metadataDTO.sensors` lists what was *paired*, not what measured.** An
  activity's `deviceId` is only the watch that recorded the file, so it never
  names a chest strap; `GET /activity-service/activity/{id}` returns
  `metadataDTO.sensors`, a list carrying each associated sensor's
  `serialNumber` (matches `list_devices()`), `bleDeviceType` and battery state,
  or `None` when none was associated. The `/sensors` sub-path 404s; it is a
  field on the activity, not an endpoint.
  **Do not read it as the source of the HR series.** An account has been seen
  with the strap listed, `batteryStatus: OK`, while the athlete reports the
  strap never connected and the watch recorded through a sleeve — the field
  reflects pairing, not delivery, and Garmin exposes no per-sample source.
  Two attempts to tell the sources apart from the series failed: sample-to-sample
  jitter is flattened by the chart API to 0.5-1.6 bpm on every run, and
  speed/HR correlation is dominated by cardiac drift (negative on clean easy
  runs, so a positive value proves nothing). **Ask the athlete** — what they
  wore is better evidence than anything in the payload. This matters because a
  wrist sensor with no skin contact can read 40-50 bpm low while the athlete
  paces off it: one easy run was logged at HR 90-124 while actually being run
  at 5K race pace.
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
- **One template per scheduled date — never share one across days.** Garmin
  Connect is happy to hold a template on many dates, and the calendar shows both.
  *The watch is not*: completing the workout marks the **template** done and drops
  it from the device, taking every other date that shares it. A base week with two
  identical easy runs lost the second one off the wrist while Connect still listed
  it. `/plan/apply` and `/strength/apply` therefore key on `(date, spec)`. The
  extra templates are the price of sessions that stay on the watch — which is also
  why a whole block should be pushed a week at a time, not at once.
- **A week ending today is finished.** The cadence this is built for is "ask after
  the Sunday long run", so on that Sunday the week just run has to count as
  evidence. `adapt.completed_weeks` and `active_plan.compliance` use `end > today`
  to exclude, not `end >= today`.
- **Re-basing a plan must keep the weeks already run inside it.** Restarting with
  `start_date = today` drops them: the week numbering lies, and `adapt` loses the
  history it judges against — it sees zero finished weeks and never fires a rule.
  `PlanRequest.start_date` backdates the anchor for exactly this.
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

**Stats page (2026-10-26)** — `/stats` in the UI over `GET /stats/{overview,weight,weeks}`,
verified against the live account: all six upstream reads returned, `warnings` empty,
and the planned-minutes figure agrees with `/plan/week` by construction. Sidebar and
bottom nav gain a "Stats" entry. The recovery charts reuse `/health/summary-history`
and `/health/sleep-history` rather than adding endpoints. `adapt.week_series` is the
new pure function behind the week chart, covered by `tests/test_week_series.py`.
