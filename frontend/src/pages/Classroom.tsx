import { useEffect, useRef, useState } from "react";
import { Alert, Button, Field, Input } from "../components/ui";
import { Logo } from "../components/Layouts";
import { errorText } from "../lib/api";
import { captureFrame, startCamera, stopCamera } from "../lib/camera";
import { CameraGuidance } from "../components/CameraGuidance";
import { drawQrFrame } from "../lib/qrZoom";

type Challenge = {
  status: string;
  steps: { action: string; label: string }[];
  ttl_seconds: number;
  message?: string;
};
export default function Classroom() {
  const [phase, setPhase] = useState("entry");
  const [error, setError] = useState("");
  const [roll, setRoll] = useState("");
  const [message, setMessage] = useState("");
  const [prompt, setPrompt] = useState("");
  const [action, setAction] = useState("center");
  const [zoom, setZoom] = useState(1);
  const [scanPurpose, setScanPurpose] = useState<"entry" | "submit">("submit");
  const [scanHint, setScanHint] = useState("");
  const [submissionPending, setSubmissionPending] = useState(false);
  const scanZoom = useRef(1);
  const token = useRef("");
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const alive = useRef(true);
  const scanner = useRef<{ stop: () => void; submitting: boolean } | null>(null);
  const entering = useRef(false);
  const entryGeneration = useRef(0);
  const lifetime = useRef(new AbortController());
  async function request<T>(route: string, body: unknown): Promise<T> {
    const headers: Record<string, string> = {
      "X-Requested-With": "attendx",
      "X-AttendX-Attempt": token.current,
    };
    if (!(body instanceof FormData))
      headers["Content-Type"] = "application/json";
    const r = await fetch(`/classroom/api/${route}`, {
      method: "POST",
      headers,
      body: body instanceof FormData ? body : JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "Classroom request failed. Ask faculty for assistance.",
      );
    return data as T;
  }
  useEffect(() => {
    alive.current = true;
    lifetime.current = new AbortController();
    const qr = window.location.hash.slice(1);
    window.history.replaceState(null, "", "/classroom");
    if (qr && !entering.current) {
      entering.current = true;
      const generation = entryGeneration.current;
      const current = () => alive.current && entryGeneration.current === generation;
      request<{ attempt_token: string }>("entry", { qr_token: qr })
        .then((r) => {
          if (!current()) return;
          token.current = r.attempt_token;
          setPhase("roll");
        })
        .catch((e) => {
          if (!current()) return;
          const reason = errorText(e);
          // Phones often open the link after the QR has rotated: offer the in-page scanner.
          setError(
            /expired or invalid|invalid QR/i.test(reason)
              ? "That QR changed before the page opened. Tap “Scan attendance QR” to scan it here."
              : reason,
          );
        });
    } else if (!qr && !entering.current)
      setMessage(
        "Connect to the faculty hotspot, then tap “Scan attendance QR” and point at the faculty screen.",
      );
    return () => {
      alive.current = false;
      lifetime.current.abort();
      stopCamera(stream.current);
      scanner.current?.stop();
      stopCamera(video.current?.srcObject as MediaStream | null);
    };
  }, []);
  const run = async () => {
    setError("");
    setPhase("camera");
    try {
      const signal = lifetime.current.signal;
      const acquired = await startCamera(video.current!, signal);
      if (signal.aborted) {
        stopCamera(acquired);
        return;
      }
      stream.current = acquired;
      if (!alive.current) return;
      // Issue only after the camera is ready, leaving the full challenge TTL for live capture.
      const ch = await request<Challenge>("roll", { roll_number: roll });
      if (!alive.current) return;
      if (ch.status !== "CHALLENGE") {
        stopCamera(stream.current);
        setPhase("review");
        setMessage(ch.message ?? "Ask faculty to mark attendance manually.");
        return;
      }
      setPhase("capturing");
      const blobs: Blob[] = [];
      const times: number[] = [];
      const began = performance.now();
      let tail = 0;
      const schedule: number[] = [];
      let acc = 1200;
      for (const s of ch.steps) {
        acc +=
          s.action === "blink_twice"
            ? 3500
            : s.action === "center"
              ? 2000
              : 2800;
        schedule.push(acc);
      }
      while (
        alive.current &&
        blobs.length < 190 &&
        performance.now() - began < 19000
      ) {
        const t = performance.now();
        // Timed instructions only: the phone runs no face model. The laptop verifies all frames.
        const index =
          t - began < 1200 ? -2 : schedule.findIndex((v) => t - began < v);
        setPrompt(
          index === -2
            ? "Look straight and hold still for the baseline"
            : (ch.steps[index]?.label ?? "Look straight and hold still"),
        );
        setAction(
          index >= 0 ? (ch.steps[index]?.action ?? "center") : "center",
        );
        blobs.push(await captureFrame(video.current!));
        times.push(Math.round(t - began));
        if (index === -1) tail++;
        if (tail >= 6) break;
        await new Promise((r) =>
          setTimeout(r, Math.max(0, 100 - (performance.now() - t))),
        );
      }
      stopCamera(stream.current);
      stream.current = null;
      if (!alive.current) return;
      setPhase("verifying");
      const fd = new FormData();
      blobs.forEach((b, i) => fd.append("frames", b, `frame${i}.jpg`));
      fd.append("timestamps", JSON.stringify(times));
      const result = await request<{ decision: string; reason: string }>(
        "verify",
        fd,
      );
      setMessage(result.reason);
      setPhase(result.decision === "match" ? "match" : "review");
    } catch (e) {
      stopCamera(stream.current);
      if (alive.current) {
        setError(errorText(e));
        setPhase("review");
      }
    }
  };
  // QR errors worth ignoring while the camera keeps scanning: the code rotated, was read a
  // moment too late, or is the same code already used for entry ("scan a fresh QR").
  const retryable = (text: string) =>
    /expired or invalid|invalid QR|fresh QR|current classroom QR/i.test(text);
  const scan = async (purpose: "entry" | "submit" = "submit") => {
    if (scanner.current?.submitting) return;
    // A manual scan supersedes any entry request still opening from the URL fragment.
    entryGeneration.current++;
    scanner.current?.stop();
    const cancellation = new AbortController();
    let acquired: MediaStream | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Register ownership before loading the reader or asking for camera permission, so
    // Cancel, unmount and a replacement scan also invalidate those pending operations.
    const controls = {
      submitting: false,
      stop: () => {
        cancellation.abort();
        clearTimeout(timer);
        stopCamera(acquired);
        if (stream.current === acquired) stream.current = null;
        if (scanner.current === controls) scanner.current = null;
      },
    };
    scanner.current = controls;
    const active = () => alive.current && !cancellation.signal.aborted && scanner.current === controls;
    if (purpose === "entry") {
      token.current = "";
      setRoll("");
    }
    setScanPurpose(purpose);
    setPhase("scanning");
    setError("");
    setMessage("");
    setScanHint("");
    setSubmissionPending(false);
    const fallback = purpose === "entry" ? "entry" : "match";
    try {
      const { BrowserQRCodeReader } = await import("@zxing/browser");
      if (!active()) return;
      const reader = new BrowserQRCodeReader();
      const target = video.current!;
      acquired = await startCamera(target, cancellation.signal, {
        facingMode: { ideal: "environment" },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      });
      if (!active()) {
        stopCamera(acquired);
        return;
      }
      stream.current = acquired;
      setZoom(1);
      scanZoom.current = 1;
      const canvas = document.createElement("canvas");
      const tried = new Set<string>();
      const decode = async () => {
        if (!active()) {
          controls.stop();
          return;
        }
        let text = "";
        if (target.videoWidth && target.videoHeight) {
          try {
            text = reader
              .decodeFromCanvas(drawQrFrame(target, canvas, scanZoom.current))
              .getText();
          } catch {
            /* No barcode in this frame; keep scanning the zoomed region. */
          }
        }
        let qr = "";
        if (text) {
          try {
            const url = new URL(text, location.origin);
            if (url.pathname === "/classroom" && url.hash) qr = url.hash.slice(1);
          } catch {
            /* not a URL */
          }
          if (!qr) setScanHint("That is not the AttendX attendance QR. Point at the faculty screen.");
        }
        if (!qr || tried.has(qr)) {
          timer = setTimeout(() => void decode(), 180);
          return;
        }
        tried.add(qr);
        try {
          if (purpose === "entry") {
            const r = await request<{ attempt_token: string }>("entry", { qr_token: qr });
            if (!active()) return;
            controls.stop();
            token.current = r.attempt_token;
            setPhase("roll");
          } else {
            // The server consumes MATCH when this POST succeeds. Keep its response even
            // if a Cancel click was queued before React disables the button.
            controls.submitting = true;
            setSubmissionPending(true);
            const result = await request<{ message: string }>("submit", { qr_token: qr });
            if (!active()) return;
            controls.submitting = false;
            setSubmissionPending(false);
            controls.stop();
            setMessage(result.message);
            setPhase("submitted");
          }
        } catch (e) {
          if (!active()) return;
          controls.submitting = false;
          setSubmissionPending(false);
          const reason = errorText(e);
          if (retryable(reason)) {
            // The QR rotated or is the one used for entry: keep the camera on and read the next code.
            setScanHint(
              purpose === "submit"
                ? "Waiting for the next QR… keep the camera on the faculty screen."
                : "QR changed — hold steady, reading the next one…",
            );
            timer = setTimeout(() => void decode(), 180);
            return;
          }
          controls.stop();
          setError(reason);
          setPhase(fallback);
        }
      };
      void decode();
    } catch (e) {
      if (active()) {
        controls.stop();
        setError(errorText(e));
        setPhase(fallback);
      }
    }
  };
  return (
    <main className="mx-auto max-w-md space-y-5 px-5 py-8">
      <Logo />
      <h1 className="text-2xl font-semibold">Classroom attendance</h1>
      <p className="text-sm text-slate-600">
        Stay connected to the faculty hotspot.
      </p>
      {error && <Alert>{error}</Alert>}
      {message && (
        <Alert
          tone={phase === "submitted" || phase === "match" ? "green" : "blue"}
        >
          {message}
        </Alert>
      )}
      <div
        className={`camera-shell relative aspect-[3/4] w-full overflow-hidden rounded-xl bg-slate-900 ${["camera", "capturing", "scanning"].includes(phase) ? "" : "hidden"}`}
      >
        <video
          ref={video}
          playsInline
          muted
          className={`absolute inset-0 h-full w-full object-cover ${phase !== "scanning" ? "-scale-x-100" : ""}`}
          style={
            phase === "scanning" ? { transform: `scale(${zoom})` } : undefined
          }
        />
        <CameraGuidance
          action={action}
          prompt={
            phase === "scanning"
              ? scanHint ||
                (scanPurpose === "entry"
                  ? "Point at the attendance QR on the faculty screen. Use zoom if far away."
                  : "Scan a fresh QR. Use zoom if you are far away.")
              : prompt || "Look straight — opening your camera…"
          }
          scanning={phase === "scanning"}
        />
      </div>
      {phase === "scanning" && (
        <div className="space-y-2 rounded-xl border border-slate-200 bg-white p-4">
          <label
            htmlFor="qr-zoom"
            className="flex justify-between text-sm font-semibold"
          >
            <span>QR camera zoom</span>
            <span>{zoom.toFixed(1)}×</span>
          </label>
          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              aria-label="Zoom out"
              disabled={zoom <= 1}
              onClick={() => {
                const value = Math.max(1, zoom - 0.5);
                setZoom(value);
                scanZoom.current = value;
              }}
            >
              −
            </Button>
            <input
              id="qr-zoom"
              type="range"
              min="1"
              max="4"
              step="0.1"
              value={zoom}
              className="min-w-0 flex-1"
              onChange={(e) => {
                const value = Number(e.target.value);
                setZoom(value);
                scanZoom.current = value;
              }}
            />
            <Button
              variant="secondary"
              aria-label="Zoom in"
              disabled={zoom >= 4}
              onClick={() => {
                const value = Math.min(4, zoom + 0.5);
                setZoom(value);
                scanZoom.current = value;
              }}
            >
              +
            </Button>
          </div>
        </div>
      )}
      {phase === "roll" && (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            void run();
          }}
        >
          <Field label="Enter your university roll number">
            {(id) => (
              <Input
                id={id}
                required
                maxLength={32}
                autoCapitalize="characters"
                value={roll}
                onChange={(e) => setRoll(e.target.value)}
              />
            )}
          </Field>
          <p className="text-sm">
            Follow the random live camera instructions, then scan a fresh
            classroom QR. Faculty gives the final attendance decision.
          </p>
          <Button type="submit" className="w-full">
            Open camera and begin
          </Button>
        </form>
      )}
      {phase === "verifying" && (
        <p aria-live="polite">
          Faculty laptop is checking liveness and your face…
        </p>
      )}
      {phase === "entry" && (
        <Button className="w-full" onClick={() => void scan("entry")}>
          Scan attendance QR
        </Button>
      )}
      {phase === "scanning" && (
        <Button
          variant="secondary"
          className="w-full"
          disabled={submissionPending}
          onClick={() => {
            if (scanner.current?.submitting) return;
            scanner.current?.stop();
            scanner.current = null;
            setPhase(scanPurpose === "entry" ? "entry" : "match");
          }}
        >
          Cancel scanning
        </Button>
      )}
      {phase === "match" && (
        <Button className="w-full" onClick={() => void scan("submit")}>
          Scan fresh QR to submit
        </Button>
      )}
      {phase === "review" && (
        <>
          <Alert tone="amber">
            Ask faculty to check you in person and mark attendance manually. A
            failed or incomplete check does not mark you absent.
          </Alert>
          <Button className="w-full" variant="secondary" onClick={() => void scan("entry")}>
            Try again: scan a new attendance QR
          </Button>
        </>
      )}
      {phase === "submitted" && (
        <p className="font-medium">
          Awaiting faculty confirmation. This submission is not yet final
          university attendance.
        </p>
      )}
    </main>
  );
}
