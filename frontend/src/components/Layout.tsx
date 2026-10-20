import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";
import { useFetch } from "../hooks/useFetch";
import { api } from "../services/api";
import type { DemoStatus } from "../types";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "▦" },
  { to: "/experiments", label: "Experiments", icon: "⧉" },
  { to: "/datasets", label: "Datasets", icon: "▤" },
  { to: "/models", label: "Models", icon: "◈" },
  { to: "/results", label: "Results", icon: "≣" },
  { to: "/reports", label: "Reports", icon: "⤓" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button onClick={toggle} className="btn-ghost" title="Toggle dark / light mode" aria-label="Toggle theme">
      {theme === "dark" ? "☀ Light" : "☾ Dark"}
    </button>
  );
}

const ADMIN_NAV = [{ to: "/users", label: "Users", icon: "◍" }];

export default function Layout() {
  const { user, autoSignedIn } = useAuth();
  const demo = useFetch<DemoStatus>(() => api.demoStatus(), []);

  return (
    <div className="flex h-full min-h-screen">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950 md:flex">
        <div className="flex items-center gap-2 px-5 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-700 text-white">𝓓</div>
          <div>
            <div className="text-sm font-bold tracking-tight">DiffMIA</div>
            <div className="text-[10px] text-slate-400">contamination lab</div>
          </div>
        </div>
        <nav className="mt-2 flex-1 space-y-0.5 px-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-brand-50 text-brand-800 dark:bg-brand-950 dark:text-brand-300"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900"
                }`
              }
            >
              <span className="w-4 text-center text-slate-400">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
          {user?.role === "ADMIN" &&
            ADMIN_NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition ${
                    isActive
                      ? "bg-brand-50 text-brand-800 dark:bg-brand-950 dark:text-brand-300"
                      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-900"
                  }`
                }
              >
                <span className="w-4 text-center text-slate-400">{item.icon}</span>
                {item.label}
              </NavLink>
            ))}
        </nav>
        <div className="border-t border-slate-200 px-4 py-3 text-[11px] leading-relaxed text-slate-400 dark:border-slate-800">
          Detect benchmark memorization through differential model behavior.
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-h-screen flex-1 flex-col md:pl-56">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-950/80">
          <div className="flex items-center justify-between gap-3 px-4 py-2.5 md:px-8">
            <div className="flex items-center gap-3">
              <span className="text-sm font-semibold md:hidden">DiffMIA</span>
              <nav className="hidden items-center gap-1 md:flex">
                {NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `rounded-md px-2 py-1 text-xs font-medium ${
                        isActive
                          ? "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-white"
                          : "text-slate-500 hover:text-slate-900 dark:text-slate-400"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
              </nav>
              {user?.role === "ADMIN" &&
                ADMIN_NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `rounded-md px-2 py-1 text-xs font-medium ${
                        isActive
                          ? "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-white"
                          : "text-slate-500 hover:text-slate-900 dark:text-slate-400"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
            </div>
            <div className="flex items-center gap-2">
              {demo.data?.mode === "DEMO" && (
                <span className="badge bg-amber-100 text-amber-800 ring-1 ring-amber-300 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-800">
                  ◉ DEMO MODE
                </span>
              )}
              <ThemeToggle />
              <div
                className="hidden text-right sm:block"
                title={
                  autoSignedIn
                    ? "Session established by the server (AUTO_LOGIN_ENABLED) — this build has no login page"
                    : undefined
                }
              >
                <div className="text-xs font-medium">{user?.username}</div>
                <div className="text-[10px] uppercase tracking-wide text-slate-400">
                  {user?.role}
                  {autoSignedIn && " · auto"}
                </div>
              </div>
            </div>
          </div>
        </header>
        <main className="flex-1 px-4 py-6 md:px-8">
          <Outlet />
        </main>
        <footer className="px-8 pb-4 text-center text-[11px] text-slate-400">
          DiffMIA estimates behavioral contamination signals — not confirmed training-data provenance.
        </footer>
      </div>
    </div>
  );
}
