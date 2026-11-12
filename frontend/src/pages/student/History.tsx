import { Alert, Card, Empty, Loading, Pct, StatusBadge, Table, Td } from "../../components/ui";
import { fmtDate, useApi } from "../../lib/hooks";

type HistoryData = {
  summary: {
    held: number;
    attended: number;
    excused: number;
    percentage: number | null;
    courses: { course_code: string; course_name: string; held: number; attended: number; percentage: number | null }[];
  } | null;
  items: { date: string; period: number; course_code: string; start: string; status: string; method: string | null }[];
};

export default function History() {
  const { data, error, loading } = useApi<HistoryData>("/api/student/history");
  if (loading && !data) return <Loading />;
  if (error) return <Alert>{error}</Alert>;
  if (!data) return null;
  const s = data.summary;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">My attendance</h1>
      {s && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-slate-200 bg-white p-3 text-center shadow-sm">
            <p className="text-xs text-slate-500">Overall</p>
            <p className="mt-1 text-xl font-semibold">
              <Pct value={s.percentage} />
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-3 text-center shadow-sm">
            <p className="text-xs text-slate-500">Attended</p>
            <p className="tabular mt-1 text-xl font-semibold text-slate-900">{s.attended}</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-3 text-center shadow-sm">
            <p className="text-xs text-slate-500">Classes held</p>
            <p className="tabular mt-1 text-xl font-semibold text-slate-900">{s.held}</p>
          </div>
        </div>
      )}
      {s && s.courses.length > 0 && (
        <Card title="By course">
          <ul className="divide-y divide-slate-100">
            {s.courses.map((c) => (
              <li key={c.course_code} className="flex items-center justify-between py-2 text-sm">
                <span>
                  <span className="font-medium text-slate-900">{c.course_code}</span> <span className="text-slate-500">{c.course_name}</span>
                </span>
                <span className="flex items-center gap-3">
                  <span className="tabular text-slate-500">
                    {c.attended}/{c.held}
                  </span>
                  <Pct value={c.percentage} />
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title="Recent classes">
        {data.items.length === 0 ? (
          <Empty>No classes yet.</Empty>
        ) : (
          <Table head={["Date", "Course", "Status"]} dense>
            {data.items.map((it, i) => (
              <tr key={i}>
                <Td className="whitespace-nowrap text-slate-600">
                  {fmtDate(it.date)} <span className="text-slate-400">· P{it.period}</span>
                </Td>
                <Td className="font-medium">{it.course_code}</Td>
                <Td>
                  <StatusBadge status={it.status} />
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
