import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Alert, Button, Card, Empty, Field, Input, Loading, Modal, PageHeader, Select, Stat, StatusBadge, Table, Td } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { download, fmtDate, fmtTime, useApi } from "../../lib/hooks";
import { windowAction, type AdminSession } from "./Sessions";

type RosterRow = {
  student_id: number; roll_number: string; name: string; face_status: string; status: string; method: string | null;
  verified_at: string | null; match_score: number | null; override_reason: string | null; attempts: number;
  last_attempt: { decision: string; reason: string; at: string } | null;
};

export default function SessionDetail() {
  const { id } = useParams();
  const { data, loading, error, reload } = useApi<{ session: AdminSession; roster: RosterRow[] }>(`/api/admin/sessions/${id}`, 5000);
  const [fix, setFix] = useState<RosterRow | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [win, setWin] = useState(false);
  if (loading && !data) return <Loading />;
  if (error && !data) return <Alert>{error}</Alert>;
  if (!data) return null;
  const s = data.session;
  const count = (st: string) => data.roster.filter((r) => r.status === st).length;
  const act = async (action: string, extra?: Record<string, unknown>) => {
    setMsg(null);
    try {
      await windowAction(s.id, action, extra);
      await reload();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  return (
    <>
      <Link to="/admin/sessions" className="text-sm font-medium text-navy-700">
        ← Sessions
      </Link>
      <PageHeader
        title={`${s.course_code} · ${s.section}`}
        subtitle={
          <>
            {s.course_name} · {fmtDate(s.date)} · period {s.period_number} ({s.start}–{s.end}) · attendance {s.open}–{s.close} · live, refreshes every 5 s
          </>
        }
        actions={
          <>
            <StatusBadge status={s.status} />
            {s.status === "open" ? (
              <Button variant="secondary" onClick={() => act("close_now")}>Close now</Button>
            ) : s.status !== "cancelled" ? (
              <Button variant="secondary" onClick={() => act("open_now", { minutes: 10 })}>Open for 10 min</Button>
            ) : null}
            <Button variant="secondary" onClick={() => setWin(true)}>Change window</Button>
            {s.status !== "cancelled" ? (
              <Button variant="danger" onClick={() => act("cancel", { reason: "cancelled by admin" })}>Cancel class</Button>
            ) : (
              <Button variant="secondary" onClick={() => act("restore")}>Restore</Button>
            )}
            <Button variant="secondary" onClick={() => download(`/api/admin/reports/export.csv?d_from=${s.date}&d_to=${s.date}&section_id=${s.section_id}`)}>
              Export CSV
            </Button>
          </>
        }
      />
      {msg && <div className="mb-4"><Alert>{msg}</Alert></div>}
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Present" value={count("present") + count("late")} hint={`of ${data.roster.length}`} />
        <Stat label="Not marked" value={count("not_marked")} />
        <Stat label="Absent" value={count("absent")} hint={s.status === "closed" ? "window closed" : "after close"} />
        <Stat label="Excused" value={count("excused")} />
      </div>
      <Card title="Roster">
        {data.roster.length === 0 ? (
          <Empty>No students in this section.</Empty>
        ) : (
          <Table head={["Roll no.", "Name", "Status", "Method", "Time", "Score", "Attempts", ""]}>
            {data.roster.map((r) => (
              <tr key={r.student_id}>
                <Td className="tabular font-medium">{r.roll_number}</Td>
                <Td>
                  {r.name}
                  {r.face_status !== "approved" && <span className="ml-1 text-xs text-slate-400">(no face)</span>}
                </Td>
                <Td>
                  <StatusBadge status={r.status} />
                  {r.override_reason && <span className="block text-xs text-slate-400">{r.override_reason}</span>}
                </Td>
                <Td>{r.method ?? "—"}</Td>
                <Td className="tabular whitespace-nowrap">{fmtTime(r.verified_at)}</Td>
                <Td className="tabular">{r.match_score?.toFixed(3) ?? "—"}</Td>
                <Td>
                  {r.attempts}
                  {r.last_attempt && r.status !== "present" && (
                    <span className="block text-xs text-slate-400" title={r.last_attempt.reason}>
                      last: {r.last_attempt.decision.replace("_", " ")}
                    </span>
                  )}
                </Td>
                <Td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => setFix(r)}>Correct</Button>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      {fix && <CorrectionModal sessionId={s.id} row={fix} onClose={() => setFix(null)} onSaved={() => { setFix(null); void reload(); }} />}
      {win && <WindowModal session={s} onClose={() => setWin(false)} onSaved={() => { setWin(false); void reload(); }} />}
    </>
  );
}

function CorrectionModal({ sessionId, row, onClose, onSaved }: { sessionId: number; row: RosterRow; onClose: () => void; onSaved: () => void }) {
  const [status, setStatus] = useState(row.status === "present" ? "absent" : "present");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.put(`/api/admin/sessions/${sessionId}/records/${row.student_id}`, { status, reason });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open title={`Correct attendance: ${row.roll_number}`} onClose={onClose} footer={<Button onClick={save} busy={busy} disabled={reason.trim().length < 3}>Save correction</Button>}>
      <div className="space-y-3">
        {error && <Alert>{error}</Alert>}
        <p className="text-sm text-slate-600">
          Manual corrections are the non-biometric fallback (for example a broken camera). Each correction is recorded in the audit log with your name and reason.
        </p>
        <Field label="Status">
          {(id) => (
            <Select id={id} value={status} onChange={(e) => setStatus(e.target.value)}>
              {["present", "late", "absent", "excused"].map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
          )}
        </Field>
        <Field label="Reason (required)">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. verified in person; phone camera broken" />}</Field>
      </div>
    </Modal>
  );
}

function WindowModal({ session, onClose, onSaved }: { session: AdminSession; onClose: () => void; onSaved: () => void }) {
  const [open, setOpen] = useState(session.open);
  const [close, setClose] = useState(session.close);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try {
      await windowAction(session.id, "set_window", { open, close, reason: "window changed by admin" });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <Modal open title="Attendance window" onClose={onClose} footer={<Button onClick={save}>Save window</Button>}>
      {error && <Alert>{error}</Alert>}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Opens">{(id) => <Input id={id} type="time" value={open} onChange={(e) => setOpen(e.target.value)} />}</Field>
        <Field label="Closes">{(id) => <Input id={id} type="time" value={close} onChange={(e) => setClose(e.target.value)} />}</Field>
      </div>
      <p className="mt-2 text-xs text-slate-500">This overrides the timetable for this session only.</p>
    </Modal>
  );
}
