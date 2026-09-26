import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type { PlanRequest, RunningWorkoutSpec } from "./types";

function yesterdayLocalISO(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

function todayLocalISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Paths never change while the backend is up, so this is fetched once. */
export const useMcpPaths = () =>
  useQuery({
    queryKey: ["mcp-paths"],
    queryFn: api.mcpPaths,
    staleTime: Infinity,
  });

export const useToday = () =>
  useQuery({
    queryKey: ["today"],
    queryFn: api.today,
    refetchInterval: 5 * 60_000,
  });

export const useYesterdaySleep = () =>
  useQuery({
    queryKey: ["sleep", "yesterday"],
    queryFn: () => api.sleep(yesterdayLocalISO()),
  });

export const useSleepHistory = (days = 14) =>
  useQuery({
    queryKey: ["sleep-history", days],
    queryFn: () => api.sleepHistory(days),
  });

/** Intraday heart rate for a single day. Defaults to today. */
export const useHeartRate = (day?: string) => {
  const target = day ?? todayLocalISO();
  return useQuery({
    queryKey: ["heart-rate", target],
    queryFn: () => api.heartRate(target),
    refetchInterval: 5 * 60_000,
  });
};

/** Walks back N days on the provider one call at a time, so keep N modest and
 *  let it go stale slowly. */
export const useSummaryHistory = (days = 14) =>
  useQuery({
    queryKey: ["summary-history", days],
    queryFn: () => api.summaryHistory(days),
    staleTime: 15 * 60_000,
  });

export const useRecentActivities = (limit = 20) =>
  useQuery({
    queryKey: ["activities", limit],
    queryFn: () => api.activities(limit),
  });

export const useActivityDetail = (id: number | null) =>
  useQuery({
    queryKey: ["activity", id],
    queryFn: () => api.activityDetail(id as number),
    enabled: id != null,
  });

export const useUpcomingWorkouts = (daysAhead = 14) =>
  useQuery({
    queryKey: ["upcoming", daysAhead],
    queryFn: () => api.upcomingWorkouts(daysAhead),
  });

export const useWorkoutTemplates = (limit = 100) =>
  useQuery({
    queryKey: ["workouts", limit],
    queryFn: () => api.listWorkouts(limit),
  });

export const useWorkoutDetail = (id: number | null) =>
  useQuery({
    queryKey: ["workout", id],
    queryFn: () => api.workoutDetail(id as number),
    enabled: id != null,
  });

export const useDevices = () =>
  useQuery({
    queryKey: ["devices"],
    queryFn: api.devices,
  });

export function useCreateRunningWorkout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (spec: RunningWorkoutSpec) => api.createRunningWorkout(spec),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["workouts"] }),
  });
}

export function useUpdateRunningWorkout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, spec }: { id: number; spec: RunningWorkoutSpec }) =>
      api.updateRunningWorkout(id, spec),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["workouts"] });
      qc.invalidateQueries({ queryKey: ["workout", vars.id] });
      // Scheduled entries render the workout's own title and structure.
      qc.invalidateQueries({ queryKey: ["upcoming"] });
    },
  });
}

export function useScheduleWorkout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, date }: { id: number; date: string }) =>
      api.scheduleWorkout(id, date),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["upcoming"] }),
  });
}

export function useDeleteWorkout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteWorkout(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workouts"] });
      qc.invalidateQueries({ queryKey: ["upcoming"] });
    },
  });
}

/** Removes one scheduled instance from the calendar. The template itself
 *  survives — that's `useDeleteWorkout`. */
export function useUnscheduleWorkout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scheduledId: number) => api.unscheduleWorkout(scheduledId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["upcoming"] }),
  });
}

/** Plan generation is a POST but reads nothing and writes nothing — a mutation
 *  purely so the page controls when it runs. */
export function usePlanPreview() {
  return useMutation({
    mutationFn: (req: PlanRequest) => api.planPreview(req),
  });
}

/** Rolling weekly plan. The status query drives whether the week card shows at
 *  all, so every mutation that starts or ends a plan invalidates it. */
export function usePlanStatus() {
  return useQuery({
    queryKey: ["plan-status"],
    queryFn: api.planStatus,
  });
}

export function usePlanWeek(offset = 0, enabled = true) {
  return useQuery({
    queryKey: ["plan-week", offset],
    queryFn: () => api.planWeek(offset),
    enabled,
    // 404 here means "no plan running", which the status query already tells us.
    retry: false,
  });
}

export function useStartRollingPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: PlanRequest) => api.planStart(req),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plan-status"] });
      qc.invalidateQueries({ queryKey: ["plan-week"] });
    },
  });
}

export function useEndRollingPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.planEnd(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plan-status"] });
      qc.removeQueries({ queryKey: ["plan-week"] });
    },
  });
}

export function useApplyPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sessions: { date: string; spec: RunningWorkoutSpec }[]) =>
      api.planApply(sessions),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workouts"] });
      qc.invalidateQueries({ queryKey: ["upcoming"] });
    },
  });
}

export function usePushWorkoutToDevice() {
  return useMutation({
    mutationFn: ({ id, deviceId }: { id: number; deviceId?: number }) =>
      api.pushWorkoutToDevice(id, deviceId),
  });
}
