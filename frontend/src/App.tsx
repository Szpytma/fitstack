import { Route, Switch } from "wouter";
import { BottomNav, MobileHeader, Sidebar } from "@/components/layout/Sidebar";
import { AuthMissing } from "@/components/layout/AuthMissing";
import { Dashboard } from "@/pages/Dashboard";
import { ActivitiesPage } from "@/pages/ActivitiesPage";
import { ActivityDetailPage } from "@/pages/ActivityDetailPage";
import { CoachPage } from "@/pages/CoachPage";
import { PlanPage } from "@/pages/PlanPage";
import { SleepPage } from "@/pages/SleepPage";
import { WorkoutsPage } from "@/pages/WorkoutsPage";
import { AccountPage } from "@/pages/AccountPage";
import { useQuery } from "@tanstack/react-query";
import { LoginScreen } from "@/components/layout/LoginScreen";
import { useToday } from "@/api/hooks";
import { authApi, isAuthMissing, type FitStackUser } from "@/api/client";

export default function App() {
  // Sign-in state gates everything, so it is resolved before any data query is
  // allowed to run — otherwise the whole app fires requests that 401.
  const auth = useQuery({
    queryKey: ["auth-status"],
    queryFn: authApi.status,
    retry: false,
    staleTime: 60_000,
  });

  if (auth.isLoading) {
    return <div className="min-h-screen bg-slate-950" />;
  }

  if (auth.isError) {
    return (
      <div className="min-h-screen bg-slate-950 text-slate-300 flex items-center justify-center p-6 text-sm">
        Cannot reach the FitStack backend.
      </div>
    );
  }

  if (!auth.data?.authenticated) {
    return <LoginScreen configured={auth.data?.configured ?? false} />;
  }

  return <AuthedApp user={auth.data.user!} />;
}

function AuthedApp({ user }: { user: FitStackUser }) {
  // Any query surfaces the auth-missing state; we pick `today` because
  // it's already used by the dashboard and cheap.
  const today = useToday();

  // A brand-new account has no Garmin tokens yet, so every data query 412s.
  // Sending them to the "run example.py" screen would be a dead end — they
  // need the Account page to upload the file. Take them straight there.
  if (today.isError && isAuthMissing(today.error) && !user.garmin_connected) {
    return (
      <div className="min-h-screen flex bg-slate-950 text-slate-100">
        <Sidebar />
        <main className="flex-1 min-w-0 overflow-x-hidden">
          <MobileHeader />
          <div className="pb-20 md:pb-0">
            <AccountPage user={user} />
          </div>
        </main>
        <BottomNav />
      </div>
    );
  }

  if (today.isError && isAuthMissing(today.error)) {
    const detail =
      (today.error as { response?: { data?: { detail?: string } } }).response
        ?.data?.detail ?? undefined;
    return (
      <div className="min-h-screen bg-slate-950 text-slate-100">
        <AuthMissing detail={detail} />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex bg-slate-950 text-slate-100">
      <Sidebar />
      {/* min-w-0 stops a wide child (charts, dense rows) forcing the flex item
          wider than the viewport and reintroducing a horizontal scroll. */}
      <main className="flex-1 min-w-0 overflow-x-hidden">
        <MobileHeader />
        {/* Clear the fixed tab bar so the last card is never trapped under it. */}
        <div className="pb-20 md:pb-0">
        <Switch>
          <Route path="/" component={Dashboard} />
          <Route path="/activities" component={ActivitiesPage} />
          <Route path="/activities/:id">
            {(params) => <ActivityDetailPage id={Number(params.id)} />}
          </Route>
          <Route path="/sleep" component={SleepPage} />
          <Route path="/coach" component={CoachPage} />
          <Route path="/workouts" component={WorkoutsPage} />
          <Route path="/plan" component={PlanPage} />
          <Route path="/account">{() => <AccountPage user={user} />}</Route>
          <Route>
            <div className="p-8 text-slate-400">Page not found.</div>
          </Route>
        </Switch>
        </div>
      </main>
      <BottomNav />
    </div>
  );
}
