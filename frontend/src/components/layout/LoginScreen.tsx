import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Lock, ShieldCheck } from "lucide-react";
import { authApi } from "@/api/client";

interface Props {
  /** False on a fresh install — the first visitor chooses the password. */
  configured: boolean;
}

export function LoginScreen({ configured }: Props) {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: ({ u, p }: { u: string; p: string }) =>
      configured ? authApi.login(u, p) : authApi.setup(u, p),
    onSuccess: () => {
      // Re-run every query that previously 401'd.
      qc.invalidateQueries();
    },
  });

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);
    if (!configured) {
      if (password.length < 8) {
        setLocalError("Use at least 8 characters.");
        return;
      }
      if (password !== confirm) {
        setLocalError("The two passwords do not match.");
        return;
      }
    }
    submit.mutate({ u: username, p: password });
  }

  const serverError = submit.isError
    ? ((submit.error as { response?: { data?: { detail?: string } } }).response?.data
        ?.detail ?? "Something went wrong.")
    : null;

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-slate-950">
      <div className="w-full max-w-sm">
        <div className="text-slate-50 text-2xl font-semibold tracking-tight mb-1">
          Fit<span className="text-emerald-400">Stack</span>
        </div>
        <p className="text-slate-500 text-sm mb-6">
          {configured
            ? "Sign in to reach your Garmin data."
            : "Choose a password to protect this instance."}
        </p>

        <form
          onSubmit={onSubmit}
          className="rounded-xl bg-slate-900 border border-slate-800 p-5 space-y-4"
        >
          <label className="block">
            <div className="text-xs text-slate-400 mb-1">Username</div>
            <input
              autoFocus
              autoCapitalize="none"
              autoCorrect="off"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={configured ? "" : "e.g. pawel"}
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-slate-100"
            />
          </label>

          <label className="block">
            <div className="text-xs text-slate-400 mb-1">Password</div>
            <input
              type="password"
              autoComplete={configured ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-slate-100"
            />
          </label>

          {!configured && (
            <label className="block">
              <div className="text-xs text-slate-400 mb-1">Confirm password</div>
              <input
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded px-3 py-2 text-slate-100"
              />
            </label>
          )}

          <button
            type="submit"
            disabled={!username || !password || submit.isPending}
            className="w-full py-2 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium disabled:opacity-40 inline-flex items-center justify-center gap-2"
          >
            <Lock className="w-4 h-4" />
            {submit.isPending
              ? "…"
              : configured
                ? "Sign in"
                : "Set password"}
          </button>

          {(localError || serverError) && (
            <div className="text-sm text-red-400">{localError ?? serverError}</div>
          )}
        </form>

        {!configured && (
          <div className="mt-4 rounded-lg bg-slate-900/60 border border-slate-800 p-3 flex gap-2">
            <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
            <div className="text-xs text-slate-400 space-y-1">
              <p>
                This is FitStack's own password — nothing to do with Garmin. Your
                Garmin login is never asked for or stored.
              </p>
              <p className="text-slate-500">
                Anyone reaching this instance before you set a password could claim
                it, so do this now if the app is on your network.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
