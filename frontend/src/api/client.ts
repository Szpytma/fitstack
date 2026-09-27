import axios, { AxiosError } from "axios";
import type {
  ActivityDetail,
  ActivitySummary,
  DailySummary,
  Device,
  HeartRatePayload,
  PlanApplyResult,
  PlanRequest,
  PlanStatus,
  PlanWeekView,
  StrengthApplyResult,
  StrengthWeekView,
  StrengthWorkoutSpec,
  RacePlan,
  RunningWorkoutSpec,
  SleepSummary,
  UpcomingWorkout,
  WorkoutDetail,
  WorkoutSummary,
} from "./types";

export const http = axios.create({
  baseURL: "/api",
  timeout: 45_000,
  // The session lives in an HttpOnly cookie; without this axios drops it.
  withCredentials: true,
});

export function isAuthMissing(err: unknown): err is AxiosError {
  return (
    err instanceof AxiosError &&
    !!err.response &&
    err.response.status === 412
  );
}

/** 401 means "sign in to FitStack" — distinct from the 412 that means
 *  "Garmin tokens are missing". */
export function isUnauthorized(err: unknown): err is AxiosError {
  return err instanceof AxiosError && err.response?.status === 401;
}

export interface FitStackUser {
  id: string;
  username: string;
  admin: boolean;
  garmin_connected: boolean;
}

export interface AuthStatus {
  configured: boolean;
  authenticated: boolean;
  user: FitStackUser | null;
}

export const authApi = {
  status: () => http.get<AuthStatus>("/auth/status").then((r) => r.data),
  setup: (username: string, password: string) =>
    http.post<AuthStatus>("/auth/setup", { username, password }).then((r) => r.data),
  login: (username: string, password: string) =>
    http.post<AuthStatus>("/auth/login", { username, password }).then((r) => r.data),
  logout: () => http.post<AuthStatus>("/auth/logout").then((r) => r.data),

  listUsers: () => http.get<FitStackUser[]>("/auth/users").then((r) => r.data),
  addUser: (username: string, password: string, admin = false) =>
    http.post<FitStackUser>("/auth/users", { username, password, admin }).then((r) => r.data),
  deleteUser: (id: string) => http.delete(`/auth/users/${id}`).then((r) => r.data),

  /** Multipart, not credentials — FitStack never asks for a Garmin password. */
  connectGarmin: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.post<{ connected: boolean }>("/auth/garmin", form).then((r) => r.data);
  },
  disconnectGarmin: () =>
    http.delete<{ connected: boolean }>("/auth/garmin").then((r) => r.data),
};

/** Absolute paths of the running backend, used to print MCP configs that
 *  actually work on this machine. */
export interface McpPaths {
  repo_root: string;
  backend_dir: string;
  python: string;
}

export const api = {
  mcpPaths: () => http.get<McpPaths>("/meta/mcp").then((r) => r.data),
  today: () => http.get<DailySummary>("/health/today").then((r) => r.data),
  summary: (day: string) =>
    http.get<DailySummary>(`/health/summary/${day}`).then((r) => r.data),
  heartRate: (day: string) =>
    http.get<HeartRatePayload>(`/health/heart-rate/${day}`).then((r) => r.data),
  sleep: (day: string) =>
    http.get<SleepSummary>(`/health/sleep/${day}`).then((r) => r.data),
  sleepHistory: (days = 14) =>
    http
      .get<SleepSummary[]>("/health/sleep-history", { params: { days } })
      .then((r) => r.data),
  summaryHistory: (days = 14) =>
    http
      .get<DailySummary[]>("/health/summary-history", { params: { days } })
      .then((r) => r.data),
  activities: (limit = 20) =>
    http
      .get<ActivitySummary[]>("/activities", { params: { limit } })
      .then((r) => r.data),
  activityDetail: (id: number) =>
    http.get<ActivityDetail>(`/activities/${id}`).then((r) => r.data),
  upcomingWorkouts: (daysAhead = 14) =>
    http
      .get<UpcomingWorkout[]>("/coach/upcoming", {
        params: { days_ahead: daysAhead },
      })
      .then((r) => r.data),
  // Step structure lives on the coach router, not /workouts/{id}.
  workoutDetail: (workoutId: number) =>
    http.get<WorkoutDetail>(`/coach/workout/${workoutId}`).then((r) => r.data),
  listWorkouts: (limit = 100) =>
    http
      .get<WorkoutSummary[]>("/workouts", { params: { limit } })
      .then((r) => r.data),
  createRunningWorkout: (spec: RunningWorkoutSpec) =>
    http
      .post<{ workout_id: number }>("/workouts/running", spec)
      .then((r) => r.data),
  // Whole-workout replacement — the id survives, so scheduled dates keep pointing at it.
  updateRunningWorkout: (workoutId: number, spec: RunningWorkoutSpec) =>
    http
      .put<{ workout_id: number }>(`/workouts/${workoutId}`, spec)
      .then((r) => r.data),
  scheduleWorkout: (workoutId: number, date: string) =>
    http
      .post<{ scheduled_id: number | null }>(`/workouts/${workoutId}/schedule`, {
        date,
      })
      .then((r) => r.data),
  deleteWorkout: (workoutId: number) =>
    http.delete<unknown>(`/workouts/${workoutId}`).then((r) => r.data),
  unscheduleWorkout: (scheduledId: number) =>
    http
      .delete<unknown>(`/workouts/schedule/${scheduledId}`)
      .then((r) => r.data),
  pushWorkoutToDevice: (workoutId: number, deviceId?: number) =>
    http
      .post<unknown>(`/workouts/${workoutId}/push`, {
        device_id: deviceId ?? null,
      })
      .then((r) => r.data),
  devices: () => http.get<Device[]>("/devices").then((r) => r.data),
  planPreview: (req: PlanRequest) =>
    http.post<RacePlan>("/plan/preview", req).then((r) => r.data),

  // Rolling weekly plan. /start computes the whole block but returns only the
  // current week, pinning the anchor the later weeks replay from.
  planStart: (req: PlanRequest) =>
    http.post<PlanWeekView>("/plan/start", req).then((r) => r.data),
  planWeek: (offset = 0) =>
    http.get<PlanWeekView>("/plan/week", { params: { offset } }).then((r) => r.data),
  planStatus: () =>
    http.get<PlanStatus | null>("/plan/status").then((r) => r.data),
  planEnd: () =>
    http.delete<{ cleared: boolean }>("/plan/active").then((r) => r.data),

  // Strength shares the running plan's anchor, so it has no start/stop of its
  // own — only the days it sits on.
  strengthWeek: (offset = 0) =>
    http.get<StrengthWeekView>("/strength/week", { params: { offset } }).then((r) => r.data),
  strengthEnable: (days: string[]) =>
    http.post<StrengthWeekView>("/strength/enable", { days }).then((r) => r.data),
  strengthDisable: () =>
    http.delete<{ cleared: boolean }>("/strength/").then((r) => r.data),
  strengthApply: (sessions: { date: string; spec: StrengthWorkoutSpec }[]) =>
    http
      .post<StrengthApplyResult>("/strength/apply", { sessions })
      .then((r) => r.data),
  planApply: (sessions: { date: string; spec: RunningWorkoutSpec }[]) =>
    http
      .post<PlanApplyResult>("/plan/apply", { sessions })
      .then((r) => r.data),
};
