import { Fragment, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, Empty, Input, Loading, PageHeader, Pct, Select, StatusBadge, Table, Tabs, Td } from "../../components/ui";
import { qs } from "../../lib/api";
import { download, fmtTime, useApi } from "../../lib/hooks";
import type { Course, Section } from "./Students";

type StudentRow = {
  student_id: number; roll_number: string; name: string; section: string | null; held: number; attended: number; excused: number;
  percentage: number | null; courses: { course_code: string; held: number; attended: number; percentage: number | null }[];
};
type CourseRow = { course_code: string; course_name: string; section: string; sessions: number; possible: number; attended: number; percentage: number | null };
type Attempt = { id: number; roll_number: string; name: string; created_at: string; decision: string; reason: string; match_score: number | null; quality: number | null; liveness_passed: boolean | null; processing_ms: number };

export default function Reports() {
  const [tab, setTab] = useState<"students" | "courses" | "attempts">("students");
  const [f, setF] = useState({ d_from: "", d_to: "", section_id: "", course_id: "" });
  const sections = useApi<Section[]>("/api/admin/sections").data ?? [];
  const courses = useApi<Course[]>("/api/admin/courses").data ?? [];
  const query = qs(f);
  const students = useApi<StudentRow[]>(tab === "students" ? `/api/admin/reports/students${query}` : null);
  const byCourse = useApi<CourseRow[]>(tab === "courses" ? `/api/admin/reports/courses${qs({ d_from: f.d_from, d_to: f.d_to, section_id: f.section_id })}` : null);
  const attempts = useApi<Attempt[]>(tab === "attempts" ? "/api/admin/attempts?limit=200" : null);
  const [open, setOpen] = useState<number | null>(null);

  return (
    <>
      <PageHeader
        title="Reports"
        subtitle="Percentages count classes whose attendance window has opened and that were not cancelled; excused classes are left out."
        actions={
          <>
            <Button variant="secondary" onClick={() => download(`/api/admin/reports/summary.csv${query}`)}>Summary CSV</Button>
            <Button onClick={() => download(`/api/admin/reports/export.csv${query}`)}>Attendance CSV</Button>
          </>
        }
      />
      <Card className="mb-5">
        <div className="grid gap-3 sm:grid-cols-4">
          <label className="text-sm text-slate-600">From<Input type="date" value={f.d_from} onChange={(e) => setF({ ...f, d_from: e.target.value })} className="mt-1" /></label>
          <label className="text-sm text-slate-600">To<Input type="date" value={f.d_to} onChange={(e) => setF({ ...f, d_to: e.target.value })} className="mt-1" /></label>
          <label className="text-sm text-slate-600">
            Section
            <Select value={f.section_id} onChange={(e) => setF({ ...f, section_id: e.target.value })} className="mt-1">
              <option value="">All</option>
              {sections.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </label>
          <label className="text-sm text-slate-600">
            Course
            <Select value={f.course_id} onChange={(e) => setF({ ...f, course_id: e.target.value })} className="mt-1">
              <option value="">All</option>
              {courses.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
            </Select>
          </label>
        </div>
      </Card>
      <Tabs value={tab} onChange={setTab} items={[{ value: "students", label: "By student" }, { value: "courses", label: "By course" }, { value: "attempts", label: "Verification attempts" }]} />
      <Card>
        {tab === "students" &&
          (students.error ? <Alert>{students.error}</Alert> : students.loading && !students.data ? <Loading /> : !students.data?.length ? <Empty>No data.</Empty> : (
            <Table head={["Roll no.", "Name", "Section", "Held", "Attended", "Excused", "Attendance"]}>
              {students.data.map((r) => (
                <Fragment key={r.student_id}>
                  <tr className="cursor-pointer hover:bg-slate-50" onClick={() => setOpen(open === r.student_id ? null : r.student_id)}>
                    <Td className="tabular font-medium">{r.roll_number}</Td>
                    <Td><Link to={`/admin/students/${r.student_id}`} className="hover:underline" onClick={(e) => e.stopPropagation()}>{r.name}</Link></Td>
                    <Td>{r.section ?? "—"}</Td>
                    <Td className="tabular">{r.held}</Td>
                    <Td className="tabular">{r.attended}</Td>
                    <Td className="tabular">{r.excused}</Td>
                    <Td><Pct value={r.percentage} /></Td>
                  </tr>
                  {open === r.student_id && r.courses.map((c) => (
                    <tr key={c.course_code} className="bg-slate-50/70 text-slate-600">
                      <Td />
                      <Td className="pl-8">{c.course_code}</Td>
                      <Td />
                      <Td className="tabular">{c.held}</Td>
                      <Td className="tabular">{c.attended}</Td>
                      <Td />
                      <Td><Pct value={c.percentage} /></Td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </Table>
          ))}
        {tab === "courses" &&
          (byCourse.loading && !byCourse.data ? <Loading /> : !byCourse.data?.length ? <Empty>No data.</Empty> : (
            <Table head={["Course", "Section", "Classes held", "Attended / possible", "Attendance"]}>
              {byCourse.data.map((r, i) => (
                <tr key={i}>
                  <Td><span className="font-medium">{r.course_code}</span> <span className="text-slate-500">{r.course_name}</span></Td>
                  <Td>{r.section}</Td>
                  <Td className="tabular">{r.sessions}</Td>
                  <Td className="tabular">{r.attended} / {r.possible}</Td>
                  <Td><Pct value={r.percentage} /></Td>
                </tr>
              ))}
            </Table>
          ))}
        {tab === "attempts" &&
          (attempts.loading && !attempts.data ? <Loading /> : !attempts.data?.length ? <Empty>No verification attempts yet.</Empty> : (
            <Table head={["Time", "Student", "Decision", "Reason", "Score", "Quality", "Liveness", "ms"]} dense>
              {attempts.data.map((a) => (
                <tr key={a.id}>
                  <Td className="whitespace-nowrap">{fmtTime(a.created_at, true)}</Td>
                  <Td className="whitespace-nowrap">{a.roll_number}</Td>
                  <Td><StatusBadge status={a.decision} /></Td>
                  <Td className="text-slate-600">{a.reason}</Td>
                  <Td className="tabular">{a.match_score?.toFixed(3) ?? "—"}</Td>
                  <Td className="tabular">{a.quality?.toFixed(1) ?? "—"}</Td>
                  <Td>{a.liveness_passed === null ? "—" : a.liveness_passed ? "passed" : "failed"}</Td>
                  <Td className="tabular">{a.processing_ms}</Td>
                </tr>
              ))}
            </Table>
          ))}
      </Card>
    </>
  );
}
