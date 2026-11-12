import { useState } from "react";
import { Alert, Button, Card, PageHeader, StatusBadge } from "../components/ui";
import { api, errorText } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import type { Batch } from "./V2Student";

export default function V2Faculty() {
  const { user, logout } = useAuth();
  const { data, error, reload } = useApi<Batch[]>(
    "/api/v2/faculty/enrollments",
    15000,
  );
  const attendance = useApi<
    { session_id: string; date: string; course: string; revision: number }[]
  >("/api/v2/faculty/attendance");
  const [failure, setFailure] = useState("");
  return (
    <main className="mx-auto max-w-5xl space-y-5 px-5 py-8">
      <PageHeader
        title={`Faculty portal · ${user?.display_name}`}
        subtitle="Enrollment identity verification for your assigned coordinator sections"
        actions={
          <Button variant="secondary" onClick={() => void logout()}>
            Sign out
          </Button>
        }
      />
      {(failure || error) && <Alert>{failure || error}</Alert>}
      <Alert tone="blue">
        Conduct classroom attendance in the faculty Windows application. Use
        this central portal for in-person CC identity checks. Administrator
        approval is a separate step.
      </Alert>
      {!data?.length && (
        <Card title="CC review queue">
          <p>No pending requests in your assigned coordinator sections.</p>
        </Card>
      )}
      {data?.map((b) => (
        <Review
          key={b.id}
          batch={b}
          onDecision={async (decision, in_person, reason) => {
            try {
              await api.post(`/api/v2/faculty/enrollments/${b.id}/verify`, {
                decision,
                in_person,
                reason,
              });
              await reload();
            } catch (e) {
              setFailure(errorText(e));
            }
          }}
        />
      ))}
      <Card title="Synchronized attendance">
        {attendance.data?.map((a) => (
          <p key={a.session_id} className="py-2 text-sm">
            {a.date} · {a.course} · approved revision {a.revision}
          </p>
        ))}
        {!attendance.data?.length && <p>No synchronized attendance yet.</p>}
      </Card>
    </main>
  );
}
function Review({
  batch: b,
  onDecision,
}: {
  batch: Batch;
  onDecision: (d: string, p: boolean, r: string) => Promise<void>;
}) {
  const [present, setPresent] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Card
      title={`${b.roll_number} · ${b.name}`}
      actions={<StatusBadge status={b.status} />}
    >
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          {b.samples.map((s) => (
            <div key={s.id}>
              {s.photo_url ? (
                <img
                  src={s.photo_url}
                  alt={`Submitted enrollment sample ${s.slot}`}
                  className="aspect-square rounded-lg object-cover"
                />
              ) : (
                <p className="bg-slate-100 p-4 text-sm">
                  Photo not retained. Use institutionally trusted identity
                  records in person.
                </p>
              )}
            </div>
          ))}
        </div>
        {b.status === "PENDING_CC_VERIFICATION" && (
          <>
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                checked={present}
                onChange={(e) => setPresent(e.target.checked)}
              />
              I physically checked this student in person against trusted
              identity records.
            </label>
            <label className="block text-sm">
              Verification notes / rejection reason
              <input
                className="mt-1 w-full rounded-lg border p-2"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={256}
              />
            </label>
            <div className="flex gap-2">
              <Button
                disabled={!present}
                busy={busy}
                onClick={async () => {
                  setBusy(true);
                  await onDecision("confirm", present, reason);
                  setBusy(false);
                }}
              >
                Confirm identity for admin review
              </Button>
              <Button
                variant="danger"
                disabled={!present || reason.trim().length < 3}
                busy={busy}
                onClick={async () => {
                  setBusy(true);
                  await onDecision("reject", present, reason);
                  setBusy(false);
                }}
              >
                Reject identity
              </Button>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}
