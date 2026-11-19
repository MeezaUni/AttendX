import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, Empty, Field, Input, Loading, Modal, PageHeader, Select, Table, Tabs, Td, cx } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { WEEKDAYS, fmtDate, useApi } from "../../lib/hooks";
import type { Course, Section } from "./Students";

export type Period = { id?: number; number: number; label: string; start_time: string; end_time: string; is_break: boolean };
type Entry = {
  id: number; weekday: number; period_number: number; section_id: number; course_id: number | null; course_code: string | null;
  course_name: string | null; faculty_id: number | null; faculty: string | null; room: string; is_break: boolean;
  start_time: string | null; end_time: string | null;
};
type Faculty = { id: number; name: string };
type Holiday = { id: number; date: string; name: string };

export default function Timetable() {
  const [tab, setTab] = useState<"week" | "periods" | "holidays">("week");
  return (
    <>
      <PageHeader
        title="Timetable"
        subtitle="Weekly classes, bell schedule and holidays. Faculty starts each five-minute attendance session during class or within five minutes after it ends. All times use the institution's timezone."
        actions={
          <Link to="/admin/timetable/import">
            <Button variant="secondary">Import timetable</Button>
          </Link>
        }
      />
      <Tabs
        value={tab}
        onChange={setTab}
        items={[
          { value: "week", label: "Weekly timetable" },
          { value: "periods", label: "Class periods" },
          { value: "holidays", label: "Holidays" },
        ]}
      />
      {tab === "week" && <WeekGrid />}
      {tab === "periods" && <Periods />}
      {tab === "holidays" && <Holidays />}
    </>
  );
}

function WeekGrid() {
  const sections = useApi<Section[]>("/api/admin/sections").data;
  const [sid, setSid] = useState<number | null>(null);
  useEffect(() => {
    if (sid === null && sections?.length) setSid(sections[0].id);
  }, [sections, sid]);
  const periods = useApi<Period[]>("/api/admin/periods").data ?? [];
  const entries = useApi<Entry[]>(sid ? `/api/admin/timetable?section_id=${sid}` : null);
  const courses = useApi<Course[]>("/api/admin/courses").data ?? [];
  const faculty = useApi<Faculty[]>("/api/admin/faculty").data ?? [];
  const [edit, setEdit] = useState<{ weekday: number; period: number; entry?: Entry } | null>(null);
  const [showSat, setShowSat] = useState(false);
  if (!sections) return <Loading />;
  if (!sections.length) return <Empty>Create a section first (Courses &amp; sections).</Empty>;
  const days = showSat || entries.data?.some((e) => e.weekday === 5) ? 6 : 5;
  const at = (wd: number, p: number) => entries.data?.find((e) => e.weekday === wd && e.period_number === p);
  // Columns in time order: teaching periods, break periods, and the unnumbered gaps between
  // consecutive periods (e.g. 10:40-10:50), shown like a printed university timetable.
  type Col = { kind: "period"; p: Period } | { kind: "break"; label: string; start: string; end: string };
  const cols: Col[] = [];
  periods.forEach((p, i) => {
    const prev = periods[i - 1];
    if (prev && prev.end_time < p.start_time) cols.push({ kind: "break", label: "Break", start: prev.end_time, end: p.start_time });
    cols.push(p.is_break ? { kind: "break", label: p.label || "Break", start: p.start_time, end: p.end_time } : { kind: "period", p });
  });
  const tint = (i: number) => (i % 2 ? "bg-cyan-100 dark:bg-cyan-900/40" : "bg-amber-100 dark:bg-amber-900/40");

  return (
    <Card
      title={
        <Select value={sid ?? ""} onChange={(e) => setSid(Number(e.target.value))} className="w-48" aria-label="Section">
          {sections.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </Select>
      }
      actions={
        <label className="flex items-center gap-2 text-sm text-slate-600">
          <input type="checkbox" className="h-4 w-4 accent-navy-700" checked={showSat} onChange={(e) => setShowSat(e.target.checked)} /> Saturday
        </label>
      }
    >
      <div className="-mx-4 overflow-x-auto sm:mx-0">
        <table className="w-full min-w-[980px] table-fixed border-collapse text-sm">
          <thead>
            <tr>
              <th className="w-20 border border-slate-300 dark:border-slate-600" />
              {cols.map((c, i) =>
                c.kind === "break" ? (
                  <th key={`b${i}`} className="w-14 border border-slate-300 bg-slate-50 px-1 py-2 font-normal dark:border-slate-600 dark:bg-slate-800">
                    <p className="text-xs font-semibold text-slate-700 dark:text-slate-200">{c.label === "Break" ? "Break" : "Lunch"}</p>
                    <p className="tabular text-[10px] leading-tight text-slate-500">{c.start}<br />{c.end}</p>
                  </th>
                ) : (
                  <th key={c.p.number} className={cx("border border-slate-300 px-1 py-2 font-normal dark:border-slate-600", tint(c.p.number))}>
                    <p className="text-xl font-semibold text-slate-900 dark:text-slate-50">{c.p.number}</p>
                    <p className="tabular text-[11px] text-slate-600 dark:text-slate-300">
                      {c.p.start_time} – {c.p.end_time}
                    </p>
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {WEEKDAYS.slice(0, days).map((day, wd) => (
              <tr key={day}>
                <th className={cx("border border-slate-300 text-2xl font-semibold text-slate-900 dark:border-slate-600 dark:text-slate-50", tint(wd))}>
                  {day.slice(0, 3)}
                </th>
                {cols.map((c, i) => {
                  if (c.kind === "break") {
                    // One tall break column spanning every day, as on the printed timetable.
                    if (wd !== 0) return null;
                    return (
                      <td key={`b${i}`} rowSpan={days} className="border border-slate-300 bg-slate-50 dark:border-slate-600 dark:bg-slate-800">
                        <span className="mx-auto block rotate-180 text-center text-2xl tracking-wide text-slate-700 [writing-mode:vertical-rl] dark:text-slate-200">
                          {c.label === "Break" ? "Break" : c.label}
                        </span>
                      </td>
                    );
                  }
                  const p = c.p;
                  const e = at(wd, p.number);
                  return (
                    <td key={p.number} className="h-24 border border-slate-300 p-0 dark:border-slate-600">
                      <button
                        onClick={() => setEdit({ weekday: wd, period: p.number, entry: e })}
                        aria-label={`${day} period ${p.number}${e?.course_code ? `: ${e.course_code}` : ""}`}
                        className={cx(
                          "flex h-full w-full flex-col items-center justify-between px-1 py-1.5 text-center transition-colors",
                          e?.is_break ? "bg-slate-50 dark:bg-slate-800" : e ? "bg-white hover:bg-navy-50 dark:bg-slate-900 dark:hover:bg-slate-800" : "text-slate-300 hover:bg-navy-50 hover:text-navy-600 dark:hover:bg-slate-800",
                        )}
                      >
                        {e?.is_break ? (
                          <span className="m-auto text-xs font-medium text-slate-600">Break</span>
                        ) : e ? (
                          <>
                            <span className="block w-full truncate text-[10px] text-slate-500">{e.faculty ?? ""}</span>
                            <span className="block font-semibold text-slate-900 dark:text-slate-50">{e.course_code}</span>
                            <span className="flex w-full justify-between text-[10px] text-slate-500">
                              <span>{e.start_time || e.end_time ? "custom time" : ""}</span>
                              <span className="font-medium text-slate-700 dark:text-slate-300">{e.room}</span>
                            </span>
                          </>
                        ) : (
                          <span className="m-auto text-lg">+</span>
                        )}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edit && sid && (
        <EntryModal
          sectionId={sid}
          weekday={edit.weekday}
          period={periods.find((p) => p.number === edit.period)!}
          entry={edit.entry}
          courses={courses}
          faculty={faculty}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            void entries.reload();
          }}
        />
      )}
    </Card>
  );
}

function EntryModal({ sectionId, weekday, period, entry, courses, faculty, onClose, onSaved }: {
  sectionId: number; weekday: number; period: Period; entry?: Entry; courses: Course[]; faculty: Faculty[]; onClose: () => void; onSaved: () => void;
}) {
  const [f, setF] = useState({
    course_id: entry?.course_id ?? courses[0]?.id ?? null,
    faculty_id: entry?.faculty_id ?? null,
    room: entry?.room ?? "",
    is_break: entry?.is_break ?? false,
    custom: Boolean(entry?.start_time || entry?.end_time),
    start_time: entry?.start_time ?? period.start_time,
    end_time: entry?.end_time ?? period.end_time,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setError(null);
    const body = {
      weekday, period_number: period.number, section_id: sectionId, course_id: f.is_break ? null : f.course_id,
      faculty_id: f.faculty_id, room: f.room, is_break: f.is_break,
      ...(f.custom ? { start_time: f.start_time, end_time: f.end_time } : {}),
    };
    try {
      if (entry) await api.put(`/api/admin/timetable/${entry.id}`, body);
      else await api.post("/api/admin/timetable", body);
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const del = async () => {
    if (!entry) return;
    await api.del(`/api/admin/timetable/${entry.id}`);
    onSaved();
  };
  const time = (k: "start_time" | "end_time", label: string) => (
    <Field label={label}>{(id) => <Input id={id} type="time" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} />}</Field>
  );
  return (
    <Modal
      open
      title={`${WEEKDAYS[weekday]}, period ${period.number}`}
      onClose={onClose}
      footer={
        <>
          {entry && (
            <Button variant="danger" onClick={del} className="mr-auto">
              Clear slot
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={save} busy={busy}>
            Save
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error && <Alert>{error}</Alert>}
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" className="h-4 w-4 accent-navy-700" checked={f.is_break} onChange={(e) => setF({ ...f, is_break: e.target.checked })} />
          Mark this slot as a break (no attendance)
        </label>
        {!f.is_break && (
          <>
            <Field label="Course">
              {(id) => (
                <Select id={id} value={f.course_id ?? ""} onChange={(e) => setF({ ...f, course_id: Number(e.target.value) })}>
                  {courses.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.code} {c.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Faculty (optional)">
                {(id) => (
                  <Select id={id} value={f.faculty_id ?? ""} onChange={(e) => setF({ ...f, faculty_id: e.target.value ? Number(e.target.value) : null })}>
                    <option value="">Course default</option>
                    {faculty.map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              <Field label="Room">{(id) => <Input id={id} value={f.room} onChange={(e) => setF({ ...f, room: e.target.value })} />}</Field>
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" className="h-4 w-4 accent-navy-700" checked={f.custom} onChange={(e) => setF({ ...f, custom: e.target.checked })} />
              Use custom class times for this slot (default: {period.start_time}–{period.end_time})
            </label>
            {f.custom && (
              <div className="grid grid-cols-2 gap-3">
                {time("start_time", "Class starts")}
                {time("end_time", "Class ends")}
              </div>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}

function Periods() {
  const { data, loading, reload } = useApi<Period[]>("/api/admin/periods");
  const [rows, setRows] = useState<Period[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  useEffect(() => {
    if (data) setRows(data);
  }, [data]);
  if (loading && !data) return <Loading />;
  const set = (i: number, k: keyof Period, v: string | boolean | number) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.put("/api/admin/periods", rows.map(({ number, label, start_time, end_time, is_break }) => ({ number, label, start_time, end_time, is_break })));
      setMsg({ tone: "green", text: "Class times saved. Faculty starts attendance; each session lasts five minutes. Reauthorize the faculty app to download updated class times." });
      await reload();
    } catch (e) {
      setMsg({ tone: "red", text: errorText(e) });
    } finally {
      setBusy(false);
    }
  };
  const add = () => {
    const last = rows[rows.length - 1];
    setRows([...rows, { number: (last?.number ?? 0) + 1, label: "", start_time: last?.end_time ?? "09:00", end_time: last?.end_time ?? "09:55", is_break: false }]);
  };
  return (
    <Card
      title="Class periods"
      actions={
        <>
          <Button variant="secondary" size="sm" onClick={add}>
            Add period
          </Button>
          <Button size="sm" onClick={save} busy={busy}>
            Save schedule
          </Button>
        </>
      }
    >
      {msg && (
        <div className="mb-3">
          <Alert tone={msg.tone}>{msg.text}</Alert>
        </div>
      )}
      <Table head={["No.", "Label", "Class starts", "Class ends", "Break", ""]} dense>
        {rows.map((r, i) => (
          <tr key={i} className={r.is_break ? "bg-amber-50/50" : ""}>
            <Td className="tabular font-semibold">{r.number}</Td>
            <Td>
              <Input value={r.label} onChange={(e) => set(i, "label", e.target.value)} className="h-9 min-w-24" aria-label={`Period ${r.number} label`} />
            </Td>
            {(["start_time", "end_time"] as const).map((k) => (
              <Td key={k}>
                <Input type="time" value={r[k]} onChange={(e) => set(i, k, e.target.value)} className="h-9 w-28" aria-label={`Period ${r.number} ${k}`} />
              </Td>
            ))}
            <Td>
              <input type="checkbox" className="h-4 w-4 accent-amber-600" checked={r.is_break} onChange={(e) => set(i, "is_break", e.target.checked)} aria-label={`Period ${r.number} is a break`} />
            </Td>
            <Td>
              <Button size="sm" variant="ghost" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                Remove
              </Button>
            </Td>
          </tr>
        ))}
      </Table>
      <p className="mt-3 text-xs text-slate-500">
        Faculty can start attendance during class or up to five minutes after class end. Collection lasts five minutes from that start. The faculty app reminds them at class end if attendance has not started. Breaks never accept attendance.
      </p>
    </Card>
  );
}

function Holidays() {
  const { data, reload } = useApi<Holiday[]>("/api/admin/holidays");
  const [date, setDate] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const add = async () => {
    setError(null);
    try {
      await api.post("/api/admin/holidays", { date, name });
      setDate("");
      setName("");
      await reload();
    } catch (e) {
      setError(errorText(e));
    }
  };
  return (
    <Card title="Holidays">
      {error && <Alert>{error}</Alert>}
      <div className="mb-4 flex flex-col gap-2 sm:flex-row">
        <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="sm:w-44" aria-label="Date" />
        <Input placeholder="Holiday name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Holiday name" />
        <Button onClick={add} disabled={!date || !name}>
          Add holiday
        </Button>
      </div>
      {!data?.length ? (
        <Empty>No holidays.</Empty>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm">
          {data.map((h) => (
            <li key={h.id} className="flex items-center justify-between py-2">
              <span>
                <span className="font-medium">{fmtDate(h.date)}</span> · {h.name}
              </span>
              <Button size="sm" variant="ghost" onClick={async () => { await api.del(`/api/admin/holidays/${h.id}`); await reload(); }}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-slate-500">Adding a holiday cancels any sessions already generated for that day.</p>
    </Card>
  );
}
