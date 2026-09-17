import { useState } from "react";
import { PageHeader, ErrorNotice, Spinner, Modal } from "../components/ui";
import { api, ApiError, type UserShape } from "../services/api";
import { useFetch } from "../hooks/useFetch";
import { useAuth } from "../hooks/useAuth";

const ROLE_OPTIONS = ["VIEWER", "RESEARCHER", "ADMIN"] as const;

const PROVIDER_LABEL: Record<string, string> = {
  local: "Password",
  google: "Google",
};

function RoleSelect({
  user,
  disabled,
  onDone,
}: {
  user: UserShape;
  disabled?: boolean;
  onDone: (message: string) => void;
}) {
  const [value, setValue] = useState(user.role);
  const [busy, setBusy] = useState(false);

  const change = async (next: string) => {
    if (next === user.role) return;
    if (next === "ADMIN" && user.auth_provider === "google") {
      const ok = window.confirm(
        `${user.username} signs in with Google and has no password. Grant ADMIN anyway?`
      );
      if (!ok) {
        setValue(user.role);
        return;
      }
    }
    setBusy(true);
    try {
      await api.updateUser(user.id, { role: next });
      onDone(`${user.username} is now ${next}.`);
    } catch (err) {
      onDone(err instanceof ApiError ? err.message : "Could not update the role.");
      setValue(user.role);
    } finally {
      setBusy(false);
    }
  };

  return (
    <select
      className="input !py-1 !text-xs"
      value={value}
      disabled={disabled || busy}
      onChange={(e) => {
        setValue(e.target.value);
        void change(e.target.value);
      }}
    >
      {ROLE_OPTIONS.map((role) => (
        <option key={role} value={role}>
          {role}
        </option>
      ))}
    </select>
  );
}

function NewUserForm({ onDone }: { onDone: (message: string, ok: boolean) => void }) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<(typeof ROLE_OPTIONS)[number]>("VIEWER");
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await api.createUser({ username, email, password, role });
      onDone(`Account ${username} created.`, true);
      setUsername("");
      setEmail("");
      setPassword("");
      setRole("VIEWER");
    } catch (err) {
      onDone(err instanceof ApiError ? err.message : "Could not create the account.", false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <input className="input" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} />
        <input className="input" type="email" placeholder="Email (optional)" value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <input className="input" type="password" placeholder="Password (min 8 chars)" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        <select className="input" value={role} onChange={(e) => setRole(e.target.value as (typeof ROLE_OPTIONS)[number])}>
          <option value="VIEWER">VIEWER</option>
          <option value="RESEARCHER">RESEARCHER</option>
        </select>
      </div>
      <button className="btn-primary" disabled={busy}>
        {busy ? "Creating…" : "Create account"}
      </button>
      <p className="text-[11px] text-slate-500">
        ADMIN accounts can only be created here if they sign in with a password — Google-only accounts are
        promoted from an existing role instead.
      </p>
    </form>
  );
}

export default function UsersPage() {
  const { user: me } = useAuth();
  const users = useFetch<UserShape[]>(() => api.users(), []);
  const [notice, setNotice] = useState<{ text: string; ok: boolean } | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const toggleActive = async (target: UserShape) => {
    try {
      await api.updateUser(target.id, { is_active: !target.is_active });
      setNotice({
        text: `${target.username} ${target.is_active ? "disabled" : "enabled"}.`,
        ok: true,
      });
      users.reload();
    } catch (err) {
      setNotice({
        text: err instanceof ApiError ? err.message : "Could not update the account.",
        ok: false,
      });
    }
  };

  if (users.loading) return <Spinner label="Loading users…" />;
  if (users.error) return <ErrorNotice message={users.error} onRetry={users.reload} />;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Users"
        subtitle="Manage accounts, roles and access. Registered users start as VIEWER — promote them to RESEARCHER to grant experiment rights."
        actions={
          <button className="btn-primary" onClick={() => setShowCreate(true)}>
            + New account
          </button>
        }
      />

      {notice && (
        <div
          className={`rounded-lg px-4 py-2.5 text-sm ${
            notice.ok
              ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
              : "bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300"
          }`}
        >
          {notice.text}
        </div>
      )}

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-[11px] uppercase tracking-wider text-slate-400 dark:border-slate-800">
              <th className="px-5 py-3 font-semibold">User</th>
              <th className="px-5 py-3 font-semibold">Auth provider</th>
              <th className="px-5 py-3 font-semibold">Email verified</th>
              <th className="px-5 py-3 font-semibold">Role</th>
              <th className="px-5 py-3 font-semibold">Status</th>
              <th className="px-5 py-3 text-right font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => {
              const isSelf = me?.id === u.id;
              return (
                <tr key={u.id} className="border-b border-slate-100 last:border-0 dark:border-slate-800/60">
                  <td className="px-5 py-3">
                    <div className="font-medium">{u.username}</div>
                    <div className="text-xs text-slate-400">{u.email || "—"}</div>
                  </td>
                  <td className="px-5 py-3">
                    <span className="badge">{PROVIDER_LABEL[u.auth_provider ?? "local"] ?? u.auth_provider}</span>
                  </td>
                  <td className="px-5 py-3">
                    {u.email_verified === false ? (
                      <span className="badge bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300">unverified</span>
                    ) : (
                      <span className="text-xs text-slate-400">✓</span>
                    )}
                  </td>
                  <td className="px-5 py-3">
                    <RoleSelect
                      user={u}
                      disabled={isSelf}
                      onDone={(message) => {
                        setNotice({ text: message, ok: !message.includes("Could not") });
                        users.reload();
                      }}
                    />
                  </td>
                  <td className="px-5 py-3">
                    {u.is_active ? (
                      <span className="badge bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">active</span>
                    ) : (
                      <span className="badge bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300">disabled</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <button
                      className="btn-ghost !px-2 text-xs"
                      disabled={isSelf}
                      title={isSelf ? "You cannot disable your own account." : undefined}
                      onClick={() => toggleActive(u)}
                    >
                      {u.is_active ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create account">
        <NewUserForm
          onDone={(text, ok) => {
            setNotice({ text, ok });
            if (ok) setShowCreate(false);
            users.reload();
          }}
        />
      </Modal>
    </div>
  );
}
