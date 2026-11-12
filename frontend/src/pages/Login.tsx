import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Logo } from "../components/Layouts";
import { Alert, Button, Field, Input } from "../components/ui";
import { errorText } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { user, login, loading } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!loading && user) return <Navigate to={user.must_change_password ? "/change-password" : user.role === "admin" ? "/admin" : user.role === "faculty" ? "/faculty" : "/"} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const u = await login(username.trim(), password);
      nav(u.must_change_password ? "/change-password" : u.role === "admin" ? "/admin" : u.role === "faculty" ? "/faculty" : "/", { replace: true });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col bg-gradient-to-b from-navy-50 to-canvas">
      <div className="flex flex-1 flex-col items-center justify-center px-4 py-10">
        <div className="mb-8 text-center">
          <div className="flex justify-center">
            <Logo />
          </div>
          <p className="mt-2 text-sm text-slate-500">Central university portal</p>
        </div>
        <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-slate-900">Sign in</h1>
          {error && <Alert>{error}</Alert>}
          <Field label="Username or roll number">
            {(id) => <Input id={id} autoComplete="username" autoCapitalize="characters" value={username} onChange={(e) => setUsername(e.target.value)} required />}
          </Field>
          <Field label="Password">
            {(id) => <Input id={id} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />}
          </Field>
          <Button type="submit" className="w-full" size="lg" busy={busy}>
            Sign in
          </Button>
          <Link className="block text-center text-sm text-navy-700 underline" to="/forgot-password">Forgot password?</Link>
        </form>
        <p className="mt-6 max-w-sm text-center text-xs leading-relaxed text-slate-500">
          University prototype. Face data is used only to verify your own attendance and can be deleted on request.
        </p>
      </div>
    </div>
  );
}
