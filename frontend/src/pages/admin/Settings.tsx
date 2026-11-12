import { useEffect, useState } from "react";
import { Alert, Button, Card, Field, Input, Loading, PageHeader, Select, Table, Td } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { fmtTime, useApi } from "../../lib/hooks";

type Runtime = Record<string, number | string | number[]>;
type SettingsData = { runtime: Runtime; fixed: Record<string, string | boolean>; engine: Record<string, unknown> };
type AuditRow = { id: number; at: string; actor: string; action: string; entity: string; entity_id: string; details: Record<string, unknown> };

const GROUPS: { title: string; note: string; keys: [string, string, string?][] }[] = [
  {
    title: "Face verification (provisional thresholds)",
    note: "AdaFace cosine similarity between live frames and the enrolled template. These defaults are provisional and must be validated on your own students and cameras (see docs/thresholds.md).",
    keys: [
      ["match_threshold", "MATCH when the median score is at least", "0.40"],
      ["nonmatch_threshold", "NON-MATCH when the median score is below", "0.25"],
      ["min_feature_norm", "Minimum face-image quality (feature norm)", "14"],
      ["min_face_px", "Minimum face size (pixels)", "80"],
      ["min_sharpness", "Minimum sharpness", "12"],
      ["enroll_min_frames", "Enrollment: good images required", "3"],
      ["enroll_min_consistency", "Enrollment: minimum agreement between images", "0.50"],
    ],
  },
  {
    title: "Liveness challenge",
    note: "Randomised head-movement and blink challenge. It stops photos and still screens, not every replay or deepfake attack.",
    keys: [
      ["challenge_steps", "Actions per challenge (1–4)"],
      ["challenge_ttl_seconds", "Time limit (seconds)"],
      ["yaw_delta", "Head turn needed (fraction of face width)"],
      ["pitch_delta", "Look-up movement needed"],
      ["blink_closed", "Blink: eyes counted closed above"],
      ["blink_open", "Blink: eyes counted open below"],
      ["max_attempts_per_session", "Attempts per student per class"],
    ],
  },
];

export default function Settings() {
  const { data, loading, reload } = useApi<SettingsData>("/api/admin/settings");
  const audit = useApi<AuditRow[]>("/api/admin/audit?limit=100");
  const [form, setForm] = useState<Runtime>({});
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (data) setForm(data.runtime);
  }, [data]);
  if (loading && !data) return <Loading />;
  if (!data) return null;
  const save = async () => {
    setBusy(true);
    setMsg(null);
    const changes = Object.fromEntries(Object.entries(form).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(data.runtime[k])));
    try {
      await api.put("/api/admin/settings", changes);
      setMsg({ tone: "green", text: `${Object.keys(changes).length} setting(s) saved and audited.` });
      await reload();
      await audit.reload();
    } catch (e) {
      setMsg({ tone: "red", text: errorText(e) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <PageHeader title="Settings" actions={<Button onClick={save} busy={busy}>Save changes</Button>} />
      {msg && <div className="mb-4"><Alert tone={msg.tone}>{msg.text}</Alert></div>}
      <div className="grid gap-5 lg:grid-cols-2">
        {GROUPS.map((g) => (
          <Card key={g.title} title={g.title}>
            <p className="mb-4 text-xs text-slate-500">{g.note}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              {g.keys.map(([k, label, def]) => (
                <Field key={k} label={label} hint={def ? `default ${def}` : undefined}>
                  {(id) => <Input id={id} type="number" step="any" value={String(form[k] ?? "")} onChange={(e) => setForm({ ...form, [k]: e.target.value === "" ? "" : Number(e.target.value) })} />}
                </Field>
              ))}
            </div>
          </Card>
        ))}
        <Card title="Eligibility and system">
          <div className="space-y-4">
            <Field label="Who may mark attendance for a class">
              {(id) => (
                <Select id={id} value={String(form.eligibility ?? "section")} onChange={(e) => setForm({ ...form, eligibility: e.target.value })}>
                  <option value="section">Every student of the class's section</option>
                  <option value="course_enrollment">Only students enrolled in the course</option>
                </Select>
              )}
            </Field>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-slate-500">Timezone</dt><dd>{String(data.fixed.timezone)}</dd>
              <dt className="text-slate-500">Face engine</dt><dd>{String(data.engine.engine)} · {String(data.engine.model_id)} · {String(data.engine.device ?? "not loaded")}</dd>
              <dt className="text-slate-500">Demo mode</dt><dd>{data.fixed.demo_mode ? "on" : "off"}</dd>
            </dl>
            <p className="text-xs text-slate-500">Timezone, engine and device are set in the server environment (.env) and need a restart to change.</p>
          </div>
        </Card>
        <Card title="Audit log (latest 100)" className="lg:col-span-2">
          <Table head={["Time", "Who", "Action", "Target", "Details"]} dense>
            {(audit.data ?? []).map((a) => (
              <tr key={a.id}>
                <Td className="whitespace-nowrap">{fmtTime(a.at, true)}</Td>
                <Td>{a.actor}</Td>
                <Td className="font-medium">{a.action}</Td>
                <Td className="whitespace-nowrap">{a.entity} {a.entity_id}</Td>
                <Td className="max-w-md truncate text-xs text-slate-500" >{JSON.stringify(a.details)}</Td>
              </tr>
            ))}
          </Table>
        </Card>
      </div>
    </>
  );
}
