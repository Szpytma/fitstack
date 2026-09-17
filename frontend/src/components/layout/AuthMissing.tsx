import { KeyRound } from "lucide-react";

export function AuthMissing({ detail }: { detail?: string }) {
  return (
    <div className="max-w-2xl mx-auto p-8">
      <div className="rounded-xl border border-amber-800 bg-amber-950/40 p-6">
        <div className="flex items-center gap-3 mb-3">
          <KeyRound className="w-6 h-6 text-amber-300" />
          <h1 className="text-lg font-semibold text-amber-100">
            Garmin authentication required
          </h1>
        </div>
        <p className="text-amber-100/80 text-sm leading-6">
          FitStack does not accept passwords itself — it reads the cached
          Garmin tokens created by <code className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-200">python-garminconnect</code>.
        </p>
        <p className="mt-3 text-amber-100/80 text-sm">
          Open a terminal and run this <strong>once</strong> (you will be
          prompted for your email, password, and MFA code if enabled):
        </p>
        <pre className="mt-3 p-3 rounded-lg bg-slate-950 border border-slate-800 text-emerald-300 text-xs overflow-x-auto">
{`cd C:\\Users\\szpyt\\source\\repos\\python-garminconnect
.venv\\Scripts\\python.exe example.py`}
        </pre>
        <p className="mt-3 text-amber-100/70 text-xs">
          Tokens are saved to <code className="px-1 py-0.5 rounded bg-slate-800">~/.garminconnect/garmin_tokens.json</code>{" "}
          and auto-refresh, so you should only need to do this once (or when
          your refresh token expires). Once done, reload this page.
        </p>
        {detail && (
          <p className="mt-4 text-xs text-amber-200/50">
            Backend said: <em>{detail}</em>
          </p>
        )}
      </div>
    </div>
  );
}
