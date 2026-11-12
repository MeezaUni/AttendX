"""Randomised active-liveness challenges and their server-side validation.

A challenge is a short random sequence of actions, e.g.
``["turn_left", "center", "blink_twice"]``. The phone streams the camera frames it captured
while the student performed it; the server re-measures every frame (MediaPipe Face Landmarker)
and checks, in order, that each action happened, that exactly one face was present throughout,
that the face moved continuously, and that the timing is plausible.

LIMITATION: this is a basic active-liveness check. It defeats printed photos and still images
on a screen, but a pre-recorded video of the right actions, a screen replay, a virtual camera or
a real-time face-swap injection can still pass it. See docs/security.md.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from attendx.face.engine import FrameMetrics

ACTIONS = ("turn_left", "turn_right", "look_up", "blink_twice")
HEAD_MOVES = ("turn_left", "turn_right", "look_up")
LABELS = {
    "turn_left": "Turn your head LEFT",
    "turn_right": "Turn your head RIGHT",
    "look_up": "Look UP",
    "blink_twice": "Blink TWICE (slowly)",
    "center": "Return to CENTRE",
}

MIN_FRAMES = 6
MAX_GAP_MS = 1500
MIN_DURATION_MS = 1000
MAX_NO_FACE_FRACTION = 0.25
MAX_JUMP = 0.25  # normalised face-centre jump between consecutive frames
SIZE_RATIO = (0.6, 1.67)
BASELINE_FRAMES = 3
MAX_BASELINE_YAW = 0.14
CONSECUTIVE = 2


def generate_steps(n_actions: int, rng: secrets.SystemRandom | None = None) -> list[str]:
    """Random, unpredictable step list. Every head movement is followed by a return to centre."""
    rng = rng or secrets.SystemRandom()
    n = max(1, min(n_actions, len(ACTIONS)))
    actions = rng.sample(ACTIONS, n)
    steps: list[str] = []
    for a in actions:
        steps.append(a)
        if a in HEAD_MOVES:
            steps.append("center")
    return steps


@dataclass
class LivenessResult:
    passed: bool
    reason: str
    completed_steps: list[str] = field(default_factory=list)
    start_frames: list[int] = field(default_factory=list)  # frontal frames before the actions
    end_frames: list[int] = field(default_factory=list)  # frontal frames after the actions
    details: dict[str, Any] = field(default_factory=dict)


def _fail(reason: str, done: list[str] | None = None, **details: Any) -> LivenessResult:
    return LivenessResult(False, reason, done or [], details=details)


def blink_thresholds(base_blink: float, rt: dict[str, Any]) -> tuple[float, float]:
    """(closed, open) thresholds relative to the person's own resting eyeBlink score, so that
    narrow or relaxed eyes (resting score above the configured 'open' level) still register
    blinks. Mirrored in frontend/src/lib/landmarks.ts."""
    closed = max(float(rt["blink_closed"]), base_blink + 0.25)
    opened = max(float(rt["blink_open"]), min(base_blink + 0.1, closed - 0.1))
    return min(closed, 0.95), opened


def check_timestamps(ts: list[float], ttl_ms: float) -> str | None:
    if len(ts) < MIN_FRAMES:
        return f"too few frames ({len(ts)})"
    for a, b in zip(ts, ts[1:], strict=False):
        if b <= a:
            return "frame timestamps are not increasing"
        if b - a > MAX_GAP_MS:
            return "the camera stream paused; try again"
    duration = ts[-1] - ts[0]
    if duration < MIN_DURATION_MS:
        return "challenge completed implausibly fast"
    if duration > ttl_ms:
        return "challenge took longer than allowed"
    return None


def validate(
    steps: list[str], frames: list[tuple[float, FrameMetrics]], rt: dict[str, Any]
) -> LivenessResult:
    """Check the step sequence against per-frame metrics (frames sorted by client time)."""
    ttl_ms = float(rt["challenge_ttl_seconds"]) * 1000.0
    problem = check_timestamps([t for t, _ in frames], ttl_ms)
    if problem:
        return _fail(problem)
    metrics = [m for _, m in frames]
    if any(m.n_faces > 1 for m in metrics):
        return _fail("more than one face appeared during the challenge")
    face_idx = [i for i, m in enumerate(metrics) if m.n_faces == 1]
    no_face = 1.0 - len(face_idx) / len(metrics)
    if no_face > MAX_NO_FACE_FRACTION:
        return _fail("your face left the frame too often", no_face_fraction=round(no_face, 2))
    if len(face_idx) < MIN_FRAMES:
        return _fail("face not visible in enough frames")
    for a, b in zip(face_idx, face_idx[1:], strict=False):
        ma, mb = metrics[a], metrics[b]
        jump = max(abs(ma.cx - mb.cx), abs(ma.cy - mb.cy))
        ratio = mb.size / max(ma.size, 1e-6)
        if jump > MAX_JUMP or not SIZE_RATIO[0] <= ratio <= SIZE_RATIO[1]:
            return _fail("the face changed abruptly between frames", frame=b)

    base = face_idx[:BASELINE_FRAMES]
    base_yaw = median(metrics[i].yaw for i in base)
    base_pitch = median(metrics[i].pitch for i in base)
    if abs(base_yaw) > MAX_BASELINE_YAW:
        return _fail("start by looking straight at the camera", base_yaw=round(base_yaw, 3))

    yd, pd = float(rt["yaw_delta"]), float(rt["pitch_delta"])
    base_blink = median(metrics[i].blink for i in base)
    closed_t, open_t = blink_thresholds(base_blink, rt)

    def dyaw(i: int) -> float:
        return metrics[i].yaw - base_yaw

    def dpitch(i: int) -> float:
        return metrics[i].pitch - base_pitch

    conds = {
        "turn_left": lambda i: dyaw(i) >= yd,
        "turn_right": lambda i: dyaw(i) <= -yd,
        "look_up": lambda i: dpitch(i) <= -pd,
        "center": lambda i: abs(dyaw(i)) <= yd / 2 and abs(dpitch(i)) <= pd,
    }

    pos = len(base)  # index into face_idx
    done: list[str] = []
    peaks: dict[str, float] = {}
    for step in steps:
        if step == "blink_twice":
            blinks, state, k = 0, "open", pos
            while k < len(face_idx) and blinks < 2:
                b = metrics[face_idx[k]].blink
                if state == "open" and b >= closed_t:
                    state = "closed"
                elif state == "closed" and b <= open_t:
                    state = "open"
                    blinks += 1
                k += 1
            if blinks < 2:
                return _fail(f"blink not detected ({blinks}/2)", done, step=step)
            pos = k
        elif step in conds:
            cond, run, k, found = conds[step], 0, pos, None
            while k < len(face_idx):
                run = run + 1 if cond(face_idx[k]) else 0
                if run >= CONSECUTIVE:
                    found = k
                    break
                k += 1
            if found is None:
                return _fail(f"did not detect: {LABELS[step]}", done, step=step)
            if step != "center":
                seg = face_idx[pos : found + 1]
                peaks[step] = round(
                    max(abs(dyaw(i)) if step != "look_up" else abs(dpitch(i)) for i in seg), 3
                )
            pos = found + 1
        else:
            return _fail(f"unknown step {step}")
        done.append(step)

    # frontal frames for identity: two from the baseline and two of the last frames facing the
    # camera, preferring the most open eyes (never empty when the face was frontal at the end)
    tail = sorted({i for i in face_idx[pos - CONSECUTIVE :] + face_idx[-4:] if abs(dyaw(i)) <= yd / 2})
    end = sorted(sorted(tail, key=lambda i: (metrics[i].blink > open_t, -i))[:2])
    start = sorted(sorted(base, key=lambda i: (metrics[i].blink > open_t, i))[:2])
    return LivenessResult(
        True,
        "challenge completed",
        done,
        start_frames=start,
        end_frames=end,
        details={
            "frames": len(metrics),
            "face_frames": len(face_idx),
            "baseline_yaw": round(base_yaw, 3),
            "baseline_pitch": round(base_pitch, 3),
            "peaks": peaks,
            "duration_ms": round(frames[-1][0] - frames[0][0]),
        },
    )
