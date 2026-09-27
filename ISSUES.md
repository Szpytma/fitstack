# FitStack — tracked issues

Tracking lives on GitHub: <https://github.com/Szpytma/fitstack/issues>. This file
is the offline summary.

Priority: **P1** blocks trusting the app to train on · **P2** wrong or missing
signal · **P3** quality of life.

---

## Done (2026-09-17)

The first round came out of an audit of `planner.py` against marathon-training
literature plus this account's own Garmin history.

| # | what | shipped in |
|---|---|---|
| 1 | Long run never progressed past ~16 km on a marathon block | #9 |
| 2 | Stated weekly volume never checked against history | #9 |
| 3 | Race beyond the 24-week cap left the current week returning 400 | #10 |
| 4 | No guard on single-run progression (+10% vs 30-day longest) | #10 |
| 5 | Interval sessions read as whole-activity averages | #11 |
| 7 | Workout steps were time-based only — "10 × 1 km" inexpressible | #12 |
| 6 | Plan sessions could not be previewed before being pushed | #16 |
| 8 | No marathon-pace work inside long runs | #15 |
| — | Starting volume read from a four-week mean including zero weeks | #17 |
| — | Warmup and cooldown reached the watch with no pace target | #17 |

Two of these were fixed by the same PR for a reason. #4's progression clamp was
defeated on its first outing by the spill rule, which exists to stop an easy day
out-distancing the long run and did so by pushing the long run back up past the
ceiling that had just been computed.

---

## Done (2026-09-27)

| # | what | shipped in |
|---|---|---|
| 27 | Strength blocks: planner, provider, API, MCP and UI | #28 |
| — | One template per scheduled date — shared templates vanished off the watch | #28 |
| — | A week ending today counted as unfinished, so the Sunday ask missed it | #28 |
| — | Re-basing a plan dropped the weeks already run | #28 |

The three fixes came out of building the strength block, not from an audit. The
template one had been misdiagnosed twice: first blamed on Garmin Connect refusing
duplicate scheduling (it does not), then on `upcoming_workouts` deduplicating by
`workoutId` (real, but a different bug). The actual cause is the **watch**, which
ties completion to the template and drops every date sharing it.

---

## Open

### #18 — P1 — No tests at all for 2825 lines of planning logic

Pure computation, no I/O, fully deterministic — the easiest code here to test,
and there is not one test. Everything verified so far was checked with throwaway
scripts. Golden snapshot of a block, taper never rises, clamp survives spill,
replay identity, `weekly_volume` edge cases, `laps.is_structured` on real runs.

### #19 — P2 — Distance-based warmup/cooldown still never uploaded

Downgraded from P1 and narrowed. `POST /plan/apply`, `unschedule` and `delete`
have now all run against the live account many times over — a full base week
scheduled, removed and re-pushed, plus the new strength path. What remains
untested is the *distance* variant from #12: warmup and cooldown on distance are
assembled by hand because the library only ships
`create_distance_interval_step`, and no race plan has been pushed since.

### #20 — P2 — `anchor_weekly_km` is pinned at plan start, but the block can open weeks later

Started 2026-09-17 for a race on 2027-04-25, the block opens 2026-11-09. The
athlete is asked in September for a number describing November, with seven weeks
of base training in between whose purpose is to change it. The seam shows:
lead-in week 7 ends at ~16 km, block week 1 opens at 30 km.

### #21 — P2 — Marathon runway warning does not fire at exactly 12 weeks

The condition is `total_weeks < 12`; the message says "16+ is the usual runway".
A 12- to 15-week marathon block is warned about not at all. The account's current
plan is exactly 12 weeks.

### #22 — P3 — Dev loop: `uvicorn --reload` never completes, and the old worker keeps the port

The reloader logs the change and never starts a new worker; killing the parent
leaves an orphan holding port 8000, so a fresh backend fails to bind and requests
are still answered by the old code.

---

## Known and deliberate

- **Recovery steps carry no pace target.** The jog between reps should be as slow
  as it needs to be.
- **Easy runs and long runs have no separate warmup.** An easy run is its own
  warmup. In a marathon-pace long run the easy lead-in *is* the warmup, and
  putting a separate one in front would defeat the session — the point is goal
  pace on tired legs.
- **The long run may exceed 33% of the week.** For a low-volume marathoner it has
  to; `MAX_LONG_SHARE` (40%) is the backstop.

## Not yet examined

`retarget.py` and `review.py` were never read during the audit. The rest of the
planning modules were.
