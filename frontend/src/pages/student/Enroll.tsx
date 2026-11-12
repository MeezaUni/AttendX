import { useState } from "react";
import { FaceCapture } from "../../components/FaceCapture";
import { Alert, Card, Loading, StatusBadge } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { fmtTime, useApi } from "../../lib/hooks";

type EnrollStatus = {
  face_status: string;
  can_enroll: boolean;
  has_active_template: boolean;
  latest: { status: string; created_at: string } | null;
};
export type EnrollResult = {
  ok: boolean;
  error?: string;
  status?: string;
  frames_used?: number;
  images: { index: number; ok: boolean; problems: string[] }[];
};

export default function Enroll() {
  const { refresh } = useAuth();
  const { data, loading, reload } = useApi<EnrollStatus>("/api/student/enrollment");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<EnrollResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (frames: Blob[]) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const fd = new FormData();
      frames.forEach((f, i) => fd.append("images", f, `enroll${i}.jpg`));
      fd.append("consent", String(consent));
      const r = await api.post<EnrollResult>("/api/student/enrollment", fd);
      setResult(r);
      await reload();
      await refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  if (loading && !data) return <Loading />;
  if (!data) return null;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">My face enrollment</h1>
        <p className="mt-1 flex items-center gap-2 text-sm text-slate-500">
          Status: <StatusBadge status={data.face_status} />
          {data.latest && <span>last update {fmtTime(data.latest.created_at, true)}</span>}
        </p>
      </div>
      {result?.ok && (
        <Alert tone="green" title="Enrollment submitted">
          {result.frames_used} photos were used. An administrator will approve your enrollment.
        </Alert>
      )}
      {result && !result.ok && (
        <Alert title="Enrollment not accepted">
          {result.error}
          {result.images.some((i) => !i.ok) && `\nProblems: ${[...new Set(result.images.flatMap((i) => i.problems))].join("; ")}`}
        </Alert>
      )}
      {error && <Alert>{error}</Alert>}
      {data.can_enroll ? (
        <Card title="Capture your face">
          <div className="space-y-4">
            <p className="text-sm text-slate-600">
              Five photos are taken from your live camera. They are turned into a numeric face template and are <strong>not</strong> stored as images.
            </p>
            <label className="flex items-start gap-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
              <input type="checkbox" className="mt-0.5 h-4 w-4 accent-navy-700" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span>
                I consent to AttendX storing an encrypted face template to verify my own attendance. I can ask for it to be deleted at any time.
              </span>
            </label>
            {consent ? <FaceCapture onCaptured={submit} busy={busy} /> : <p className="text-center text-sm text-slate-500">Tick the consent box to continue.</p>}
          </div>
        </Card>
      ) : (
        <Alert tone="blue">
          {data.has_active_template
            ? "Your face is enrolled. To re-enroll, ask an administrator to open enrollment for you."
            : data.face_status === "pending"
              ? "Your enrollment is waiting for administrator approval."
              : "Enrollment is not open for you. Ask an administrator."}
        </Alert>
      )}
    </div>
  );
}
