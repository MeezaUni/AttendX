import { useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Input,
  PageHeader,
  Select,
  StatusBadge,
} from "../components/ui";
import { api, errorText } from "../lib/api";
import { useApi } from "../lib/hooks";
import type { Batch } from "./V2Student";

type Option = { id: number; name: string; code?: string };
type Status = {
  faculty: { user_id: number; name: string }[];
  semesters: { id: number; name: string; end_date: string }[];
  assignments: {
    id: number;
    faculty_user_id: number;
    section_id: number;
    course_id: number | null;
    kind: string;
    revoked: boolean;
  }[];
  mail: { id: number; status: string; attempts: number; last_error: string }[];
};
export default function V2Admin() {
  const sections = useApi<Option[]>("/api/admin/sections");
  const courses = useApi<Option[]>("/api/admin/courses");
  const students = useApi<
    (Option & { roll_number: string; section: string })[]
  >("/api/admin/students");
  const status = useApi<Status>("/api/v2/admin/status", 15000);
  const enrollments = useApi<Batch[]>("/api/v2/admin/enrollments", 15000);
  const attendance = useApi<
    {
      session_id: string;
      date: string;
      course: string;
      section: string;
      revision: number;
      headcount: number;
      roster: {
        student_id: number;
        roll_number: string;
        name: string;
        status: string;
      }[];
    }[]
  >("/api/v2/admin/attendance", 15000);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const action = async (path: string, body?: unknown) => {
    setFailure("");
    setMessage("");
    try {
      await api.post(path, body);
      setMessage("Saved successfully.");
      await Promise.all([
        status.reload(),
        students.reload(),
        enrollments.reload(),
      ]);
      return true;
    } catch (e) {
      setFailure(errorText(e));
      return false;
    }
  };
  const form =
    (path: string, convert?: (d: Record<string, string>) => unknown) =>
    async (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const target = e.currentTarget;
      const d = Object.fromEntries(new FormData(target)) as Record<
        string,
        string
      >;
      if (await action(path, convert ? convert(d) : d)) target.reset();
    };
  const select = (name: string, list: Option[] | null, required = true) => (
    <label className="block text-sm">
      {name.replaceAll("_", " ")}
      <Select name={name} required={required} defaultValue="">
        <option value="">Select…</option>
        {list?.map((o) => (
          <option key={o.id} value={o.id}>
            {o.code ?? o.name}
          </option>
        ))}
      </Select>
    </label>
  );
  return (
    <div className="space-y-6">
      <PageHeader
        title="AttendX V2 administration"
        subtitle="Central identity, academic authorization and approved attendance"
        actions={
          <Link
            className="text-sm text-navy-700 underline"
            to="/admin/timetable"
          >
            Manage timetable
          </Link>
        }
      />
      {(failure || status.error || enrollments.error) && (
        <Alert>{failure || status.error || enrollments.error}</Alert>
      )}
      {message && <Alert tone="green">{message}</Alert>}
      <div className="grid items-start gap-5 xl:grid-cols-2">
        <Card title="Invite a student">
          <form
            className="space-y-3"
            onSubmit={form("/api/v2/admin/students", (d) => ({
              ...d,
              section_id: Number(d.section_id),
              semester: Number(d.semester),
            }))}
          >
            <Text name="roll_number" label="University roll number" />
            <Text name="name" label="Full name" />
            <Text name="email" label="University email" type="email" />
            <Text name="department" label="Department" />
            <Text name="semester" label="Semester number" type="number" />
            {select("section_id", sections.data)}
            <Button type="submit">
              Create student and send activation invitation
            </Button>
            <p className="text-xs text-slate-500">
              Students choose their own passwords and capture their own samples.
              Email delivery requires configured SMTP.
            </p>
          </form>
        </Card>
        <Card title="Configure semester and renewal">
          <form
            className="space-y-3"
            onSubmit={form("/api/v2/admin/semesters", (d) => ({
              ...d,
              section_ids: [Number(d.section_id)],
              reminder_days: d.reminder_days.split(",").map(Number),
            }))}
          >
            <Text name="name" label="Semester name" />
            <Text name="academic_year" label="Academic year" />
            <Text name="start_date" label="First day" type="date" />
            <Text
              name="end_date"
              label="Last day / template expiry"
              type="date"
            />
            <Text
              name="renewal_deadline"
              label="Renewal deadline"
              type="date"
            />
            <Text
              name="reminder_days"
              label="Reminder days before expiry, comma separated"
              defaultValue="30,7,1,0"
            />
            {select("section_id", sections.data)}
            <Button type="submit">Save semester policy for section</Button>
          </form>
          <div className="mt-3 text-sm">
            {status.data?.semesters.map((s) => (
              <p key={s.id}>
                {s.name} · expires {s.end_date}
              </p>
            ))}
          </div>
        </Card>
        <Card title="Create a faculty account">
          <form className="space-y-3" onSubmit={form("/api/v2/admin/faculty")}>
            <Text name="name" label="Faculty name" />
            <Text name="username" label="Faculty username" />
            <Text name="email" label="University email" type="email" />
            <Text
              name="password"
              label="Faculty initial password"
              type="password"
            />
            <Text name="department" label="Department" />
            <Button type="submit">Create faculty account</Button>
          </form>
        </Card>
        <Card title="Teaching and Class Coordinator assignments">
          <form
            className="space-y-3"
            onSubmit={form("/api/v2/admin/assignments", (d) => ({
              ...d,
              faculty_user_id: Number(d.faculty_user_id),
              section_id: Number(d.section_id),
              course_id: d.kind === "teaching" ? Number(d.course_id) : null,
            }))}
          >
            {select(
              "faculty_user_id",
              status.data?.faculty.map((f) => ({
                id: f.user_id,
                name: f.name,
              })) ?? null,
            )}
            {select("section_id", sections.data)}
            <label className="block text-sm">
              Permission
              <Select name="kind">
                <option value="teaching">
                  Teach selected course and section
                </option>
                <option value="coordinator">CC for selected section</option>
              </Select>
            </label>
            {select("course_id", courses.data, false)}
            <Text name="reason" label="Authorization reason" />
            <Button type="submit">Assign scoped permission</Button>
          </form>
          <div className="mt-4 space-y-2">
            {status.data?.assignments
              .filter((a) => !a.revoked)
              .map((a) => (
                <div
                  key={a.id}
                  className="flex items-center justify-between gap-2 text-sm"
                >
                  <span>
                    {
                      status.data?.faculty.find(
                        (f) => f.user_id === a.faculty_user_id,
                      )?.name
                    }{" "}
                    · {sections.data?.find((s) => s.id === a.section_id)?.name}{" "}
                    · {a.kind}
                  </span>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={async () => {
                      try {
                        await api.del(`/api/v2/admin/assignments/${a.id}`);
                        await status.reload();
                      } catch (e) {
                        setFailure(errorText(e));
                      }
                    }}
                  >
                    Revoke
                  </Button>
                </div>
              ))}
          </div>
        </Card>
      </div>
      <Card title="Biometric enrollment approvals">
        <p className="mb-4 text-sm text-slate-500">
          Only enrollments verified in person by the assigned CC can receive
          final approval.
        </p>
        <div className="space-y-3">
          {enrollments.data?.map((b) => (
            <div
              key={b.id}
              className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3"
            >
              <div>
                <p className="text-sm font-medium">
                  {b.roll_number} · {b.name} · version {b.version}
                </p>
                <p className="text-xs text-slate-500">
                  {b.samples.length} samples · expires {b.expires_on}
                </p>
              </div>
              <StatusBadge status={b.status} />
              {b.status === "PENDING_ADMIN_APPROVAL" && (
                <Button
                  onClick={() =>
                    void action(`/api/v2/admin/enrollments/${b.id}/approve`)
                  }
                >
                  Give final enrollment approval
                </Button>
              )}
            </div>
          ))}
          {!enrollments.data?.length && <p>No enrollment requests yet.</p>}
        </div>
      </Card>
      <Card title="Student invitations">
        <div className="max-h-64 space-y-2 overflow-auto">
          {students.data?.map((s) => (
            <div key={s.id} className="flex justify-between gap-3 text-sm">
              <span>
                {s.roll_number} · {s.name} · {s.section}
              </span>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  void action(`/api/v2/admin/students/${s.id}/invite`)
                }
              >
                Reissue pending invitation
              </Button>
            </div>
          ))}
        </div>
      </Card>
      <Card
        title="Approved attendance"
        actions={
          <a
            className="text-sm text-navy-700 underline"
            href="/api/v2/admin/attendance.csv"
          >
            Export approved attendance CSV
          </a>
        }
      >
        <p className="mb-3 text-sm text-slate-500">
          Only explicit faculty approval creates these records. A missing
          submission has no inferred attendance status.
        </p>
        {attendance.data?.map((s) => (
          <details key={s.session_id} className="border-b py-3">
            <summary>
              {s.date} · {s.course} · {s.section} · headcount {s.headcount} ·
              revision {s.revision}
            </summary>
            <div className="mt-3 space-y-1">
              {s.roster.map((r) => (
                <p key={r.student_id} className="flex justify-between text-sm">
                  <span>
                    {r.roll_number} · {r.name}
                  </span>
                  <StatusBadge status={r.status} />
                </p>
              ))}
            </div>
          </details>
        ))}
        {!attendance.data?.length && (
          <p>No approved attendance synchronized yet.</p>
        )}
      </Card>
      <Card
        title="Email delivery and privacy maintenance"
        actions={
          <Button
            variant="secondary"
            onClick={() => void action("/api/v2/admin/maintenance")}
          >
            Run expiry, reminders and delivery retry
          </Button>
        }
      >
        <div className="max-h-48 overflow-auto text-sm">
          {status.data?.mail.map((m) => (
            <p key={m.id}>
              Message {m.id}: {m.status} · attempts {m.attempts} {m.last_error}
            </p>
          ))}
          {!status.data?.mail.length && <p>No email queued.</p>}
        </div>
      </Card>
    </div>
  );
}
function Text({
  name,
  label,
  type = "text",
  defaultValue,
}: {
  name: string;
  label: ReactNode;
  type?: string;
  defaultValue?: string;
}) {
  return (
    <label className="block space-y-1 text-sm">
      <span>{label}</span>
      <Input
        name={name}
        type={type}
        required
        defaultValue={defaultValue}
        autoComplete={type === "password" ? "new-password" : "off"}
      />
    </label>
  );
}
