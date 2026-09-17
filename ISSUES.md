# FitStack — tracked issues

Opened 2026-09-17, from an audit of `planner.py` against marathon-training
literature plus the author's own Garmin data (observed 4.5 km/week, 1 of 26 runs
in zone 2, threshold 5:31/km off a 5 km in 26:08, marathon 2027-04-25).

Priority: **P1** blocks using the app to train for the marathon · **P2** wrong or
missing signal · **P3** quality of life.

---

## #1 — P1 — Long run never progresses beyond ~16 km on a marathon block

`long_run_km` (`backend/app/planner.py:258`) takes 30–33% of the week, and
`peak_volume` (`planner.py:252`) caps weekly volume at `start_km * 1.6`. So the
long run is structurally bounded by the start volume, and `_LONG_RUN_CAP`'s 32 km
for the marathon (`planner.py:63`) is unreachable below ~97 km/week.

Computed for this account (start 30 km, 42.195 km, 24 weeks): peak week 48.0 km,
**longest run in the whole block 15.8 km** (week 21). That is a half-marathon
plan wearing a marathon label.

Fix: make the long run progress in absolute terms toward a marathon-appropriate
peak, time-capped rather than distance-capped — 2.5–3 h, which at this athlete's
long pace (7:05–7:53/km) is ~23–25 km, not 32. The share-of-week rule stays as a
ceiling, not as the only driver.

Acceptance: a 24-week marathon block off 30 km/week peaks its long run above
20 km, and no long run exceeds 3 h at the plan's own long pace.

---

## #2 — P1 — Stated weekly volume is never sanity-checked against observed

`build_plan` (`planner.py:723`) takes `stated or observed`. `floor`
(`planner.py:725`) only ever *raises* a too-small number, and the goal-time sanity
check (`planner.py:744`) has no volume equivalent. Typing 30 km/week against an
observed 4.5 km/week produces a week-1 plan of 30 km over 4 runs — a ~7× jump —
silently, with no warning.

Fix: when `stated` exceeds `observed` by more than ~50%, append a warning naming
both numbers. Consider starting nearer the observed figure unless the athlete
confirms.

Acceptance: stated 30 vs observed 4.5 surfaces a warning in `warnings`.

---

## #3 — P2 — No guard on single-run progression

A BJSM cohort of 5200+ runners found materially higher overuse-injury risk when a
*single run* exceeds 110% of the longest run in the previous 30 days, independent
of weekly volume. The planner has no such rule: week 1 here prescribes a 9.0 km
long run against a 5.0 km 30-day longest (+80%).

Fix: clamp the first weeks' long runs to 110% of the 30-day longest observed run,
and warn when clamped. Pure computation over activities — belongs next to
`adapt.py`.

---

## #4 — P1 — Race more than 24 weeks out leaves the current week unreachable

`total_weeks = max(4, min(24, days_out // 7))` (`planner.py:701`) caps the block at
24 weeks and anchors it *backwards* from race day. Started 2026-09-17 for a
2027-04-25 marathon (31 weeks), the block runs 2026-11-09 → 2027-04-25, so
`GET /plan/week?offset=0` returns 400:

> No plan week starts on 2026-09-21 — this block runs 2026-11-09 to 2027-04-25.

Offsets 0–6 all 400. For seven weeks the rolling plan shows nothing at all.

Fix: when the race is further out than the cap, fill the lead-in — the aerobic
base block (`base_plan.py`) is the right occupant of exactly that window — or at
minimum say so instead of erroring.

---

## #5 — P2 — Interval sessions are read as whole-activity averages

Two places read summary fields and so misread structured sessions
(e.g. 5 km warmup + 10×1 km + 2 km cooldown):

- `adapt.efficiency_factor` (`adapt.py:119`) uses `avg_hr` / `avg_speed_mps`. An
  interval session typically averages 80–85% HRmax, passes the aerobic window
  (`AEROBIC_LO/HI = 0.60/0.85`) and pollutes the weekly EF median with a number
  that blends reps and jog recoveries.
- `threshold_from_activities` (`planner.py:142`) runs Riegel over the whole
  activity, so a strong 10×1 km projects as a slow 10K and never registers as
  fitness — the best threshold measurement of the week is discarded.

Per-lap data already exists (`get_activity_splits` → `lapDTOs`,
`providers/garmin.py:164`) but only in the single-activity detail endpoint.

Fix: (a) exclude structured sessions from EF; (b) read laps for quality sessions
and derive threshold from the rep average. (a) alone silences the noise; (b)
recovers the signal.

---

## #6 — P2 — Plan sessions cannot be previewed before they are pushed

`SessionRow` (`frontend/src/components/RollingPlanCard.tsx:139`) renders one line
per session — day, title, km, band. The `spec` is present in the data but used
only for the push (line 184). Step structure is visible only via
`WorkoutPreview` → `StepList`, which takes a `workout_id` and therefore works only
after the workout exists in Garmin.

Fix: expand a session row into its steps. `StepList` is already exported
(`WorkoutPreview.tsx:106`); it needs an adapter from the plan's `WorkoutStep`
shape to `WorkoutDetailStep`.

---

## #7 — P3 — Workout steps are time-based only

`WorkoutStep` (`backend/app/schemas/health.py:149`) carries `duration_s` and no
distance, and `create_running_workout` (`providers/garmin.py:447`) builds every
step with `create_*_step(dur, …)`. "10×1 km" is therefore not expressible — it
becomes "10×4:00".

Fix: add `distance_m` to the step schema and the matching Garmin end condition.

---

## #8 — P3 — No marathon-pace work inside long runs

`quality_session` (`planner.py:520`) gives the peak phase a standalone
`Race pace N×15min`, and long runs are always entirely easy. Marathon-pace
segments inside the long run are a staple of marathon preparation.
