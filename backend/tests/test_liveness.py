import secrets

import pytest

from attendx.config import RUNTIME_DEFAULTS
from attendx.face.engine import FrameMetrics, metrics_from_landmarks
from attendx.liveness.challenge import ACTIONS, generate_steps, validate

RT = dict(RUNTIME_DEFAULTS)


def fm(yaw=0.0, pitch=0.5, blink=0.0, n=1, cx=0.5, cy=0.5, size=0.4):  # type: ignore[no-untyped-def]
    return FrameMetrics(n_faces=n, yaw=yaw, pitch=pitch, blink=blink, cx=cx, cy=cy, size=size)


def seq_for(steps, dt=100.0):  # type: ignore[no-untyped-def]
    ms = [fm()] * 4
    for st in steps:
        ms += {
            "turn_left": [fm(yaw=0.2)] * 3,
            "turn_right": [fm(yaw=-0.2)] * 3,
            "look_up": [fm(pitch=0.38)] * 3,
            "center": [fm()] * 3,
            "blink_twice": [fm(), fm(blink=0.8), fm(), fm(blink=0.8), fm(), fm()],
        }[st]
    ms += [fm()] * 3
    return [(1000 + i * dt, m) for i, m in enumerate(ms)]


@pytest.mark.parametrize(
    "steps",
    [["turn_left", "center"], ["turn_right", "center"], ["look_up", "center"], ["blink_twice"],
     ["turn_left", "center", "blink_twice", "look_up", "center"]],
)  # fmt: skip
def test_valid_sequences_pass(steps):
    res = validate(steps, seq_for(steps), RT)
    assert res.passed, res.reason
    assert res.completed_steps == steps
    assert res.start_frames and res.end_frames


def test_wrong_direction_fails():
    res = validate(["turn_left", "center"], seq_for(["turn_right", "center"]), RT)
    assert not res.passed and "LEFT" in res.reason


def test_wrong_order_fails():
    frames = seq_for(["blink_twice", "turn_left", "center"])
    res = validate(["turn_left", "center", "blink_twice"], frames, RT)
    assert not res.passed and "blink" in res.reason


def test_single_blink_is_not_enough():
    frames = [(1000 + i * 100, m) for i, m in enumerate([fm()] * 4 + [fm(blink=0.9), fm()] + [fm()] * 8)]
    res = validate(["blink_twice"], frames, RT)
    assert not res.passed and "1/2" in res.reason


def test_still_photo_fails_every_action():
    frames = [(1000 + i * 100, fm()) for i in range(40)]
    for action in ACTIONS:
        steps = [action, "center"] if action != "blink_twice" else [action]
        assert not validate(steps, frames, RT).passed


def test_second_face_fails():
    frames = seq_for(["blink_twice"])
    frames[6] = (frames[6][0], fm(n=2))
    res = validate(["blink_twice"], frames, RT)
    assert not res.passed and "more than one face" in res.reason


def test_face_missing_too_often_fails():
    frames = seq_for(["turn_left", "center"])
    frames = [(t, fm(n=0)) if i % 2 else (t, m) for i, (t, m) in enumerate(frames)]
    assert "left the frame" in validate(["turn_left", "center"], frames, RT).reason


def test_abrupt_face_jump_fails():
    frames = seq_for(["blink_twice"])
    frames[7] = (frames[7][0], fm(cx=0.9))
    assert "abruptly" in validate(["blink_twice"], frames, RT).reason


def test_timestamps_checked():
    steps = ["turn_left", "center"]
    frames = seq_for(steps)
    assert "not increasing" in validate(steps, list(reversed(frames)), RT).reason
    fast = seq_for(steps, dt=10.0)
    assert "implausibly fast" in validate(steps, fast, RT).reason
    gap = list(frames)
    gap[5] = (gap[5][0] + 5000, gap[5][1])
    assert not validate(steps, gap, RT).passed
    slow = seq_for(steps, dt=5000.0)
    assert not validate(steps, slow, RT).passed


def test_must_start_facing_camera():
    frames = [(t, fm(yaw=0.3) if i < 4 else m) for i, (t, m) in enumerate(seq_for(["blink_twice"]))]
    assert "looking straight" in validate(["blink_twice"], frames, RT).reason


def test_too_few_frames():
    assert "too few" in validate(["blink_twice"], seq_for([])[:3], RT).reason


def test_generate_steps_random_and_well_formed():
    rng = secrets.SystemRandom()
    seen = set()
    for _ in range(200):
        steps = generate_steps(3, rng)
        actions = [s for s in steps if s != "center"]
        assert len(actions) == 3 and len(set(actions)) == 3
        for i, s in enumerate(steps):
            if s in ("turn_left", "turn_right", "look_up"):
                assert steps[i + 1] == "center"
        seen.add(tuple(steps))
    assert len(seen) > 10  # unpredictable


def test_landmark_geometry_signs():
    import numpy as np

    lm = np.zeros((478, 2))
    lm[234], lm[454] = (0.3, 0.5), (0.7, 0.5)  # cheeks
    lm[33], lm[263] = (0.4, 0.4), (0.6, 0.4)  # eyes
    lm[152] = (0.5, 0.8)  # chin
    lm[1] = (0.5, 0.55)  # nose centred
    centre = metrics_from_landmarks(lm, 0.0)
    assert abs(centre.yaw) < 1e-9
    lm[1] = (0.6, 0.55)  # nose towards image right = subject's left (unmirrored frame)
    assert metrics_from_landmarks(lm, 0.0).yaw > 0.1
    lm[1] = (0.5, 0.47)  # nose closer to the eye line = looking up
    assert metrics_from_landmarks(lm, 0.0).pitch < centre.pitch


def test_blink_relative_to_resting_eyes():
    """Narrow/relaxed eyes rest above the global 'open' level (0.30): blinks must still count and
    frontal frames must still be found for identity."""
    rest, closed = 0.42, 0.85
    ms = [fm(blink=rest)] * 4 + [fm(blink=rest), fm(blink=closed), fm(blink=rest), fm(blink=closed),
                                 fm(blink=rest), fm(blink=rest)] + [fm(blink=rest)] * 4  # fmt: skip
    frames = [(1000 + i * 100, m) for i, m in enumerate(ms)]
    res = validate(["blink_twice"], frames, RT)
    assert res.passed, res.reason
    assert len(res.start_frames) == 2 and len(res.end_frames) == 2


def test_resting_eyes_cannot_fake_blinks():
    """A constant resting score never produces a blink event."""
    frames = [(1000 + i * 100, fm(blink=0.42)) for i in range(20)]
    assert not validate(["blink_twice"], frames, RT).passed
