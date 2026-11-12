import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Badge, Button, Card, Input, PageHeader, Select, Td } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { WEEKDAYS, useApi } from "../../lib/hooks";
import type { Section } from "./Students";

type Row = {
  weekday: number | null; period: number | null; start: string | null; end: string | null; course_code: string | null;
  course_name: string | null; section: string | null; faculty: string | null; room: string | null; is_break: boolean;
  source: string; flags: string[];
};
type Preview = { kind: string; layout: string; rows: Row[]; warnings: string[] };

export default function TimetableImport() {
  const sections = useApi<Section[]>("/api/admin/sections").data ?? [];
  const [preview, setPreview] = useState<Preview | null>(null);
  const [rows, setRows] = useState<(Row & { keep: boolean })[]>([]);
  const [sectionId, setSectionId] = useState<string>("");
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    setDone(null);
    setPreview(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const p = await api.post<Preview>("/api/admin/timetable/import/preview", fd);
      setPreview(p);
      setRows(p.rows.map((r) => ({ ...r, keep: true })));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const set = (i: number, k: keyof Row | "keep", v: unknown) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v, flags: k === "keep" ? r.flags : r.flags.filter((f) => !f.startsWith("weekday") && !f.startsWith("course code missing")) } : r)));

  const commit = async () => {
    setBusy(true);
    setError(null);
    try {
      const keep = rows.filter((r) => r.keep).map(({ keep: _k, flags: _f, source: _s, ...r }) => r);
      const res = await api.post<{ saved: number; created_courses: string[] }>("/api/admin/timetable/import/commit", {
        rows: keep,
        default_section_id: sectionId ? Number(sectionId) : null,
        replace_sections: replace,
      });
      setDone(`${res.saved} timetable slots saved.${res.created_courses.length ? ` New courses: ${res.created_courses.join(", ")}.` : ""}`);
      setPreview(null);
      setRows([]);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const problems = (r: Row) => (r.weekday === null ? 1 : 0) + (r.period === null ? 1 : 0) + (!r.is_break && !r.course_code ? 1 : 0);
  const blocking = rows.filter((r) => r.keep && problems(r) > 0).length;

  return (
    <>
      <Link to="/admin/timetable" className="text-sm font-medium text-navy-700">
        ← Timetable
      </Link>
      <PageHeader title="Import timetable" subtitle="Upload CSV, XLSX, PDF or a photo/scan. Review and correct every row before saving; nothing is saved until you confirm." />
      {done && (
        <div className="mb-4">
          <Alert tone="green" title="Import saved">
            {done} <Link to="/admin/timetable" className="font-semibold underline">View timetable</Link>
          </Alert>
        </div>
      )}
      {error && (
        <div className="mb-4">
          <Alert title="Import problem">{error}</Alert>
        </div>
      )}
      <Card title="1. Upload a file">
        <input
          type="file"
          accept=".csv,.xlsx,.pdf,.png,.jpg,.jpeg,.webp"
          disabled={busy}
          aria-label="Timetable file"
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          className="block w-full text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-navy-50 file:px-3 file:py-2 file:text-sm file:font-medium file:text-navy-800"
        />
        <p className="mt-3 text-xs text-slate-500">
          Two layouts are understood. <strong>List</strong>: one row per class with columns day, period, start, end, course_code, course_name, section.{" "}
          <strong>Grid</strong>: weekdays down the first column, periods or time ranges across the top, course codes in the cells and BREAK/LUNCH for breaks.
          Values that cannot be read are left empty and flagged; they are never guessed.
        </p>
        {busy && <p className="mt-3 text-sm text-navy-700">Reading file…</p>}
      </Card>

      {preview && (
        <Card
          className="mt-5"
          title={`2. Review ${rows.length} rows (${preview.layout} layout, ${preview.kind})`}
          actions={blocking > 0 ? <Badge tone="red">{blocking} rows need fixing</Badge> : <Badge tone="green">ready</Badge>}
        >
          {preview.warnings.length > 0 && (
            <div className="mb-4">
              <Alert tone="amber">{preview.warnings.join("\n")}</Alert>
            </div>
          )}
          <div className="mb-4 grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              <span className="font-medium text-slate-700">Section for rows without one</span>
              <Select value={sectionId} onChange={(e) => setSectionId(e.target.value)} className="mt-1">
                <option value="">— choose —</option>
                {sections.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
              <input type="checkbox" className="h-4 w-4 accent-navy-700" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
              Replace the existing timetable of these sections
            </label>
          </div>
          <div className="-mx-4 overflow-x-auto sm:mx-0">
            <table className="min-w-[1000px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                  {["Use", "Day", "Period", "Start", "End", "Break", "Course code", "Course name", "Section", "Notes"].map((h) => (
                    <th key={h} className="px-2 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((r, i) => {
                  const bad = r.keep && problems(r) > 0;
                  return (
                    <tr key={i} className={bad ? "bg-red-50/60" : r.flags.length ? "bg-amber-50/40" : ""}>
                      <Td className="px-2">
                        <input type="checkbox" className="h-4 w-4 accent-navy-700" checked={r.keep} onChange={(e) => set(i, "keep", e.target.checked)} aria-label={`Use row ${i + 1}`} />
                      </Td>
                      <Td className="px-2">
                        <Select value={r.weekday ?? ""} onChange={(e) => set(i, "weekday", e.target.value === "" ? null : Number(e.target.value))} className={`h-8 w-28 ${r.weekday === null ? "ring-red-400" : ""}`} aria-label="Weekday">
                          <option value="">?</option>
                          {WEEKDAYS.map((d, k) => (
                            <option key={d} value={k}>
                              {d.slice(0, 3)}
                            </option>
                          ))}
                        </Select>
                      </Td>
                      <Td className="px-2">
                        <Input type="number" min={1} max={16} value={r.period ?? ""} onChange={(e) => set(i, "period", e.target.value ? Number(e.target.value) : null)} className={`h-8 w-16 ${r.period === null ? "ring-red-400" : ""}`} aria-label="Period" />
                      </Td>
                      <Td className="px-2">
                        <Input type="time" value={r.start ?? ""} onChange={(e) => set(i, "start", e.target.value || null)} className="h-8 w-28" aria-label="Start" />
                      </Td>
                      <Td className="px-2">
                        <Input type="time" value={r.end ?? ""} onChange={(e) => set(i, "end", e.target.value || null)} className="h-8 w-28" aria-label="End" />
                      </Td>
                      <Td className="px-2">
                        <input type="checkbox" className="h-4 w-4 accent-amber-600" checked={r.is_break} onChange={(e) => set(i, "is_break", e.target.checked)} aria-label="Break" />
                      </Td>
                      <Td className="px-2">
                        <Input value={r.course_code ?? ""} disabled={r.is_break} onChange={(e) => set(i, "course_code", e.target.value.toUpperCase() || null)} className={`h-8 w-28 ${!r.is_break && !r.course_code ? "ring-red-400" : ""}`} aria-label="Course code" />
                      </Td>
                      <Td className="px-2">
                        <Input value={r.course_name ?? ""} disabled={r.is_break} onChange={(e) => set(i, "course_name", e.target.value || null)} className="h-8 w-44" aria-label="Course name" />
                      </Td>
                      <Td className="px-2">
                        <Input value={r.section ?? ""} onChange={(e) => set(i, "section", e.target.value || null)} className="h-8 w-28" placeholder="default" aria-label="Section" />
                      </Td>
                      <Td className="max-w-xs px-2 text-xs text-amber-800">
                        {r.flags.join("; ")}
                        {r.source && <span className="block text-slate-400">read: “{r.source}”</span>}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-end gap-3">
            <p className="text-sm text-slate-500">New course codes need a course name. Unknown section names must exist first.</p>
            <Button onClick={commit} busy={busy} disabled={blocking > 0 || !rows.some((r) => r.keep)}>
              3. Save {rows.filter((r) => r.keep).length} rows
            </Button>
          </div>
        </Card>
      )}
    </>
  );
}
