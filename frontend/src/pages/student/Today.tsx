import { Link } from "react-router-dom";
import { Alert, Badge, Button, Empty, Loading, StatusBadge } from "../../components/ui";
import { fmtDate, fmtTime, useApi } from "../../lib/hooks";

export type StudentSession = {
  id: number;
  period_number: number;
  course_code: string;
  course_name: string;
  faculty: string | null;
  start: string;
  end: string;
  open: string;
  close: string;
  status: "open" | "upcoming" | "closed" | "cancelled";
  record: { status: string; method: string; verified_at: string | null } | null;
  attempts_left: number;
  note: string;
};

type TodayData = {
  date: string;
  weekday: string;
  holiday: string | null;
  server_time: string;
  face_ready: boolean;
  face_status: string;
  sessions: StudentSession[];
};

export default function Today() {
  const { data, error, loading } = useApi<TodayData>("/api/student/today", 20000);
  if (loading && !data) return <Loading />;
  if (error && !data) return <Alert>{error}</Alert>;
  if (!data) return null;
  const openNow = data.sessions.filter((s) => s.status === "open" && !s.record);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Today's classes</h1>
        <p className="text-sm text-slate-500">
          {fmtDate(data.date)} · server time {fmtTime(data.server_time)}
        </p>
      </div>
      {!data.face_ready && (
        <Alert tone="amber" title="Face not enrolled yet">
          {data.face_status === "enrollment_open" ? (
            <>
              Enrollment is open for you. <Link className="font-semibold underline" to="/enroll">Enroll your face now</Link>.
            </>
          ) : data.face_status === "pending" ? (
            "Your face enrollment is waiting for administrator approval."
          ) : (
            "Ask your administrator to enroll your face before marking attendance."
          )}
        </Alert>
      )}
      {data.holiday && <Alert tone="blue">Holiday: {data.holiday}. No attendance today.</Alert>}
      {openNow.length > 0 && data.face_ready && (
        <Alert tone="green" title="Attendance is open">
          {openNow.map((s) => s.course_code).join(", ")}: mark it now.
        </Alert>
      )}
      {data.sessions.length === 0 && !data.holiday && <Empty>No classes scheduled for you today.</Empty>}
      <ul className="space-y-3">
        {data.sessions.map((s) => (
          <li key={s.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-medium text-slate-500">
                  Period {s.period_number} · {s.start}–{s.end}
                </p>
                <p className="mt-0.5 font-semibold text-slate-900">
                  {s.course_code} <span className="font-normal text-slate-600">{s.course_name}</span>
                </p>
                {s.faculty && <p className="text-sm text-slate-500">{s.faculty}</p>}
              </div>
              {s.record ? <StatusBadge status={s.record.status} /> : <StatusBadge status={s.status} />}
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
              <p className="text-sm text-slate-600">
                Attendance window <span className="tabular font-medium">{s.open}–{s.close}</span>
              </p>
              {s.record ? (
                <Badge tone="green">
                  Marked {s.record.verified_at ? fmtTime(s.record.verified_at) : `(${s.record.method})`}
                </Badge>
              ) : s.status === "open" ? (
                s.attempts_left > 0 ? (
                  <Link to={`/verify/${s.id}`} state={{ session: s }}>
                    <Button disabled={!data.face_ready}>Mark attendance</Button>
                  </Link>
                ) : (
                  <span className="text-sm text-red-700">No attempts left. Ask your instructor.</span>
                )
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
