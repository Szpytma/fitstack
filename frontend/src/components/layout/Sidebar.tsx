import { Link, useLocation } from "wouter";
import {
  Activity,
  CalendarDays,
  Dumbbell,
  LayoutDashboard,
  Moon,
  Sparkles,
  UserCircle,
  type LucideIcon,
} from "lucide-react";

const NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/activities", label: "Activities", icon: Activity },
  { href: "/sleep", label: "Sleep", icon: Moon },
  { href: "/coach", label: "Coach", icon: CalendarDays },
  { href: "/workouts", label: "Workouts", icon: Dumbbell },
  { href: "/plan", label: "AI Plan", icon: Sparkles },
  { href: "/account", label: "Account", icon: UserCircle },
];

function isActive(location: string, href: string): boolean {
  return href === "/" ? location === "/" : location.startsWith(href);
}

/** Desktop navigation. Hidden below `md` — a fixed 224px column leaves barely
 *  any room on a phone, so `<BottomNav>` takes over there. */
export function Sidebar() {
  const [location] = useLocation();
  return (
    <aside className="hidden md:flex w-56 shrink-0 border-r border-slate-800 bg-slate-950 p-4 flex-col">
      <div className="text-slate-50 text-xl font-semibold mb-6 tracking-tight">
        Fit<span className="text-emerald-400">Stack</span>
      </div>
      <nav className="flex flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = isActive(location, href);
          return (
            <Link
              key={href}
              href={href}
              className={
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors " +
                (active
                  ? "bg-slate-800 text-slate-100"
                  : "text-slate-400 hover:bg-slate-900 hover:text-slate-200")
              }
            >
              <Icon className="w-4 h-4" />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto text-slate-600 text-xs">v0.3.0 · Garmin</div>
    </aside>
  );
}

/** Phone navigation: a fixed tab bar. `pb-[env(safe-area-inset-bottom)]` keeps
 *  the tabs clear of the iOS home indicator. */
export function BottomNav() {
  const [location] = useLocation();
  return (
    <nav
      className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-slate-800 bg-slate-950/95 backdrop-blur pb-[env(safe-area-inset-bottom)]"
      aria-label="Main"
    >
      <ul className="flex">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = isActive(location, href);
          return (
            <li key={href} className="flex-1 min-w-0">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={
                  "flex flex-col items-center gap-0.5 py-2 text-[10px] leading-tight transition-colors " +
                  (active ? "text-emerald-400" : "text-slate-500 hover:text-slate-300")
                }
              >
                <Icon className="w-5 h-5 shrink-0" />
                <span className="truncate max-w-full px-0.5">{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Phone header — the sidebar carries the wordmark on desktop. */
export function MobileHeader() {
  return (
    <header className="md:hidden sticky top-0 z-30 border-b border-slate-800 bg-slate-950/95 backdrop-blur px-4 py-3">
      <div className="text-slate-50 text-lg font-semibold tracking-tight">
        Fit<span className="text-emerald-400">Stack</span>
      </div>
    </header>
  );
}
