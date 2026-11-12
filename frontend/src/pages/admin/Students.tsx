import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Alert, Badge, Button, Card, Empty, Field, Input, Loading, Modal, PageHeader, Select, StatusBadge, Table, Td } from "../../components/ui";
import { api, errorText, qs } from "../../lib/api";
import { useApi } from "../../lib/hooks";

export type Section = { id: number; name: string; department: string; semester: number; students?: number };
export type Course = { id: number; code: string; name: string; department: string; faculty_id: number | null; faculty: string | null };
export type Student = {
  id: number;
  roll_number: string;
  name: string;
  department: string;
  semester: number;
  section_id: number | null;
  section: string | null;
  face_status: string;
  is_synthetic: boolean;
  is_active: boolean;
  username: string | null;
  course_ids: number[];
  courses: string[];
  initial_password?: string;
};

export function CredentialNotice({ roll, password, onClose }: { roll: string; password: string; onClose: () => void }) {
  return (
    <Modal open title="Student login created" onClose={onClose} footer={<Button onClick={onClose}>Done</Button>}>
      <p className="text-sm text-slate-600">Give these details to the student privately. The password is shown only once and must be changed at first sign-in.</p>
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 rounded-lg bg-slate-50 p-4 text-sm">
        <dt className="text-slate-500">Username</dt>
        <dd className="tabular font-semibold">{roll}</dd>
        <dt className="text-slate-500">Temporary password</dt>
        <dd className="tabular font-semibold select-all">{password}</dd>
      </dl>
    </Modal>
  );
}

export function StudentForm({ initial, sections, courses, onSaved, onCancel }: { initial?: Student; sections: Section[]; courses: Course[]; onSaved: (s: Student) => void; onCancel: () => void }) {
  const [f, setF] = useState({
    roll_number: initial?.roll_number ?? "",
    name: initial?.name ?? "",
    department: initial?.department ?? "",
    semester: initial?.semester ?? 1,
    section_id: initial?.section_id ?? (sections[0]?.id || null),
    course_ids: initial?.course_ids ?? [],
    is_active: initial?.is_active ?? true,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = { ...f, section_id: f.section_id || null };
      const s = initial ? await api.put<Student>(`/api/admin/students/${initial.id}`, body) : await api.post<Student>("/api/admin/students", body);
      onSaved(s);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      {error && <Alert>{error}</Alert>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Roll number">
          {(id) => <Input id={id} value={f.roll_number} disabled={!!initial} required onChange={(e) => setF({ ...f, roll_number: e.target.value })} />}
        </Field>
        <Field label="Full name">{(id) => <Input id={id} value={f.name} required onChange={(e) => setF({ ...f, name: e.target.value })} />}</Field>
        <Field label="Department">{(id) => <Input id={id} value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} />}</Field>
        <Field label="Semester">
          {(id) => <Input id={id} type="number" min={1} max={12} value={f.semester} onChange={(e) => setF({ ...f, semester: Number(e.target.value) })} />}
        </Field>
        <Field label="Section">
          {(id) => (
            <Select id={id} value={f.section_id ?? ""} onChange={(e) => setF({ ...f, section_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">— none —</option>
              {sections.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {initial && (
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
            <input type="checkbox" className="h-4 w-4 accent-navy-700" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />
            Login enabled
          </label>
        )}
      </div>
      {courses.length > 0 && (
        <fieldset>
          <legend className="text-sm font-medium text-slate-700">Enrolled courses</legend>
          <div className="mt-1 grid gap-1 sm:grid-cols-2">
            {courses.map((c) => (
              <label key={c.id} className="flex items-center gap-2 text-sm text-slate-700">
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-navy-700"
                  checked={f.course_ids.includes(c.id)}
                  onChange={(e) => setF({ ...f, course_ids: e.target.checked ? [...f.course_ids, c.id] : f.course_ids.filter((x) => x !== c.id) })}
                />
                {c.code} <span className="text-slate-500">{c.name}</span>
              </label>
            ))}
          </div>
        </fieldset>
      )}
      <div className="flex justify-end gap-2 pt-2">
        <Button variant="secondary" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" busy={busy}>
          {initial ? "Save changes" : "Create student"}
        </Button>
      </div>
    </form>
  );
}

export default function Students() {
  const [q, setQ] = useState("");
  const [section, setSection] = useState("");
  const { data, loading, error, reload } = useApi<Student[]>(`/api/admin/students${qs({ q, section_id: section })}`);
  const sections = useApi<Section[]>("/api/admin/sections").data ?? [];
  const courses = useApi<Course[]>("/api/admin/courses").data ?? [];
  const [creating, setCreating] = useState(false);
  const [creds, setCreds] = useState<{ roll: string; password: string } | null>(null);

  return (
    <>
      <PageHeader title="Students" subtitle="Accounts, sections, enrolled courses and face enrollment status" actions={<Button onClick={() => setCreating(true)}>Add student</Button>} />
      <Card>
        <div className="mb-4 flex flex-col gap-2 sm:flex-row">
          <Input placeholder="Search name or roll number" value={q} onChange={(e) => setQ(e.target.value)} className="sm:max-w-xs" aria-label="Search" />
          <Select value={section} onChange={(e) => setSection(e.target.value)} className="sm:max-w-[12rem]" aria-label="Section filter">
            <option value="">All sections</option>
            {sections.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </Select>
        </div>
        {error && <Alert>{error}</Alert>}
        {loading && !data ? (
          <Loading />
        ) : !data?.length ? (
          <Empty>No students yet. Add one, or create sections first under Courses &amp; sections.</Empty>
        ) : (
          <Table head={["Roll no.", "Name", "Section", "Courses", "Face", ""]}>
            {data.map((s) => (
              <tr key={s.id} className="hover:bg-slate-50">
                <Td className="tabular font-medium whitespace-nowrap">{s.roll_number}</Td>
                <Td>
                  {s.name} {s.is_synthetic && <Badge tone="amber">synthetic</Badge>} {!s.is_active && <Badge tone="red">disabled</Badge>}
                </Td>
                <Td className="whitespace-nowrap">{s.section ?? "—"}</Td>
                <Td className="text-slate-500">{s.courses.join(", ") || "—"}</Td>
                <Td>
                  <StatusBadge status={s.face_status} />
                </Td>
                <Td className="text-right">
                  <Link to={`/admin/students/${s.id}`} className="text-sm font-medium text-navy-700 hover:underline">
                    Manage
                  </Link>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      <Modal open={creating} onClose={() => setCreating(false)} title="Add student" wide>
        <StudentForm
          sections={sections}
          courses={courses}
          onCancel={() => setCreating(false)}
          onSaved={(s) => {
            setCreating(false);
            if (s.initial_password) setCreds({ roll: s.roll_number, password: s.initial_password });
            void reload();
          }}
        />
      </Modal>
      {creds && <CredentialNotice roll={creds.roll} password={creds.password} onClose={() => setCreds(null)} />}
    </>
  );
}
