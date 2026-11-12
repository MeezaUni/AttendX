import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import { cx } from "./ui";

export function Logo({ light }: { light?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="7" fill={light ? "#fff" : "#1f3a96"} />
        <path d="M9 17.5l4.5 4.5L23 11" fill="none" stroke={light ? "#1f3a96" : "#fff"} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className={cx("text-lg font-semibold tracking-tight", light ? "text-white" : "text-navy-900")}>AttendX</span>
    </span>
  );
}

const ICONS: Record<string, ReactNode> = {
  dashboard: <path d="M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z" />,
  students: <path d="M16 11a4 4 0 1 0-8 0 4 4 0 0 0 8 0zM4 21a8 8 0 0 1 16 0" />,
  face: <path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M9 10h.01M15 10h.01M9.5 15a3.5 3.5 0 0 0 5 0" />,
  courses: <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5v14zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5" />,
  timetable: <path d="M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />,
  sessions: <path d="M12 6v6l4 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0z" />,
  reports: <path d="M3 3v18h18M7 15l4-4 3 3 5-6" />,
  settings: <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-2.82 1.17V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-2.82-1.17l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 3.6 15H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 2.82 1.17l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />,
  today: <path d="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />,
  history: <path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2" />,
};

function Icon({ name, className = "h-5 w-5" }: { name: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {ICONS[name]}
    </svg>
  );
}

const ADMIN_NAV = [
  { to: "/admin", label: "V2 administration", icon: "dashboard", end: true },
  { to: "/admin/courses", label: "Courses & sections", icon: "courses" },
  { to: "/admin/timetable", label: "Timetable", icon: "timetable" },
  { to: "/admin/settings", label: "Settings", icon: "settings" },
];

function DemoBanner() {
  const { data } = useApi<{ demo_mode: boolean }>("/api/health");
  if (!data?.demo_mode) return null;
  return (
    <div className="bg-amber-50 px-4 py-1.5 text-center text-xs font-medium text-amber-900">
      Demonstration mode: records marked "synthetic" are generated test data, not real students.
    </div>
  );
}

export function AdminLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const links = (
    <nav className="space-y-0.5">
      {ADMIN_NAV.map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={n.end}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            cx(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
              isActive ? "bg-navy-50 text-navy-800" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
            )
          }
        >
          <Icon name={n.icon} />
          {n.label}
        </NavLink>
      ))}
    </nav>
  );
  const signOut = async () => {
    await logout();
    nav("/login");
  };
  return (
    <div className="min-h-dvh lg:flex">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white px-3 py-5 lg:flex">
        <div className="px-3 pb-6">
          <Logo />
          <p className="mt-1 text-xs text-slate-500">Administration</p>
        </div>
        {links}
        <div className="mt-auto border-t border-slate-100 px-3 pt-4">
          <p className="truncate text-sm font-medium text-slate-800">{user?.display_name || user?.username}</p>
          <button onClick={signOut} className="mt-1 text-sm text-navy-700 hover:underline">
            Sign out
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white/95 px-4 py-3 backdrop-blur lg:hidden">
          <Logo />
          <button onClick={() => setOpen(!open)} className="rounded-lg p-2 text-slate-600 hover:bg-slate-100" aria-label="Menu" aria-expanded={open}>
            <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
            </svg>
          </button>
        </header>
        {open && (
          <div className="border-b border-slate-200 bg-white px-3 py-3 lg:hidden">
            {links}
            <button onClick={signOut} className="mt-2 w-full rounded-lg px-3 py-2 text-left text-sm font-medium text-navy-700 hover:bg-slate-100">
              Sign out
            </button>
          </div>
        )}
        <DemoBanner />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

const STUDENT_NAV = [
  { to: "/", label: "My enrollment", icon: "face", end: true },
];

export function StudentLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  return (
    <div className="flex min-h-dvh flex-col pb-[calc(4rem+env(safe-area-inset-bottom))] sm:pb-0">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-2xl items-center justify-between px-4 py-3">
          <Logo />
          <div className="flex items-center gap-3">
            <nav className="hidden gap-1 sm:flex">
              {STUDENT_NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  end={n.end}
                  className={({ isActive }) => cx("rounded-lg px-3 py-1.5 text-sm font-medium", isActive ? "bg-navy-50 text-navy-800" : "text-slate-600 hover:bg-slate-100")}
                >
                  {n.label}
                </NavLink>
              ))}
            </nav>
            <button
              onClick={async () => {
                await logout();
                nav("/login");
              }}
              className="text-sm font-medium text-slate-500 hover:text-slate-800"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <DemoBanner />
      <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-5">
        <p className="mb-4 text-sm text-slate-500">
          {user?.student?.name} · <span className="tabular">{user?.student?.roll_number}</span>
          {user?.student?.section && <> · {user.student.section}</>}
        </p>
        <Outlet />
      </main>
      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t border-slate-200 bg-white pb-[env(safe-area-inset-bottom)] sm:hidden">
        {STUDENT_NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => cx("flex flex-col items-center gap-0.5 py-2 text-xs font-medium", isActive ? "text-navy-700" : "text-slate-500")}
          >
            <Icon name={n.icon} className="h-6 w-6" />
            {n.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
