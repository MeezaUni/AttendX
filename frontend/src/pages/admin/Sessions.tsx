import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, Empty, Field, Input, Loading, Modal, PageHeader, Select, StatusBadge, Table, Td } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { fmtDate, fmtTime, useApi } from "../../lib/hooks";
import type { Course, Section } from "./Students";

export type AdminSession = {
  id: number; date: string; period_number: number; section: string; section_id: number; course_code: string; course_name: string;
  faculty: string | null; start: string; end: string; open: string; close: string; status: string; cancelled: boolean;
  manually_adjusted: boolean; note: string; present?: number; enrolled?: number;
};
type DayData = { date: string; weekday: string; holiday: string | null; server_time: string; sessions: AdminSession[] };

export async function windowAction(id: number, action: string, extra: Record<string, unknown> = {}) {
  return api.post<AdminSession>(`/api/admin/sessions/${id}/window`, { action, ...extra });
}

export default function Sessions() {
  const [day, setDay] = useState("");
  const { data, loading, error, reload } = useApi<DayData>(`/api/admin/sessions${day ? `?day=${day}` : ""}`, 10000);
  const [msg, setMsg] = useState<string | null>(null);
  const [adhoc, setAdhoc] = useState(false);
  const act = async (id: number, action: string, extra?: Record<string, unknown>) => {
    setMsg(null);
    try {
      await windowAction(id, action, extra);
      await reload();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  return (
    <>
      <PageHeader
        title="Attendance sessions"
        subtitle={data ? <>{fmtDate(data.date)} · server time {fmtTime(data.server_time)} · refreshes every 10 s</> : undefined}
        actions={
          <>
            <Input type="date" value={day || data?.date || ""} onChange={(e) => setDay(e.target.value)} className="w-44" aria-label="Date" />
            <Button variant="secondary" onClick={() => setAdhoc(true)}>
              Extra session
            </Button>
          </>
        }
      />
      {data?.holiday && (
        <div className="mb-4">
          <Alert tone="blue">Holiday: {data.holiday}. No attendance is taken.</Alert>
        </div>
      )}
      {(msg || error) && (
        <div className="mb-4">
          <Alert>{msg || error}</Alert>
        </div>
      )}
      <Card>
        {loading && !data ? (
          <Loading />
        ) : !data?.sessions.length ? (
          <Empty>No classes on this day. Add classes in the timetable, or create an extra session.</Empty>
        ) : (
          <Table head={["Period", "Class", "Section", "Window", "Status", "Present", ""]}>
            {data.sessions.map((s) => (
              <tr key={s.id} className="hover:bg-slate-50">
                <Td className="whitespace-nowrap">
                  <span className="font-semibold">P{s.period_number}</span> <span className="tabular text-slate-500">{s.start}–{s.end}</span>
                </Td>
                <Td>
                  <Link to={`/admin/sessions/${s.id}`} className="font-medium text-navy-700 hover:underline">
                    {s.course_code}
                  </Link>{" "}
                  <span className="text-slate-500">{s.course_name}</span>
                </Td>
                <Td>{s.section}</Td>
                <Td className="tabular whitespace-nowrap">
                  {s.open}–{s.close} {s.manually_adjusted && <span className="text-xs text-navy-600">(adjusted)</span>}
                </Td>
                <Td>
                  <StatusBadge status={s.status} />
                </Td>
                <Td className="tabular">
                  {s.present}/{s.enrolled}
                </Td>
                <Td className="text-right whitespace-nowrap">
                  {s.status === "open" ? (
                    <Button size="sm" variant="secondary" onClick={() => act(s.id, "close_now")}>
                      Close now
                    </Button>
                  ) : s.status === "cancelled" ? (
                    <Button size="sm" variant="secondary" onClick={() => act(s.id, "restore")}>
                      Restore
                    </Button>
                  ) : (
                    data.date === data.server_time.slice(0, 10) && (
                      <Button size="sm" variant="secondary" onClick={() => act(s.id, "open_now", { minutes: 10 })}>
                        Open 10 min
                      </Button>
                    )
                  )}{" "}
                  <Link to={`/admin/sessions/${s.id}`}>
                    <Button size="sm" variant="ghost">
                      Roster
                    </Button>
                  </Link>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {adhoc && data && <AdhocModal date={data.date} onClose={() => setAdhoc(false)} onSaved={() => { setAdhoc(false); void reload(); }} />}
    </>
  );
}

function AdhocModal({ date, onClose, onSaved }: { date: string; onClose: () => void; onSaved: () => void }) {
  const sections = useApi<Section[]>("/api/admin/sections").data ?? [];
  const courses = useApi<Course[]>("/api/admin/courses").data ?? [];
  const now = new Date();
  const hh = (d: Date) => d.toTimeString().slice(0, 5);
  const [f, setF] = useState({ date, period_number: 1, section_id: 0, course_id: 0, start: hh(now), end: hh(new Date(now.getTime() + 50 * 60000)), open: hh(now), close: hh(new Date(now.getTime() + 10 * 60000)), note: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/admin/sessions", { ...f, section_id: f.section_id || sections[0]?.id, course_id: f.course_id || courses[0]?.id });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const t = (k: "start" | "end" | "open" | "close", label: string) => <Field label={label}>{(id) => <Input id={id} type="time" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />}</Field>;
  return (
    <Modal open title="Extra session" onClose={onClose} footer={<Button onClick={save} busy={busy}>Create session</Button>}>
      <div className="space-y-3">
        {error && <Alert>{error}</Alert>}
        <p className="text-sm text-slate-500">For a make-up class or a demonstration. Times are in the institution's timezone.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date">{(id) => <Input id={id} type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} />}</Field>
          <Field label="Period number">{(id) => <Input id={id} type="number" min={1} max={16} value={f.period_number} onChange={(e) => setF({ ...f, period_number: Number(e.target.value) })} />}</Field>
          <Field label="Section">
            {(id) => (
              <Select id={id} value={f.section_id || sections[0]?.id || ""} onChange={(e) => setF({ ...f, section_id: Number(e.target.value) })}>
                {sections.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Course">
            {(id) => (
              <Select id={id} value={f.course_id || courses[0]?.id || ""} onChange={(e) => setF({ ...f, course_id: Number(e.target.value) })}>
                {courses.map((c) => <option key={c.id} value={c.id}>{c.code}</option>)}
              </Select>
            )}
          </Field>
          {t("start", "Class starts")}
          {t("end", "Class ends")}
          {t("open", "Attendance opens")}
          {t("close", "Attendance closes")}
        </div>
      </div>
    </Modal>
  );
}
