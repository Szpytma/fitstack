export interface DailySummary {
  date: string;
  steps: number | null;
  step_goal: number | null;
  calories_kcal: number | null;
  distance_m: number | null;
  active_minutes: number | null;
  resting_hr: number | null;
  min_hr: number | null;
  max_hr: number | null;
  last_sync_gmt: string | null;
  wellness_start_local: string | null;
  wellness_end_gmt: string | null;
}

export interface SleepSummary {
  date: string;
  sleep_seconds: number | null;
  deep_seconds: number | null;
  light_seconds: number | null;
  rem_seconds: number | null;
  awake_seconds: number | null;
  sleep_score: number | null;
}

export interface HeartRatePayload {
  date: string;
  resting_hr: number | null;
  min_hr: number | null;
  max_hr: number | null;
  hr_values: (number | null)[][] | null;
}

export interface ActivitySummary {
  activity_id: number | null;
  name: string | null;
  type: string | null;
  start_local: string | null;
  duration_s: number | null;
  distance_m: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  calories_kcal: number | null;
  avg_speed_mps: number | null;
  elevation_gain_m: number | null;
}

export interface UpcomingWorkout {
  date: string;
  scheduled_id: number | null;
  workout_id: number;
  title: string | null;
  sport: string | null;
  atp_plan_id: number | null;
}

export interface WorkoutSummary {
  workout_id: number;
  name: string | null;
  sport: string | null;
  estimated_duration_s: number | null;
  updated: string | null;
}

export interface Device {
  device_id: number | null;
  name: string | null;
  product: string | null;
  last_sync_local: string | null;
}

export interface ActivitySeries {
  time_s: (number | null)[];
  distance_m: (number | null)[];
  hr: (number | null)[];
  pace_min_per_km: (number | null)[];
  altitude_m: (number | null)[];
  lat: (number | null)[];
  lon: (number | null)[];
}

export interface ActivityLap {
  lap: number | null;
  distance_m: number | null;
  duration_s: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_speed_mps: number | null;
  elevation_gain_m: number | null;
}

export interface ActivityHrZone {
  zone: number | null;
  seconds: number | null;
  low_bpm: number | null;
}

export interface ActivityWeather {
  temp_c: number | null;
  apparent_c: number | null;
  humidity: number | null;
  wind_kph: number | null;
  conditions: string | null;
}

export interface ActivityDetail {
  activity_id: number;
  name: string | null;
  type: string | null;
  start_local: string | null;
  duration_s: number | null;
  distance_m: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_speed_mps: number | null;
  avg_pace_min_per_km: number | null;
  calories_kcal: number | null;
  elevation_gain_m: number | null;
  elevation_loss_m: number | null;
  series: ActivitySeries;
  polyline: [number, number][];
  splits: ActivityLap[];
  hr_zones: ActivityHrZone[];
  weather: ActivityWeather;
}

// -------- workout detail (read) --------
// Mirrors GarminProvider._normalize_step — richer than the write side:
// end conditions and target types Garmin returns that we cannot yet build.
export interface WorkoutDetailStep {
  kind: string | null;
  end_condition?: string | null;
  end_value?: number | null;
  target_type?: string | null;
  target_low?: number | null;
  target_high?: number | null;
  zone?: number | null;
  iterations?: number | null;
  steps?: WorkoutDetailStep[] | null;
}

export interface WorkoutDetailSegment {
  segment_order: number | null;
  sport: string | null;
  steps: WorkoutDetailStep[];
}

export interface WorkoutDetail {
  workout_id: number;
  name: string | null;
  sport: string | null;
  estimated_duration_s: number | null;
  estimated_distance_m: number | null;
  segments: WorkoutDetailSegment[];
}

// -------- write --------
export type WorkoutStepKind =
  | "warmup"
  | "interval"
  | "recovery"
  | "cooldown"
  | "repeat";

export interface PaceTarget {
  type: "pace";
  low_mps: number;
  high_mps: number;
}
export interface HrTarget {
  type: "hr";
  low_bpm: number;
  high_bpm: number;
}
export type Target = PaceTarget | HrTarget;

export interface WorkoutStep {
  kind: WorkoutStepKind;
  /** A step ends on time or on distance, never both. */
  duration_s?: number | null;
  distance_m?: number | null;
  iterations?: number | null;
  target?: Target | null;
  steps?: WorkoutStep[] | null;
}

export interface RunningWorkoutSpec {
  name: string;
  estimated_duration_s?: number | null;
  steps: WorkoutStep[];
}

// -------- race plan --------
export type PlanPhase = "base" | "build" | "peak" | "taper" | "race";
export type PlanSessionKind = "long" | "quality" | "easy" | "recovery" | "race";

export interface PlanSession {
  date: string;
  day: string;
  kind: PlanSessionKind;
  title: string;
  distance_km: number;
  duration_s: number;
  pace_label: string;
  /** Set only in HR mode — what the watch will chase for this session. */
  hr_label?: string | null;
  note?: string | null;
  spec?: RunningWorkoutSpec | null;
}

export interface PlanWeek {
  index: number;
  start: string;
  end: string;
  phase: PlanPhase;
  volume_km: number;
  planned_km: number;
  /** Set in base mode, where time is the prescription and km only an estimate. */
  planned_minutes?: number | null;
  down_week: boolean;
  sessions: PlanSession[];
}

export interface PlanBasis {
  source: "goal_time" | "recent_activities" | "stated_volume";
  threshold_mps: number;
  threshold_pace: string;
  projected_race_time?: string | null;
  reference?: string | null;
  reference_activity_id?: number | null;
  weekly_km_observed?: number | null;
  /** What the block was actually built from, and the numbers behind it. */
  weekly_km_start?: number | null;
  volume_basis?: VolumeBasis | null;
  paces: Record<string, string>;
}

export interface VolumeBasis {
  start_km?: number | null;
  recent_km?: number | null;
  median_km?: number | null;
  best_km?: number | null;
  longest_run_km?: number | null;
  weeks_idle?: number;
}

export type PlanTargetMode = "pace" | "hr";

export type PlanHrSource = "garmin_zones" | "garmin_max_hr" | "recent_activities";

export interface PlanHrBasis {
  max_hr: number;
  source: PlanHrSource;
  reference?: string | null;
  resting_hr?: number | null;
  zones: Record<string, string>;
}

export interface RacePlan {
  race_name?: string | null;
  race_km: number;
  race_date: string;
  weeks_total: number;
  runs_per_week: number;
  long_run_day: string;
  peak_week_km: number;
  total_km: number;
  basis: PlanBasis;
  /** "pace" whenever HR retargeting was not asked for, or could not be done. */
  target_mode: PlanTargetMode;
  hr_basis?: PlanHrBasis | null;
  warnings: string[];
  weeks: PlanWeek[];
}

export interface PlanRequest {
  /** "base" is an open-ended zone 2 block — race_km and race_date are ignored. */
  mode?: "race" | "base";
  weeks?: number;
  weekly_minutes?: number | null;
  race_km?: number;
  race_date?: string;
  runs_per_week: number;
  long_run_day: string;
  weekly_km?: number | null;
  goal_time?: string | null;
  race_name?: string | null;
  /** False when planning for someone else — skips reading your Garmin history. */
  use_history?: boolean;
  /** "hr" retargets every session by heart rate instead of pace. */
  target_mode?: PlanTargetMode;
}

export interface PlanApplyResult {
  templates_created: number;
  scheduled: number;
  failures: string[];
  workout_ids: number[];
}

/** What the previous week actually delivered, against what it asked for.
 *  Reported, never acted on — the volume ramp stays anchored either way. */
export interface PlanCompliance {
  week_number: number;
  start: string;
  end: string;
  planned_km: number;
  actual_km: number;
  ratio?: number | null;
  runs_done: number;
  runs_planned: number;
}

/** Why the upcoming week advances, holds, or steps back. Deterministic — the
 *  rules live in backend/app/adapt.py, not in a model. */
export interface PlanDecision {
  week_number: number;
  action: "advance" | "hold" | "step_back";
  scale: number;
  reasons: string[];
  looked_at?: Record<string, unknown>[];
  ef_baseline?: number | null;
}

/** One week of a rolling plan, with enough context to act on it alone. */
export interface PlanWeekView {
  race_name?: string | null;
  race_km: number;
  race_date: string;
  week_number: number;
  weeks_total: number;
  weeks_remaining_after_this: number;
  target_mode: PlanTargetMode;
  basis: PlanBasis;
  hr_basis?: PlanHrBasis | null;
  warnings: string[];
  /** How the previous week actually went. Null while it is still running. */
  last_week?: PlanCompliance | null;
  /** The adaptation decision behind this week, and what it would have been. */
  decision?: PlanDecision | null;
  original_planned_km?: number | null;
  week: PlanWeek;
}

/** Where the athlete is in the block. Null when no rolling plan is running. */
export interface PlanStatus {
  race_name?: string | null;
  race_km: number;
  race_date: string;
  started: string;
  days_to_race: number;
  weeks_to_race: number;
  runs_per_week: number;
  long_run_day: string;
  target_mode: PlanTargetMode;
  anchor_weekly_km: number;
  next_week_starts: string;
}

// ---------- strength ----------

export interface StrengthExercise {
  exercise_name: string;
  sets: number;
  reps: number;
  rest_s: number;
  weight_kg?: number | null;
  category?: string | null;
}

export interface StrengthWarmup {
  exercise_name: string;
  duration_s: number;
  category?: string | null;
}

export interface StrengthWorkoutSpec {
  name: string;
  estimated_duration_s?: number | null;
  warmup?: StrengthWarmup | null;
  exercises: StrengthExercise[];
}

export type StrengthFocus = "lower" | "upper" | "upper_light";

export interface StrengthSession {
  date: string;
  day: string;
  focus: StrengthFocus;
  focus_label: string;
  title: string;
  note?: string | null;
  estimated_duration_s?: number | null;
  warmup?: StrengthWarmup | null;
  exercises: StrengthExercise[];
  spec?: StrengthWorkoutSpec | null;
}

export interface StrengthWeek {
  index: number;
  start: string;
  end: string;
  sets: number;
  reps: number;
  deload: boolean;
  note?: string | null;
  sessions: StrengthSession[];
}

/** One week of the strength block, with where it sits in the arc. */
export interface StrengthWeekView {
  plan_name: string;
  week_number: number;
  weeks_total: number;
  days: string[];
  notes: string[];
  week: StrengthWeek;
}

export interface StrengthApplyResult {
  created: number;
  scheduled: number;
  removed: number;
  failures: string[];
  workout_ids: number[];
}
