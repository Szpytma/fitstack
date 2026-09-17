import { StatCard } from "@/components/StatCard";
import { SleepCard } from "@/components/SleepCard";
import { RecentActivities } from "@/components/RecentActivities";
import { UpcomingWorkouts } from "@/components/UpcomingWorkouts";
import { HeartRateChart } from "@/components/HeartRateChart";
import { VolumeTrend } from "@/components/VolumeTrend";
import {
  useHeartRate,
  useRecentActivities,
  useSummaryHistory,
  useToday,
  useUpcomingWorkouts,
  useYesterdaySleep,
} from "@/api/hooks";
import { Flame, Footprints, HeartPulse, Route } from "lucide-react";

export function Dashboard() {
  const today = useToday();
  const sleep = useYesterdaySleep();
  const activities = useRecentActivities(10);
  const upcoming = useUpcomingWorkouts(14);
  const heartRate = useHeartRate();
  const history = useSummaryHistory(14);

  const stepGoalProgress =
    today.data?.steps && today.data.step_goal
      ? today.data.steps / today.data.step_goal
      : undefined;
  const km = today.data?.distance_m ? (today.data.distance_m / 1000).toFixed(2) : "—";
  const lastSync = today.data?.last_sync_gmt
    ? new Date(today.data.last_sync_gmt + "Z").toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

  return (
    <div className="max-w-6xl mx-auto p-4 sm:p-6 space-y-6">
      <header className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-50">Dashboard</h1>
          <p className="text-slate-400 text-sm">
            {today.data?.date ?? "—"} · last watch sync {lastSync}
          </p>
        </div>
        {today.isFetching && <span className="text-xs text-slate-500">refreshing…</span>}
      </header>

      <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Steps"
          value={today.data?.steps?.toLocaleString() ?? "—"}
          sub={today.data?.step_goal ? `goal ${today.data.step_goal.toLocaleString()}` : undefined}
          progress={stepGoalProgress}
          icon={<Footprints className="w-4 h-4" />}
        />
        <StatCard label="Distance" value={`${km} km`} icon={<Route className="w-4 h-4" />} />
        <StatCard
          label="Calories"
          value={today.data?.calories_kcal ? Math.round(today.data.calories_kcal).toLocaleString() : "—"}
          sub="kcal"
          icon={<Flame className="w-4 h-4" />}
        />
        <StatCard
          label="Heart rate"
          value={today.data?.resting_hr ? `${today.data.resting_hr} bpm` : "—"}
          sub={
            today.data?.min_hr && today.data?.max_hr
              ? `min ${today.data.min_hr} · max ${today.data.max_hr}`
              : undefined
          }
          icon={<HeartPulse className="w-4 h-4" />}
        />
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <HeartRateChart data={heartRate.data} loading={heartRate.isLoading} />
        <VolumeTrend data={history.data} loading={history.isLoading} />
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SleepCard data={sleep.data} loading={sleep.isLoading} href="/sleep" />
        <UpcomingWorkouts data={upcoming.data} loading={upcoming.isLoading} href="/coach" />
      </section>

      <section>
        <RecentActivities data={activities.data} loading={activities.isLoading} href="/activities" />
      </section>
    </div>
  );
}
