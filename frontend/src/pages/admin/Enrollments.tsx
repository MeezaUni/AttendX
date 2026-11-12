import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, Empty, Loading, PageHeader, StatusBadge, Table, Tabs, Td } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { fmtTime, useApi } from "../../lib/hooks";

type Row = { id: number; student_id: number; roll_number: string; name: string; section: string | null; status: string; source: string; n_frames: number; consistency: number; mean_quality: number; created_at: string };

export default function Enrollments() {
  const [status, setStatus] = useState<"pending" | "approved" | "all">("pending");
  const { data, loading, error, reload } = useApi<Row[]>(`/api/admin/enrollments?status=${status}`, 20000);
  const [msg, setMsg] = useState<string | null>(null);
  const act = async (url: string) => {
    setMsg(null);
    try {
      await api.post(url);
      await reload();
    } catch (e) {
      setMsg(errorText(e));
    }
  };
  return (
    <>
      <PageHeader
        title="Face enrollment"
        subtitle="Approve student self-enrollments. To enroll a student directly, open the student's page."
      />
      <Tabs
        value={status}
        onChange={setStatus}
        items={[
          { value: "pending", label: "Awaiting approval" },
          { value: "approved", label: "Approved" },
          { value: "all", label: "All templates" },
        ]}
      />
      {msg && <Alert>{msg}</Alert>}
      {error && <Alert>{error}</Alert>}
      <Card>
        {loading && !data ? (
          <Loading />
        ) : !data?.length ? (
          <Empty>{status === "pending" ? "No enrollments waiting for approval." : "No templates."}</Empty>
        ) : (
          <Table head={["Student", "Section", "Submitted", "Source", "Images", "Consistency", "Status", ""]}>
            {data.map((r) => (
              <tr key={r.id}>
                <Td>
                  <Link to={`/admin/students/${r.student_id}`} className="font-medium text-navy-700 hover:underline">
                    {r.roll_number}
                  </Link>{" "}
                  <span className="text-slate-600">{r.name}</span>
                </Td>
                <Td>{r.section ?? "—"}</Td>
                <Td className="whitespace-nowrap">{fmtTime(r.created_at, true)}</Td>
                <Td>{r.source.replace("_", " ")}</Td>
                <Td className="tabular">{r.n_frames}</Td>
                <Td className="tabular">{r.consistency.toFixed(2)}</Td>
                <Td>
                  <StatusBadge status={r.status} />
                </Td>
                <Td className="text-right whitespace-nowrap">
                  {r.status === "pending" && (
                    <>
                      <Button size="sm" onClick={() => act(`/api/admin/templates/${r.id}/approve`)}>
                        Approve
                      </Button>{" "}
                      <Button size="sm" variant="danger" onClick={() => act(`/api/admin/templates/${r.id}/revoke`)}>
                        Reject
                      </Button>
                    </>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
      <p className="mt-3 text-xs text-slate-500">
        Consistency is the lowest similarity between the enrollment images (higher means the images agree). Only an encrypted template is stored, never the photos.
      </p>
    </>
  );
}
