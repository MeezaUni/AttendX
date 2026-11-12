import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Logo } from "../components/Layouts";
import { Alert, Button, Field, Input } from "../components/ui";
import { api, errorText } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function ChangePassword() {
  const { user, loading, refresh } = useAuth();
  const nav = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!loading && !user) return <Navigate to="/login" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== repeat) return setError("The new passwords do not match.");
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/auth/change-password", { current_password: current, new_password: next });
      await refresh();
      nav(user?.role === "admin" ? "/admin" : "/", { replace: true });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-canvas px-4 py-10">
      <div className="mb-6">
        <Logo />
      </div>
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-lg font-semibold text-slate-900">Choose a new password</h1>
        {user?.must_change_password && <Alert tone="blue">Your account uses a temporary password. Set your own before continuing.</Alert>}
        {error && <Alert>{error}</Alert>}
        <Field label="Current password">
          {(id) => <Input id={id} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />}
        </Field>
        <Field label="New password" hint="At least 8 characters, mixing letters with numbers or symbols.">
          {(id) => <Input id={id} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} />}
        </Field>
        <Field label="Repeat new password">
          {(id) => <Input id={id} type="password" autoComplete="new-password" value={repeat} onChange={(e) => setRepeat(e.target.value)} required />}
        </Field>
        <Button type="submit" className="w-full" size="lg" busy={busy}>
          Save password
        </Button>
      </form>
    </div>
  );
}
