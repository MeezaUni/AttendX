import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { FaceCapture } from "../../components/FaceCapture";
import { Alert, Button, Card, Empty, Loading, Modal, PageHeader, Pct, StatusBadge, Table, Tabs, Td } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { fmtTime, useApi } from "../../lib/hooks";
import type { EnrollResult } from "../student/Enroll";
import { CredentialNotice, StudentForm, type Course, type Section, type Student } from "./Students";

type Template = { id: number; status: string; source: string; n_frames: number; mean_quality: number; consistency: number; created_at: string; approved_at: string | null };
type Detail = Student & { templates: Template[] };
type Summary = { student_id: number; percentage: number | null; held: number; attended: number; courses: { course_code: string; held: number; attended: number; percentage: number | null }[] };
type Attempt = { id: number; created_at: string; decision: string; reason: string; match_score: number | null; quality: number | null; liveness_passed: boolean | null; processing_ms: number };

export default function StudentDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data, loading, error, reload } = useApi<Detail>(`/api/admin/students/${id}`);
  const sections = useApi<Section[]>("/api/admin/sections").data ?? [];
  const courses = useApi<Course[]>("/api/admin/courses").data ?? [];
  const summary = useApi<Summary[]>(data ? `/api/admin/reports/students?section_id=${data.section_id ?? ""}` : null).data?.find((r) => r.student_id === Number(id));
  const attempts = useApi<Attempt[]>(`/api/admin/attempts?student_id=${id}&limit=20`).data ?? [];
  const [editing, setEditing] = useState(false);
  const [mode, setMode] = useState<"live" | "upload">("live");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [creds, setCreds] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<null | "delete-face" | "delete-student">(null);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ tone: "green", text: ok });
      await reload();
    } catch (e) {
      setMsg({ tone: "red", text: errorText(e) });
    } finally {
      setBusy(false);
    }
  };

  const enroll = async (files: Blob[], source: "admin_live" | "admin_upload") => {
    setBusy(true);
    setMsg(null);
    try {
      const fd = new FormData();
      files.forEach((f, i) => fd.append("images", f, `img${i}.jpg`));
      fd.append("source", source);
      fd.append("consent", String(consent));
      const r = await api.post<EnrollResult>(`/api/admin/students/${id}/face`, fd);
      if (r.ok) setMsg({ tone: "green", text: `Face enrolled and approved (${r.frames_used} images used).` });
      else {
        const problems = [...new Set(r.images.flatMap((i) => i.problems))];
        setMsg({ tone: "red", text: `${r.error}${problems.length ? `\nImage problems: ${problems.join("; ")}` : ""}` });
      }
      await reload();
    } catch (e) {
      setMsg({ tone: "red", text: errorText(e) });
    } finally {
      setBusy(false);
    }
  };

  if (loading && !data) return <Loading />;
  if (error || !data) return <Alert>{error ?? "Not found"}</Alert>;

  return (
    <>
      <Link to="/admin/students" className="text-sm font-medium text-navy-700">
        ← Students
      </Link>
      <PageHeader
        title={data.name}
        subtitle={
          <>
            <span className="tabular">{data.roll_number}</span> · {data.section ?? "no section"} · semester {data.semester}
            {data.department && ` · ${data.department}`}
          </>
        }
        actions={
          <>
            <Button variant="secondary" onClick={() => setEditing(true)}>
              Edit
            </Button>
            <Button variant="secondary" busy={busy} onClick={() => act(async () => setCreds((await api.post<{ initial_password: string }>(`/api/admin/students/${id}/reset-password`)).initial_password), "Password reset.")}>
              Reset password
            </Button>
          </>
        }
      />
      {msg && (
        <div className="mb-4">
          <Alert tone={msg.tone}>{msg.text}</Alert>
        </div>
      )}
      <div className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-5 lg:col-span-3">
          <Card title="Face enrollment" actions={<StatusBadge status={data.face_status} />}>
            <div className="space-y-4">
              <label className="flex items-start gap-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-navy-700" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>The student is present and has consented to biometric enrollment. Images are converted to an encrypted template and not stored.</span>
              </label>
              <Tabs
                value={mode}
                onChange={setMode}
                items={[
                  { value: "live", label: "Live capture" },
                  { value: "upload", label: "Upload photos" },
                ]}
              />
              {!consent ? (
                <p className="text-sm text-slate-500">Confirm consent to continue.</p>
              ) : mode === "live" ? (
                <FaceCapture busy={busy} onCaptured={(f) => enroll(f, "admin_live")} />
              ) : (
                <div className="space-y-2">
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    multiple
                    disabled={busy}
                    aria-label="Enrollment photos"
                    className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-navy-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-navy-800"
                    onChange={(e) => {
                      const files = Array.from(e.target.files ?? []);
                      if (files.length) void enroll(files, "admin_upload");
                      e.target.value = "";
                    }}
                  />
                  <p className="text-xs text-slate-500">Select 3–8 recent, well-lit photos of the student only (authorised source). Attendance itself never accepts uploads.</p>
                </div>
              )}
              <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-4">
                <Button variant="secondary" busy={busy} onClick={() => act(() => api.post(`/api/admin/students/${id}/enrollment/open`), "Self-enrollment opened: the student can now enroll from their phone.")}>
                  Allow self-enrollment
                </Button>
                <Button variant="danger" disabled={!data.templates.length} onClick={() => setConfirm("delete-face")}>
                  Delete all face data
                </Button>
              </div>
            </div>
          </Card>
          <Card title="Face templates">
            {data.templates.length === 0 ? (
              <Empty>No templates.</Empty>
            ) : (
              <Table head={["Created", "Source", "Images", "Consistency", "Status", ""]} dense>
                {data.templates.map((t) => (
                  <tr key={t.id}>
                    <Td className="whitespace-nowrap">{fmtTime(t.created_at, true)}</Td>
                    <Td>{t.source.replace("_", " ")}</Td>
                    <Td className="tabular">{t.n_frames}</Td>
                    <Td className="tabular">{t.consistency.toFixed(2)}</Td>
                    <Td>
                      <StatusBadge status={t.status} />
                    </Td>
                    <Td className="text-right whitespace-nowrap">
                      {t.status === "pending" && (
                        <Button size="sm" busy={busy} onClick={() => act(() => api.post(`/api/admin/templates/${t.id}/approve`), "Template approved.")}>
                          Approve
                        </Button>
                      )}{" "}
                      {(t.status === "pending" || t.status === "approved") && (
                        <Button size="sm" variant="danger" busy={busy} onClick={() => act(() => api.post(`/api/admin/templates/${t.id}/revoke`), "Template revoked.")}>
                          Revoke
                        </Button>
                      )}
                    </Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </div>
        <div className="space-y-5 lg:col-span-2">
          <Card title="Attendance">
            {summary ? (
              <div className="space-y-2 text-sm">
                <p className="flex justify-between">
                  <span className="text-slate-600">Overall</span>
                  <span>
                    <span className="tabular mr-2 text-slate-500">
                      {summary.attended}/{summary.held}
                    </span>
                    <Pct value={summary.percentage} />
                  </span>
                </p>
                {summary.courses.map((c) => (
                  <p key={c.course_code} className="flex justify-between pl-3 text-slate-600">
                    <span>{c.course_code}</span>
                    <span>
                      <span className="tabular mr-2 text-slate-400">
                        {c.attended}/{c.held}
                      </span>
                      <Pct value={c.percentage} />
                    </span>
                  </p>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No classes held yet.</p>
            )}
          </Card>
          <Card title="Recent verification attempts">
            {attempts.length === 0 ? (
              <Empty>None yet.</Empty>
            ) : (
              <ul className="divide-y divide-slate-100 text-sm">
                {attempts.map((a) => (
                  <li key={a.id} className="py-2">
                    <div className="flex items-center justify-between">
                      <StatusBadge status={a.decision} />
                      <span className="text-xs text-slate-400">{fmtTime(a.created_at, true)}</span>
                    </div>
                    <p className="mt-1 text-slate-600">{a.reason}</p>
                    <p className="tabular text-xs text-slate-400">
                      score {a.match_score?.toFixed(3) ?? "—"} · quality {a.quality?.toFixed(1) ?? "—"} · liveness {a.liveness_passed === null ? "—" : a.liveness_passed ? "passed" : "failed"} · {a.processing_ms} ms
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Button variant="danger" className="w-full" onClick={() => setConfirm("delete-student")}>
            Delete student
          </Button>
        </div>
      </div>
      <Modal open={editing} onClose={() => setEditing(false)} title="Edit student" wide>
        <StudentForm
          initial={data}
          sections={sections}
          courses={courses}
          onCancel={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            void reload();
          }}
        />
      </Modal>
      <Modal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm === "delete-face" ? "Delete face data?" : "Delete student?"}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              busy={busy}
              onClick={async () => {
                const what = confirm;
                setConfirm(null);
                if (what === "delete-face") await act(() => api.del(`/api/admin/students/${id}/face`), "All face templates were permanently deleted.");
                else {
                  await api.del(`/api/admin/students/${id}`);
                  nav("/admin/students");
                }
              }}
            >
              Delete permanently
            </Button>
          </>
        }
      >
        <p className="text-sm text-slate-600">
          {confirm === "delete-face"
            ? "Every face template of this student is permanently erased. Past attendance records are kept. The student must enroll again to use face verification."
            : "The student, their login and all their attendance records and face data are permanently deleted."}
        </p>
      </Modal>
      {creds && <CredentialNotice roll={data.roll_number} password={creds} onClose={() => setCreds(null)} />}
    </>
  );
}
