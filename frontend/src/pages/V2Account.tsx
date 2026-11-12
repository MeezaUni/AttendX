import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Logo } from "../components/Layouts";
import { Alert, Button, Field, Input } from "../components/ui";
import { api, errorText } from "../lib/api";

export default function V2Account() {
  const path = useLocation().pathname;
  const activating = path === "/activate";
  const forgot = path === "/forgot-password";
  const [token] = useState(() => window.location.hash.slice(1));
  const [details, setDetails] = useState<{
    name: string;
    roll_number: string;
    email: string;
    consent_notice: string;
  } | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    window.history.replaceState(null, "", path);
    if (activating && token)
      api
        .post<typeof details>("/api/v2/auth/activation-info", { token })
        .then(setDetails)
        .catch((e) => setError(errorText(e)));
  }, [activating, path, token]);
  return (
    <main className="mx-auto max-w-md space-y-6 px-5 py-12">
      <Logo />
      <h1 className="text-2xl font-semibold">
        {activating
          ? "Activate your student account"
          : forgot
            ? "Recover your account"
            : "Choose a new password"}
      </h1>
      {details && (
        <div className="space-y-2 border-l-4 border-navy-700 pl-4">
          <p className="font-medium">{details.name}</p>
          <p>{details.roll_number}</p>
          <p className="text-sm text-slate-600">{details.email}</p>
          <p className="text-sm">{details.consent_notice}</p>
        </div>
      )}
      {error && <Alert>{error}</Alert>}
      {message && <Alert tone="green">{message}</Alert>}
      {!message && (
        <form
          className="space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setError("");
            setBusy(true);
            try {
              if (forgot) {
                const r = await api.post<{ message: string }>(
                  "/api/v2/auth/forgot-password",
                  { email },
                );
                setMessage(r.message);
              } else {
                if (!token)
                  throw new Error(
                    "Open the complete single-use link from your university email.",
                  );
                if (password !== confirm)
                  throw new Error("Passwords must match.");
                await api.post(
                  `/api/v2/auth/${activating ? "activate" : "reset-password"}`,
                  { token, password },
                );
                setPassword("");
                setConfirm("");
                setMessage(
                  activating
                    ? "Account activated. Sign in to capture your three enrollment samples."
                    : "Password changed. Sign in with your new password.",
                );
              }
            } catch (err) {
              setError(errorText(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          {forgot ? (
            <Field label="Registered university email">
              {(id) => (
                <Input
                  id={id}
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                />
              )}
            </Field>
          ) : (
            <>
              <Field
                label="New password"
                hint="At least 8 characters with letters and numbers or symbols."
              >
                {(id) => (
                  <Input
                    id={id}
                    type="password"
                    minLength={8}
                    maxLength={128}
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                )}
              </Field>
              <Field label="Confirm password">
                {(id) => (
                  <Input
                    id={id}
                    type="password"
                    required
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    autoComplete="new-password"
                  />
                )}
              </Field>
            </>
          )}
          <Button type="submit" busy={busy}>
            {forgot
              ? "Send reset link"
              : activating
                ? "Activate account"
                : "Save new password"}
          </Button>
        </form>
      )}
      <Link className="block text-navy-700 underline" to="/login">
        Sign in to central portal
      </Link>
    </main>
  );
}
