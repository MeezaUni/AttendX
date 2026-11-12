import { Link } from "react-router-dom";
import { Alert, Badge, Card, Empty, Loading, PageHeader, Pct, Stat, StatusBadge } from "../../components/ui";
import { fmtDate, fmtTime, useApi } from "../../lib/hooks";

type Dash = {
  date: string;
  server_time: string;
  timezone: string;
  counts: Record<string, number>;
  session_statuses: Record<string, number>;
  attempts_24h: Record<string, number>;
  week_average: number | null;
  low_attendance: { student_id: number; roll_number: string; name: string; percentage: number; held: number }[];
  recent: { roll_number: string; name: string; status: string; method: string; date: string; at: string }[];
  face_engine: { engine: string; device?: string | null; error?: string | null; detector_loaded?: boolean; embedder_loaded?: boolean };
};

export default function Dashboard() {
  const { data, error, loading } = useApi<Dash>("/api/admin/dashboard", 15000);
  if (loading && !data) return <Loading />;
  if (error && !data) return <Alert>{error}</Alert>;
  if (!data) return null;
  const c = data.counts;
  const eng = data.face_engine;
  const attempts = Object.values(data.attempts_24h).reduce((a, b) => a + b, 0);
  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={
          <>
            {fmtDate(data.date)} · server time {fmtTime(data.server_time)} ({data.timezone})
          </>
        }
      />
      {eng.error && (
        <div className="mb-4">
          <Alert title="Face engine unavailable">{eng.error}</Alert>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Classes today" value={c.sessions_today} hint={`${c.open_now} open now`} />
        <Stat label="Marked today" value={c.marked_today} hint="present or late" />
        <Stat label="Students" value={c.students} hint={`${c.enrolled_faces} faces enrolled`} />
        <Stat label="7-day average" value={<Pct value={data.week_average} />} hint="attendance rate" />
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Recent attendance"
          actions={
            <Link to="/admin/sessions" className="text-sm font-medium text-navy-700 hover:underline">
              Today's sessions →
            </Link>
          }
        >
          {data.recent.length === 0 ? (
            <Empty>No attendance recorded yet.</Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.recent.map((r, i) => (
                <li key={i} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <span className="min-w-0 truncate">
                    <span className="tabular font-medium text-slate-900">{r.roll_number}</span> <span className="text-slate-600">{r.name}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="hidden text-xs text-slate-400 sm:inline">
                      {r.method} · {fmtTime(r.at, true)}
                    </span>
                    <StatusBadge status={r.status} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="space-y-5">
          <Card title="Needs attention">
            <ul className="space-y-2 text-sm">
              <li className="flex justify-between">
                <Link to="/admin/enrollments" className="text-navy-700 hover:underline">
                  Pending face enrollments
                </Link>
                <Badge tone={c.pending_enrollments ? "amber" : "gray"}>{c.pending_enrollments}</Badge>
              </li>
              <li className="flex justify-between">
                <span className="text-slate-600">Verification attempts (24 h)</span>
                <span className="tabular">{attempts}</span>
              </li>
              {Object.entries(data.attempts_24h).map(([k, v]) => (
                <li key={k} className="flex justify-between pl-3 text-slate-500">
                  <StatusBadge status={k} />
                  <span className="tabular">{v}</span>
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Below 75 % (last 7 days)">
            {data.low_attendance.length === 0 ? (
              <p className="text-sm text-slate-500">Nobody below 75 %.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {data.low_attendance.map((s) => (
                  <li key={s.student_id} className="flex justify-between">
                    <Link to={`/admin/students/${s.student_id}`} className="truncate text-slate-700 hover:underline">
                      {s.roll_number} {s.name}
                    </Link>
                    <Pct value={s.percentage} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Face engine">
            <p className="text-sm text-slate-600">
              {eng.engine === "real" ? "SCRFD + AdaFace IR-101" : eng.engine} ·{" "}
              {eng.embedder_loaded ? `running on ${eng.device}` : eng.engine === "real" ? "loading…" : "test engine"}
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}
