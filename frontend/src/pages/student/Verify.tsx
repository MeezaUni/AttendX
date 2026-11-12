import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { Alert, Button, Spinner, cx } from "../../components/ui";
import { api, errorText } from "../../lib/api";
import { cameraErrorText, captureFrame, startCamera, stopCamera } from "../../lib/camera";
import { fmtTime } from "../../lib/hooks";
import { ChallengeTracker, loadLandmarker, metricsFrom, type Guidance, type Metrics } from "../../lib/landmarks";
import type { StudentSession } from "./Today";

type Challenge = {
  challenge_id: string;
  steps: { action: string; label: string }[];
  ttl_seconds: number;
  guidance: Guidance;
};
type Result = {
  decision: "match" | "non_match" | "abstain" | "rejected";
  reason: string;
  marked: boolean;
  course_code?: string;
  verified_at?: string | null;
  attempts_left: number;
};
type Phase = "intro" | "starting" | "preview" | "challenge" | "verifying" | "result" | "error";

const FPS = 10;
const MAX_FRAMES = 190;
const TAIL_FRAMES = 6;
const TIMED_STEP_MS: Record<string, number> = { blink_twice: 3500, center: 2000, default: 2800 };

function faceHint(m: Metrics | null, ready: boolean): { ok: boolean; text: string } {
  if (!ready) return { ok: true, text: "Centre your face in the oval" };
  if (!m || m.faces === 0) return { ok: false, text: "No face found: centre your face in the oval" };
  if (m.faces > 1) return { ok: false, text: "Only you should be in the frame" };
  if (m.size < 0.28) return { ok: false, text: "Move a little closer" };
  if (m.size > 0.8) return { ok: false, text: "Move a little further away" };
  if (Math.abs(m.cx - 0.5) > 0.2 || Math.abs(m.cy - 0.5) > 0.22) return { ok: false, text: "Centre your face in the oval" };
  if (Math.abs(m.yaw) > 0.12) return { ok: false, text: "Look straight at the camera" };
  return { ok: true, text: "Good, hold still" };
}

export default function Verify() {
  const { sessionId } = useParams();
  const loc = useLocation();
  const nav = useNavigate();
  const session = (loc.state as { session?: StudentSession } | null)?.session;
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const landmarker = useRef<Awaited<ReturnType<typeof loadLandmarker>> | null>(null);
  const lastTs = useRef(0);
  const cancelled = useRef(false);
  const [phase, setPhase] = useState<Phase>("intro");
  const [error, setError] = useState<string | null>(null);
  const [lmState, setLmState] = useState<"loading" | "ready" | "failed">("loading");
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [steps, setSteps] = useState<Challenge["steps"]>([]);
  const [stepIndex, setStepIndex] = useState(0);
  const [blinks, setBlinks] = useState(0);
  const [result, setResult] = useState<Result | null>(null);
  const [allowAnyway, setAllowAnyway] = useState(false);

  // the in-browser guide is only advisory: never block the student for long on it
  useEffect(() => {
    if (phase !== "preview") return;
    setAllowAnyway(false);
    const id = window.setTimeout(() => setAllowAnyway(true), 8000);
    return () => window.clearTimeout(id);
  }, [phase]);

  useEffect(() => {
    loadLandmarker()
      .then((l) => {
        landmarker.current = l;
        setLmState("ready");
      })
      .catch(() => setLmState("failed"));
    return () => {
      cancelled.current = true;
      stopCamera(stream.current);
    };
  }, []);

  const detect = useCallback((): Metrics | null => {
    const v = video.current, l = landmarker.current;
    if (!v || !l || v.readyState < 2) return null;
    let ts = performance.now();
    if (ts <= lastTs.current) ts = lastTs.current + 1;
    lastTs.current = ts;
    try {
      return metricsFrom(l.detectForVideo(v, ts));
    } catch {
      return null;
    }
  }, []);

  // live guidance while previewing
  useEffect(() => {
    if (phase !== "preview" || lmState !== "ready") return;
    const id = window.setInterval(() => setMetrics(detect()), 125);
    return () => window.clearInterval(id);
  }, [phase, lmState, detect]);

  const startCam = async () => {
    setError(null);
    setPhase("starting");
    try {
      stream.current = await startCamera(video.current!);
      setPhase("preview");
    } catch (e) {
      setError(cameraErrorText(e));
      setPhase("error");
    }
  };

  const run = async () => {
    setError(null);
    let ch: Challenge;
    try {
      ch = await api.post<Challenge>("/api/student/attendance/challenge", { session_id: Number(sessionId) });
    } catch (e) {
      setError(errorText(e));
      setPhase("error");
      return;
    }
    setSteps(ch.steps);
    setStepIndex(0);
    setBlinks(0);
    setPhase("challenge");
    const actions = ch.steps.map((s) => s.action);
    const tracker = new ChallengeTracker(actions, ch.guidance);
    const useLm = lmState === "ready";
    const frames: Promise<Blob>[] = [];
    const times: number[] = [];
    const t0 = performance.now();
    const deadline = t0 + Math.min(ch.ttl_seconds * 1000 - 12000, 19000);
    // timed fallback when the in-browser landmarker is unavailable: the server still validates
    const schedule: number[] = [];
    let acc = 1200;
    for (const a of actions) {
      acc += TIMED_STEP_MS[a] ?? TIMED_STEP_MS.default;
      schedule.push(acc);
    }
    let tail = 0;
    await new Promise<void>((resolve) => {
      const tick = () => {
        if (cancelled.current) return resolve();
        const now = performance.now();
        const v = video.current!;
        frames.push(captureFrame(v));
        times.push(Math.round(now - t0));
        if (useLm) {
          const m = detect();
          if (m) tracker.update(m);
          setStepIndex(tracker.index);
          setBlinks(tracker.blinkCount);
        } else {
          const idx = schedule.findIndex((t) => now - t0 < t);
          setStepIndex(idx === -1 ? actions.length : idx);
        }
        const done = useLm ? tracker.done : now - t0 >= schedule[schedule.length - 1];
        if (done) tail += 1;
        if (tail >= TAIL_FRAMES || frames.length >= MAX_FRAMES || now > deadline) return resolve();
        window.setTimeout(tick, Math.max(0, 1000 / FPS - (performance.now() - now)));
      };
      tick();
    });
    if (cancelled.current) return;
    setPhase("verifying");
    stopCamera(stream.current);
    stream.current = null;
    try {
      const blobs = await Promise.all(frames);
      const fd = new FormData();
      blobs.forEach((b, i) => fd.append("frames", b, `f${i}.jpg`));
      fd.append("timestamps", JSON.stringify(times));
      const r = await api.post<Result>(`/api/student/attendance/challenge/${ch.challenge_id}/submit`, fd);
      setResult(r);
      setPhase("result");
    } catch (e) {
      setError(errorText(e));
      setPhase("error");
    }
  };

  const hint = faceHint(metrics, lmState === "ready");
  const showVideo = phase === "starting" || phase === "preview" || phase === "challenge";
  const current = steps[stepIndex];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Link to="/" className="text-sm font-medium text-navy-700">
          ← Back
        </Link>
        {session && (
          <p className="text-sm text-slate-500">
            Window {session.open}–{session.close}
          </p>
        )}
      </div>
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{session ? `${session.course_code} attendance` : "Mark attendance"}</h1>
        {session && <p className="text-sm text-slate-500">{session.course_name}</p>}
      </div>

      <div className={cx("relative mx-auto aspect-[3/4] w-full max-w-sm overflow-hidden rounded-2xl bg-slate-900", !showVideo && "hidden")}>
        <video ref={video} className="h-full w-full -scale-x-100 object-cover" playsInline muted />
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div
            className={cx(
              "h-[58%] w-[66%] rounded-[50%] border-[3px] transition-colors",
              phase === "challenge" ? "border-navy-300" : hint.ok ? "border-emerald-400" : "border-white/60",
            )}
          />
        </div>
        {phase === "preview" && (
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-4 text-center text-sm font-medium text-white" aria-live="polite">
            {hint.text}
          </div>
        )}
        {phase === "challenge" && current && (
          <div className="absolute inset-x-0 top-0 bg-gradient-to-b from-black/75 to-transparent p-4 text-center" aria-live="assertive">
            <p className="text-xs font-medium uppercase tracking-wide text-navy-200">
              Step {Math.min(stepIndex + 1, steps.length)} of {steps.length}
            </p>
            <p className="mt-1 text-xl font-semibold text-white">{current.label}</p>
            {current.action === "blink_twice" && lmState === "ready" && <p className="mt-1 text-sm text-white/80">Blinks seen: {blinks}/2</p>}
          </div>
        )}
        {phase === "challenge" && stepIndex >= steps.length && (
          <div className="absolute inset-x-0 top-0 bg-gradient-to-b from-black/75 to-transparent p-4 text-center text-lg font-semibold text-white">
            Look at the camera…
          </div>
        )}
      </div>

      {phase === "challenge" && (
        <ol className="flex flex-wrap justify-center gap-2" aria-label="Challenge steps">
          {steps.map((s, i) => (
            <li
              key={i}
              className={cx(
                "rounded-full px-3 py-1 text-xs font-medium",
                i < stepIndex ? "bg-emerald-100 text-emerald-800" : i === stepIndex ? "bg-navy-700 text-white" : "bg-slate-100 text-slate-500",
              )}
            >
              {i < stepIndex ? "✓ " : ""}
              {s.label.replace(/ \(slowly\)/, "")}
            </li>
          ))}
        </ol>
      )}

      {phase === "intro" && (
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="font-semibold text-slate-900">How it works</h2>
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-slate-600">
            <li>Your front camera opens. Hold the phone at eye level in good light.</li>
            <li>Follow a short random challenge, such as turning your head or blinking.</li>
            <li>Your face is compared with your own enrollment, and attendance is recorded.</li>
          </ol>
          <p className="text-xs text-slate-500">
            Frames are sent only to the AttendX server for this check and are not stored. Photo uploads are not accepted.
          </p>
          <Button size="lg" className="w-full" onClick={startCam}>
            Open camera
          </Button>
        </div>
      )}

      {phase === "preview" && (
        <div className="space-y-2">
          <Button size="lg" className="w-full" onClick={run} disabled={!allowAnyway && (lmState === "loading" || (lmState === "ready" && !hint.ok))}>
            {lmState === "loading" ? "Preparing face guide…" : "Start verification"}
          </Button>
          {lmState === "failed" && (
            <p className="text-center text-xs text-slate-500">
              Live guidance is unavailable on this browser. Follow each instruction while it is shown; the server still checks every step.
            </p>
          )}
        </div>
      )}

      {phase === "verifying" && (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-slate-200 bg-white p-8 text-navy-700">
          <Spinner className="h-8 w-8" />
          <p className="font-medium">Verifying…</p>
          <p className="text-sm text-slate-500">Checking the challenge and your face</p>
        </div>
      )}

      {phase === "result" && result && <ResultCard result={result} onRetry={() => setPhase("intro")} onDone={() => nav("/")} />}

      {phase === "error" && (
        <div className="space-y-3">
          <Alert>{error}</Alert>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => nav("/")}>
              Back to classes
            </Button>
            <Button onClick={() => setPhase("intro")}>Try again</Button>
          </div>
        </div>
      )}
    </div>
  );
}

function ResultCard({ result, onRetry, onDone }: { result: Result; onRetry: () => void; onDone: () => void }) {
  if (result.marked) {
    return (
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-6 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-600 text-white">
          <svg viewBox="0 0 24 24" className="h-8 w-8" fill="none" stroke="currentColor" strokeWidth="3">
            <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <h2 className="mt-3 text-lg font-semibold text-emerald-900">Attendance recorded</h2>
        <p className="mt-1 text-sm text-emerald-800">
          {result.course_code} · present at {fmtTime(result.verified_at)}
        </p>
        <Button className="mt-5 w-full" size="lg" onClick={onDone}>
          Done
        </Button>
      </div>
    );
  }
  const title =
    result.decision === "non_match" ? "Face did not match" : result.decision === "abstain" ? "Could not verify" : "Check not passed";
  return (
    <div className="space-y-4 rounded-2xl border border-amber-200 bg-amber-50 p-6">
      <div>
        <h2 className="text-lg font-semibold text-amber-900">{title}</h2>
        <p className="mt-1 text-sm text-amber-900">{result.reason}.</p>
        <p className="mt-2 text-sm text-amber-800">
          Attendance was <strong>not</strong> recorded. Attempts left for this class: {result.attempts_left}.
        </p>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-sm text-amber-900/90">
        <li>Face a light source; avoid strong backlight.</li>
        <li>Keep your whole face inside the oval and remove sunglasses or a mask.</li>
        <li>Make each movement clearly, then return to the centre.</li>
      </ul>
      <div className="flex gap-2">
        <Button variant="secondary" className="flex-1" onClick={onDone}>
          Back
        </Button>
        {result.attempts_left > 0 && (
          <Button className="flex-1" onClick={onRetry}>
            Try again
          </Button>
        )}
      </div>
    </div>
  );
}
