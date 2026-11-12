import { useState } from "react";
import { GuidedEnrollment } from "../components/GuidedEnrollment";
import {
  Alert,
  Button,
  Card,
  Field,
  Input,
  PageHeader,
  StatusBadge,
} from "../components/ui";
import { api, errorText } from "../lib/api";
import { useApi } from "../lib/hooks";

export type Batch = {
  id: string;
  student_id: number;
  version: number;
  status: string;
  name?: string;
  roll_number?: string;
  created_at: string;
  expires_on: string;
  cc_verified_at?: string;
  samples: {
    id: number;
    slot: number;
    photo_url: string | null;
    quality: { feature_norm: number; problems: string[] };
  }[];
};
type Enrollment = {
  account_state: string;
  enrollment_state: string;
  days_until_expiry: number | null;
  expires_on: string | null;
  renewal_deadline: string | null;
  can_enroll: boolean;
  active_version: number | null;
  history: Batch[];
};

export default function V2Student() {
  const { data, error, reload } = useApi<Enrollment>(
    "/api/v2/student/enrollment",
    15000,
  );
  const records = useApi<
    { date: string; course: string; status: string; revision: number }[]
  >("/api/v2/student/attendance");
  const [photos, setPhotos] = useState<Blob[]>([]);
  const [consent, setConsent] = useState(false);
  const [retention, setRetention] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  return (
    <div className="space-y-5">
      <PageHeader
        title="My central enrollment"
        subtitle="Your account, face samples and semester renewal"
      />
      {(error || failure) && <Alert>{error || failure}</Alert>}
      {message && <Alert tone="green">{message}</Alert>}
      {data && (
        <Card title="Enrollment status">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <StatusBadge status={data.enrollment_state} />
            <p className="text-sm">Account: {data.account_state}</p>
          </div>
          {data.days_until_expiry !== null && (
            <p className="mt-4 text-xl font-medium">
              {data.days_until_expiry >= 0
                ? `Face enrollment expires in ${data.days_until_expiry} days.`
                : "Your face enrollment has expired."}
            </p>
          )}
          <p className="mt-2 text-sm text-slate-600">
            Valid until {data.expires_on ?? "semester not configured"}. Renew by{" "}
            {data.renewal_deadline ?? "date pending"}.
          </p>
          <p className="mt-2 text-sm">
            Classroom attendance uses the faculty hotspot and rotating QR.
            Faculty can always mark attendance manually.
          </p>
        </Card>
      )}
      {data?.can_enroll && (
        <Card
          title={
            data.active_version
              ? "Renew your three-sample enrollment"
              : "Capture three enrollment samples"
          }
        >
          <div className="space-y-4">
            <GuidedEnrollment onCaptured={setPhotos} />
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              I consent to encrypted face templates for attendance until the
              configured semester expiry. I can withdraw consent and use manual
              attendance.
            </label>
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                checked={retention}
                onChange={(e) => setRetention(e.target.checked)}
              />
              Keep encrypted photo previews for me and my assigned CC during
              review, until the retention deadline. Otherwise delete photos
              after processing.
            </label>
            <Field
              label="Current central password"
              hint="Reauthenticate before submitting new biometric samples."
            >
              {(id) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              )}
            </Field>
            <Button
              disabled={photos.length !== 3 || !consent || !password}
              busy={busy}
              onClick={async () => {
                setBusy(true);
                setFailure("");
                try {
                  const fd = new FormData();
                  photos.forEach((p, i) =>
                    fd.append("images", p, `sample${i + 1}.jpg`),
                  );
                  fd.append("consent", String(consent));
                  fd.append("retain_photos", String(retention));
                  fd.append("current_password", password);
                  await api.post("/api/v2/student/enrollments", fd);
                  setPassword("");
                  setPhotos([]);
                  setMessage(
                    "Submitted. Your assigned CC must check your identity in person, then an administrator gives final approval.",
                  );
                  await reload();
                } catch (e) {
                  setFailure(errorText(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Submit three samples for CC review
            </Button>
          </div>
        </Card>
      )}
      {data?.history.map((batch) => (
        <Card
          key={batch.id}
          title={`Enrollment version ${batch.version}`}
          actions={<StatusBadge status={batch.status} />}
        >
          <p className="mb-3 text-sm text-slate-500">
            Captured {new Date(batch.created_at).toLocaleString()} · expires{" "}
            {batch.expires_on}
          </p>
          <div className="grid grid-cols-3 gap-3">
            {batch.samples.map((s) => (
              <figure key={s.id}>
                {s.photo_url ? (
                  <img
                    src={s.photo_url}
                    alt={`Your enrollment sample ${s.slot}`}
                    className="aspect-square w-full rounded-lg object-cover"
                  />
                ) : (
                  <div className="flex aspect-square items-center rounded-lg bg-slate-100 p-2 text-xs text-slate-600">
                    Photo deleted under retention policy. Sample metadata
                    retained.
                  </div>
                )}
                <figcaption className="mt-2 text-xs">
                  Sample {s.slot} · quality checked
                </figcaption>
              </figure>
            ))}
          </div>
        </Card>
      ))}
      <Card title="Set up this phone once for classroom attendance">
        <p className="text-sm text-slate-600">
          Install the AttendX classroom certificate once on this phone. It works
          with authorized faculty laptops across this AttendX deployment, including
          offline classes. This does not start attendance.
        </p>
        <div className="mt-3 flex flex-wrap gap-4 text-sm text-navy-700 underline">
          <a href="/api/v2/public/classroom.mobileconfig">iPhone: download AttendX profile</a>
          <a href="/api/v2/public/classroom-ca.cer">Android: download classroom certificate</a>
        </div>
        <p className="mt-3 text-sm">
          On iPhone, install the downloaded profile in Settings, then open General
          → About → Certificate Trust Settings and enable full trust for AttendX
          offline classroom CA. On Android, install it as a CA certificate in your
          security settings. Your faculty app provides a camera check after you join
          the classroom Wi-Fi. Remove the profile when you stop using AttendX.
        </p>
      </Card>
      <Card title="Approved attendance">
        <p className="mb-3 text-sm text-slate-500">
          Only faculty-approved, synchronized attendance appears here.
        </p>
        {!records.data?.length ? (
          <p className="text-sm">No approved records yet.</p>
        ) : (
          records.data.map((r, i) => (
            <p
              key={i}
              className="flex justify-between border-b border-slate-100 py-2 text-sm"
            >
              <span>
                {r.date} · {r.course}
              </span>
              <StatusBadge status={r.status} />
            </p>
          ))
        )}
      </Card>
      <Card title="Privacy and account controls">
        <div className="flex flex-wrap gap-3">
          <a
            className="text-sm text-navy-700 underline"
            href="/change-password"
          >
            Change password
          </a>
          <Button
            variant="danger"
            onClick={async () => {
              if (
                !window.confirm(
                  "Delete all retained enrollment photos and templates? You will still be on the academic roster and can use manual attendance.",
                )
              )
                return;
              try {
                await api.post("/api/v2/student/consent/revoke");
                setMessage(
                  "Consent withdrawn. Central biometric material deleted. Offline devices receive the revocation on their next sync or lose authorization when their grant expires.",
                );
                await reload();
              } catch (e) {
                setFailure(errorText(e));
              }
            }}
          >
            Withdraw consent and delete biometrics
          </Button>
        </div>
      </Card>
    </div>
  );
}
