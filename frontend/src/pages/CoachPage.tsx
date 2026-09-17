import { useUpcomingWorkouts } from "@/api/hooks";
import { UpcomingWorkouts } from "@/components/UpcomingWorkouts";

export function CoachPage() {
  const q = useUpcomingWorkouts(45);
  return (
    <div className="max-w-4xl mx-auto p-4 sm:p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-slate-50">Coach schedule</h1>
        <p className="text-slate-400 text-sm">
          Next 45 days of scheduled workouts — select one to see its steps and targets
        </p>
      </header>
      <UpcomingWorkouts data={q.data} loading={q.isLoading} expandable />
    </div>
  );
}
