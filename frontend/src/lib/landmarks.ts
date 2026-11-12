// In-browser MediaPipe Face Landmarker, used ONLY to guide the student in real time (progress
// ticks, "move closer" hints). The server re-measures every uploaded frame and decides.
// The WASM runtime and the model are served from this origin (no third-party CDN).
import type { FaceLandmarker, FaceLandmarkerResult } from "@mediapipe/tasks-vision";

export type Metrics = { faces: number; yaw: number; pitch: number; blink: number; cx: number; cy: number; size: number };

let loading: Promise<FaceLandmarker> | null = null;

export function loadLandmarker(): Promise<FaceLandmarker> {
  loading ??= (async () => {
    const { FaceLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision");
    const fileset = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
    const opts = (delegate: "GPU" | "CPU") => ({
      baseOptions: { modelAssetPath: "/api/public/face_landmarker.task", delegate },
      runningMode: "VIDEO" as const,
      numFaces: 2,
      outputFaceBlendshapes: true,
    });
    try {
      return await FaceLandmarker.createFromOptions(fileset, opts("GPU"));
    } catch {
      return await FaceLandmarker.createFromOptions(fileset, opts("CPU"));
    }
  })();
  loading.catch(() => (loading = null));
  return loading;
}

// Same landmark indices and geometry as backend/attendx/face/engine.py::metrics_from_landmarks
const NOSE = 1, LCHEEK = 234, RCHEEK = 454, CHIN = 152, LEYE = 33, REYE = 263;

export function metricsFrom(res: FaceLandmarkerResult): Metrics {
  const faces = res.faceLandmarks?.length ?? 0;
  if (faces !== 1) return { faces, yaw: 0, pitch: 0, blink: 0, cx: 0, cy: 0, size: 0 };
  const lm = res.faceLandmarks[0];
  const left = Math.min(lm[LCHEEK].x, lm[RCHEEK].x);
  const right = Math.max(lm[LCHEEK].x, lm[RCHEEK].x);
  const yaw = (lm[NOSE].x - left) / Math.max(right - left, 1e-6) - 0.5;
  const eyeY = (lm[LEYE].y + lm[REYE].y) / 2;
  const pitch = (lm[NOSE].y - eyeY) / Math.max(lm[CHIN].y - eyeY, 1e-6);
  let blink = 0;
  const cats = res.faceBlendshapes?.[0]?.categories;
  if (cats) {
    const get = (n: string) => cats.find((c) => c.categoryName === n)?.score ?? 0;
    blink = (get("eyeBlinkLeft") + get("eyeBlinkRight")) / 2;
  }
  let minX = 1, maxX = 0, minY = 1, maxY = 0;
  for (const p of lm) {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
  }
  return { faces: 1, yaw, pitch, blink, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2, size: maxX - minX };
}

export type Guidance = { yaw_delta: number; pitch_delta: number; blink_closed: number; blink_open: number };

/** Incremental mirror of the server's step validation, for live progress only. Slightly stricter
 *  (3 consecutive frames instead of 2) so the client rarely reports success the server rejects. */
export class ChallengeTracker {
  steps: string[];
  index = 0;
  private g: Guidance;
  private base: Metrics[] = [];
  private run = 0;
  private blinkState: "open" | "closed" = "open";
  private blinks = 0;
  constructor(steps: string[], g: Guidance) {
    this.steps = steps;
    this.g = g;
  }
  get done() {
    return this.index >= this.steps.length;
  }
  get baselineReady() {
    return this.base.length >= 3;
  }
  get blinkCount() {
    return this.blinks;
  }
  update(m: Metrics): void {
    if (m.faces !== 1 || this.done) return;
    if (!this.baselineReady) {
      if (Math.abs(m.yaw) < 0.12) this.base.push(m);
      return;
    }
    const by = median(this.base.map((b) => b.yaw));
    const bp = median(this.base.map((b) => b.pitch));
    const dy = m.yaw - by, dp = m.pitch - bp;
    // blink thresholds relative to the resting score (same rule as the server)
    const bb = median(this.base.map((b) => b.blink));
    const closedT = Math.min(Math.max(this.g.blink_closed, bb + 0.25), 0.95);
    const openT = Math.max(this.g.blink_open, Math.min(bb + 0.1, closedT - 0.1));
    const step = this.steps[this.index];
    if (step === "blink_twice") {
      if (this.blinkState === "open" && m.blink >= closedT) this.blinkState = "closed";
      else if (this.blinkState === "closed" && m.blink <= openT) {
        this.blinkState = "open";
        this.blinks += 1;
      }
      if (this.blinks >= 2) this.advance();
      return;
    }
    const ok =
      step === "turn_left" ? dy >= this.g.yaw_delta * 1.1
      : step === "turn_right" ? dy <= -this.g.yaw_delta * 1.1
      : step === "look_up" ? dp <= -this.g.pitch_delta * 1.1
      : Math.abs(dy) <= this.g.yaw_delta / 2.5 && Math.abs(dp) <= this.g.pitch_delta * 0.8;
    this.run = ok ? this.run + 1 : 0;
    if (this.run >= 3) this.advance();
  }
  private advance() {
    this.index += 1;
    this.run = 0;
    this.blinks = 0;
    this.blinkState = "open";
  }
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const n = s.length;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}
