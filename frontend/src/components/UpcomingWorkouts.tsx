import { useState } from "react";
import type { UpcomingWorkout } from "@/api/types";
import { useUnscheduleWorkout } from "@/api/hooks";
import { CalendarDays, ChevronDown, ChevronRight, X } from "lucide-react";
import { SectionCard } from "./SectionCard";
import { WorkoutPreview } from "./WorkoutPreview";

interface Props {
  data?: UpcomingWorkout[];
  loading?: boolean;
  href?: string;
  /** Let each row open its step structure. The dashboard stays compact; the
   *  Coach schedule turns this on. */
  expandable?: boolean;
}

function relDay(iso: string): string {
  const d = new Date(iso + "T00:00");
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const diff = Math.round((d.getTime() - now.getTime()) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function Row({ w, expandable }: { w: UpcomingWorkout; expandable: boolean }) {
  const [open, setOpen] = useState(false);
  const unschedule = useUnscheduleWorkout();

  const title = w.title ?? "Workout";
  const meta = (
    <div className="text-slate-500 text-xs">
      {w.sport ?? "—"}
      {w.atp_plan_id ? " · Garmin Coach" : ""}
    </div>
  );

  return (
    <li className="py-3 text-sm group">
      <div className="flex items-center justify-between gap-2">
        {expandable ? (
          <button
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            title={open ? "Hide steps" : "Show steps"}
            className="min-w-0 flex items-center gap-2 text-left"
          >
            {open ? (
              <ChevronDown className="w-4 h-4 text-slate-500 shrink-0" />
            ) : (
              <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 shrink-0" />
            )}
            <div className="min-w-0">
              <div className="text-slate-100 font-medium truncate">{title}</div>
              {meta}
            </div>
          </button>
        ) : (
          <div className="min-w-0">
            <div className="text-slate-100 font-medium truncate">{title}</div>
            {meta}
          </div>
        )}

        <div className="flex items-center gap-2 shrink-0">
          <div className="text-slate-300 text-xs">{relDay(w.date)}</div>
          {/* Garmin Coach owns its own calendar entries, so removing one can
              leave its plan inconsistent — worth saying, not worth blocking.
              The template itself survives either way. */}
          {w.scheduled_id != null && (
            <button
              title="Remove from calendar"
              aria-label={`Remove ${title} from ${w.date}`}
              onClick={() => {
                const coachWarning = w.atp_plan_id
                  ? "\n\nThis one belongs to a Garmin Coach plan — Coach may re-add or reshuffle it."
                  : "";
                if (
                  confirm(
                    `Remove "${title}" from ${w.date}?\n\nThe workout template stays on your account.${coachWarning}`,
                  )
                ) {
                  unschedule.mutate(w.scheduled_id as number);
                }
              }}
              disabled={unschedule.isPending}
              className="p-1 rounded text-slate-600 hover:bg-slate-800 hover:text-red-400 disabled:opacity-40 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {expandable && open && <WorkoutPreview workoutId={w.workout_id} />}

      {unschedule.isError && (
        <div className="mt-2 text-xs text-red-400">
          Could not remove that workout — {(unschedule.error as Error).message}
        </div>
      )}
    </li>
  );
}

export function UpcomingWorkouts({ data, loading, href, expandable = false }: Props) {
  return (
    <SectionCard title="Upcoming workouts" icon={<CalendarDays className="w-4 h-4 text-slate-400" />} href={href}>
      {loading || !data ? (
        <div className="text-slate-500 text-sm">Loading…</div>
      ) : data.length === 0 ? (
        <div className="text-slate-500 text-sm">Nothing scheduled.</div>
      ) : (
        <ul className="divide-y divide-slate-800">
          {data.map((w) => (
            // A single template recurs across many dates in a race plan, so the
            // workout id alone is not unique in this list.
            <Row key={w.scheduled_id ?? `${w.workout_id}-${w.date}`} w={w} expandable={expandable} />
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
