import { useState, type FormEvent } from "react";
import { Alert, Button, Card, Empty, Field, Input, Loading, Modal, PageHeader, Select, Table, Tabs, Td } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { useApi } from "../../lib/hooks";
import type { Course, Section } from "./Students";

type Faculty = { id: number; name: string; email: string | null; department: string };
type Kind = "courses" | "sections" | "faculty";

function useSave(onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, run };
}

export default function Courses() {
  const [tab, setTab] = useState<Kind>("courses");
  const courses = useApi<Course[]>("/api/admin/courses");
  const sections = useApi<Section[]>("/api/admin/sections");
  const faculty = useApi<Faculty[]>("/api/admin/faculty");
  const [edit, setEdit] = useState<{ kind: Kind; item?: Course | Section | Faculty } | null>(null);
  const [enrollFor, setEnrollFor] = useState<Section | null>(null);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const reloadAll = () => {
    void courses.reload();
    void sections.reload();
    void faculty.reload();
  };
  const remove = async (url: string) => {
    if (!window.confirm("Delete permanently? Linked timetable slots and sessions are removed too.")) return;
    try {
      await api.del(url);
      reloadAll();
    } catch (e) {
      setMsg({ tone: "red", text: errorText(e) });
    }
  };
  return (
    <>
      <PageHeader title="Courses & sections" actions={<Button onClick={() => setEdit({ kind: tab })}>Add {tab === "faculty" ? "faculty" : tab.slice(0, -1)}</Button>} />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { value: "courses", label: "Courses" },
          { value: "sections", label: "Sections" },
          { value: "faculty", label: "Faculty" },
        ]}
      />
      {msg && (
        <div className="mb-4">
          <Alert tone={msg.tone}>{msg.text}</Alert>
        </div>
      )}
      <Card>
        {tab === "courses" &&
          (courses.loading && !courses.data ? (
            <Loading />
          ) : !courses.data?.length ? (
            <Empty>No courses yet.</Empty>
          ) : (
            <Table head={["Code", "Name", "Department", "Faculty", ""]}>
              {courses.data.map((c) => (
                <tr key={c.id}>
                  <Td className="font-medium">{c.code}</Td>
                  <Td>{c.name}</Td>
                  <Td>{c.department || "—"}</Td>
                  <Td>{c.faculty ?? "—"}</Td>
                  <Td className="text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" onClick={() => setEdit({ kind: "courses", item: c })}>
                      Edit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => remove(`/api/admin/courses/${c.id}`)}>
                      Delete
                    </Button>
                  </Td>
                </tr>
              ))}
            </Table>
          ))}
        {tab === "sections" &&
          (sections.loading && !sections.data ? (
            <Loading />
          ) : !sections.data?.length ? (
            <Empty>No sections yet.</Empty>
          ) : (
            <Table head={["Section", "Department", "Semester", "Students", ""]}>
              {sections.data.map((s) => (
                <tr key={s.id}>
                  <Td className="font-medium">{s.name}</Td>
                  <Td>{s.department || "—"}</Td>
                  <Td className="tabular">{s.semester}</Td>
                  <Td className="tabular">{s.students ?? 0}</Td>
                  <Td className="text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" onClick={() => setEnrollFor(s)}>
                      Enroll in course
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEdit({ kind: "sections", item: s })}>
                      Edit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => remove(`/api/admin/sections/${s.id}`)}>
                      Delete
                    </Button>
                  </Td>
                </tr>
              ))}
            </Table>
          ))}
        {tab === "faculty" &&
          (faculty.loading && !faculty.data ? (
            <Loading />
          ) : !faculty.data?.length ? (
            <Empty>No faculty yet.</Empty>
          ) : (
            <Table head={["Name", "Email", "Department", ""]}>
              {faculty.data.map((f) => (
                <tr key={f.id}>
                  <Td className="font-medium">{f.name}</Td>
                  <Td>{f.email ?? "—"}</Td>
                  <Td>{f.department || "—"}</Td>
                  <Td className="text-right whitespace-nowrap">
                    <Button size="sm" variant="ghost" onClick={() => setEdit({ kind: "faculty", item: f })}>
                      Edit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => remove(`/api/admin/faculty/${f.id}`)}>
                      Delete
                    </Button>
                  </Td>
                </tr>
              ))}
            </Table>
          ))}
      </Card>
      {edit && (
        <EditModal
          kind={edit.kind}
          item={edit.item}
          faculty={faculty.data ?? []}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            reloadAll();
          }}
        />
      )}
      {enrollFor && (
        <EnrollSectionModal
          section={enrollFor}
          courses={courses.data ?? []}
          onClose={() => setEnrollFor(null)}
          onDone={(n) => {
            setEnrollFor(null);
            setMsg({ tone: "green", text: `${n} students of ${enrollFor.name} were enrolled in the course.` });
          }}
        />
      )}
    </>
  );
}

function EditModal({ kind, item, faculty, onClose, onSaved }: { kind: Kind; item?: Course | Section | Faculty; faculty: Faculty[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<Record<string, string>>(() => {
    const i = (item ?? {}) as Record<string, unknown>;
    return Object.fromEntries(["code", "name", "department", "semester", "email", "faculty_id"].map((k) => [k, i[k] == null ? (k === "semester" ? "1" : "") : String(i[k])]));
  });
  const save = useSave(onSaved);
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body =
      kind === "courses"
        ? { code: f.code, name: f.name, department: f.department, faculty_id: f.faculty_id ? Number(f.faculty_id) : null }
        : kind === "sections"
          ? { name: f.name, department: f.department, semester: Number(f.semester) }
          : { name: f.name, email: f.email || null, department: f.department };
    const url = `/api/admin/${kind}${item ? `/${item.id}` : ""}`;
    void save.run(() => (item ? api.put(url, body) : api.post(url, body)));
  };
  const title = `${item ? "Edit" : "Add"} ${kind === "faculty" ? "faculty member" : kind.slice(0, -1)}`;
  return (
    <Modal open title={title} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        {save.error && <Alert>{save.error}</Alert>}
        {kind === "courses" && <Field label="Course code">{(id) => <Input id={id} value={f.code} onChange={set("code")} required placeholder="e.g. DL3101" />}</Field>}
        <Field label={kind === "sections" ? "Section name" : "Name"}>{(id) => <Input id={id} value={f.name} onChange={set("name")} required placeholder={kind === "sections" ? "e.g. CSE-5A" : ""} />}</Field>
        <Field label="Department">{(id) => <Input id={id} value={f.department} onChange={set("department")} />}</Field>
        {kind === "sections" && <Field label="Semester">{(id) => <Input id={id} type="number" min={1} max={12} value={f.semester} onChange={set("semester")} />}</Field>}
        {kind === "faculty" && <Field label="Email (optional)">{(id) => <Input id={id} type="email" value={f.email} onChange={set("email")} />}</Field>}
        {kind === "courses" && (
          <Field label="Faculty">
            {(id) => (
              <Select id={id} value={f.faculty_id} onChange={set("faculty_id")}>
                <option value="">— none —</option>
                {faculty.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" busy={save.busy}>
            Save
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function EnrollSectionModal({ section, courses, onClose, onDone }: { section: Section; courses: Course[]; onClose: () => void; onDone: (n: number) => void }) {
  const [cid, setCid] = useState(courses[0]?.id ?? 0);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal
      open
      title={`Enroll ${section.name} in a course`}
      onClose={onClose}
      footer={
        <Button
          onClick={async () => {
            try {
              const r = await api.post<{ added: number }>(`/api/admin/sections/${section.id}/enroll-course/${cid}`);
              onDone(r.added);
            } catch (e) {
              setError(errorText(e));
            }
          }}
          disabled={!cid}
        >
          Enroll all students
        </Button>
      }
    >
      {error && <Alert>{error}</Alert>}
      <Field label="Course">
        {(id) => (
          <Select id={id} value={cid} onChange={(e) => setCid(Number(e.target.value))}>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.code} {c.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <p className="mt-2 text-xs text-slate-500">Course enrollment matters when Settings → eligibility is "course enrollment".</p>
    </Modal>
  );
}
