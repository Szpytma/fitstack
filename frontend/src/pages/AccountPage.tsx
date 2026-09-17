import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  LogOut,
  Plus,
  ShieldCheck,
  Trash2,
  Upload,
  XCircle,
} from "lucide-react";
import { authApi, type FitStackUser } from "@/api/client";

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl bg-slate-900 border border-slate-800 p-5 space-y-4">
      <h2 className="text-slate-200 font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function GarminCard({ user }: { user: FitStackUser }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  const connect = useMutation({
    mutationFn: (f: File) => authApi.connectGarmin(f),
    onSuccess: () => qc.invalidateQueries(),
  });
  const disconnect = useMutation({
    mutationFn: () => authApi.disconnectGarmin(),
    onSuccess: () => qc.invalidateQueries(),
  });

  const error = connect.isError
    ? ((connect.error as { response?: { data?: { detail?: string } } }).response?.data
        ?.detail ?? "Upload failed.")
    : null;

  return (
    <Card title="Garmin connection">
      <div className="flex items-center gap-2 text-sm">
        {user.garmin_connected ? (
          <>
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span className="text-slate-200">Connected</span>
          </>
        ) : (
          <>
            <XCircle className="w-4 h-4 text-slate-500" />
            <span className="text-slate-400">Not connected</span>
          </>
        )}
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const f = e.dataTransfer.files?.[0];
          if (f) connect.mutate(f);
        }}
        onClick={() => fileRef.current?.click()}
        className={`rounded-lg border border-dashed p-6 text-center cursor-pointer transition-colors ${
          dragging
            ? "border-emerald-500 bg-emerald-500/5"
            : "border-slate-700 hover:border-slate-600"
        }`}
      >
        <Upload className="w-5 h-5 mx-auto text-slate-500 mb-2" />
        <div className="text-sm text-slate-300">
          {connect.isPending ? "Uploading…" : "Drop garmin_tokens.json here, or tap to choose"}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) connect.mutate(f);
            e.target.value = "";
          }}
        />
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}
      {connect.isSuccess && !error && (
        <div className="text-sm text-emerald-400">Connected. Your data should load now.</div>
      )}

      <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 space-y-2">
        <div className="flex gap-2">
          <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
          <div className="text-xs text-slate-400">
            FitStack never asks for your Garmin password. You produce the token file
            yourself and upload only that.
          </div>
        </div>
        <div className="text-xs text-slate-500 space-y-1">
          <p className="text-slate-400">To produce the file, on your own machine:</p>
          <pre className="bg-slate-900 border border-slate-800 rounded p-2 overflow-x-auto text-[11px] text-slate-300">
{`pip install garminconnect
python -c "import garminconnect,getpass;
g=garminconnect.Garmin(input('email: '),getpass.getpass());
g.login(); g.garth.dump('~/.garminconnect')"`}
          </pre>
          <p>
            That writes <span className="text-slate-300">garmin_tokens.json</span> into{" "}
            <span className="text-slate-300">~/.garminconnect</span>. Upload it above.
          </p>
        </div>
      </div>

      {user.garmin_connected && (
        <button
          onClick={() => {
            if (confirm("Forget this account's Garmin tokens?")) disconnect.mutate();
          }}
          disabled={disconnect.isPending}
          className="text-xs text-slate-500 hover:text-red-400 disabled:opacity-40"
        >
          Disconnect Garmin
        </button>
      )}
    </Card>
  );
}

function UsersCard() {
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: authApi.listUsers, retry: false });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const add = useMutation({
    mutationFn: () => authApi.addUser(username, password),
    onSuccess: () => {
      setUsername("");
      setPassword("");
      qc.invalidateQueries({ queryKey: ["users"] });
    },
  });
  const del = useMutation({
    mutationFn: (id: string) => authApi.deleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  const addError = add.isError
    ? ((add.error as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
      "Could not create the account.")
    : null;

  return (
    <Card title="Accounts">
      <ul className="divide-y divide-slate-800">
        {(users.data ?? []).map((u) => (
          <li key={u.id} className="py-2 flex items-center justify-between text-sm">
            <div>
              <div className="text-slate-100">
                {u.username}
                {u.admin && (
                  <span className="ml-2 text-[10px] uppercase tracking-wide text-emerald-400">
                    admin
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-500">
                {u.garmin_connected ? "Garmin connected" : "no Garmin yet"}
              </div>
            </div>
            {!u.admin && (
              <button
                onClick={() => {
                  if (confirm(`Delete ${u.username} and their stored tokens?`))
                    del.mutate(u.id);
                }}
                className="p-1.5 rounded text-slate-600 hover:bg-slate-800 hover:text-red-400"
                title="Delete account"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </li>
        ))}
      </ul>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-slate-800">
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="username"
          autoCapitalize="none"
          className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-100"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="password (min 8)"
          className="bg-slate-800 border border-slate-700 rounded px-3 py-2 text-sm text-slate-100"
        />
      </div>
      <button
        onClick={() => add.mutate()}
        disabled={!username || password.length < 8 || add.isPending}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-sm disabled:opacity-40"
      >
        <Plus className="w-4 h-4" /> Add account
      </button>
      {addError && <div className="text-sm text-red-400">{addError}</div>}
      <p className="text-xs text-slate-500">
        A new account starts with no Garmin connection — they sign in and upload their
        own token file. They never see your data.
      </p>
    </Card>
  );
}

export function AccountPage({ user }: { user: FitStackUser }) {
  const qc = useQueryClient();
  const logout = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <div className="max-w-3xl mx-auto p-4 sm:p-6 space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-50">Account</h1>
          <p className="text-slate-400 text-sm">
            Signed in as <span className="text-slate-200">{user.username}</span>
          </p>
        </div>
        <button
          onClick={() => logout.mutate()}
          className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-white text-sm"
        >
          <LogOut className="w-4 h-4" /> Sign out
        </button>
      </header>

      <GarminCard user={user} />
      {user.admin && <UsersCard />}
    </div>
  );
}
