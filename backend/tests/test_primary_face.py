"""Classroom mode verifies the main central face and ignores students in the background."""

import sys
from types import SimpleNamespace

import numpy as np

from attendx.face.engine import FrameMetrics, RealFaceEngine, primary_index


def test_large_central_face_wins_over_small_background_faces():
    # 640x480 frame: the student holding the phone fills the centre; two people sit behind.
    boxes = [
        (20, 30, 110, 140),  # small, top-left (behind)
        (220, 120, 430, 400),  # large, centred (the student)
        (520, 40, 620, 150),  # small, top-right (behind)
    ]
    assert primary_index(boxes, 640, 480) == 1


def test_large_face_slightly_off_centre_still_beats_small_centred_face():
    boxes = [
        (290, 200, 350, 270),  # small but dead centre (someone far behind)
        (120, 100, 380, 420),  # large, a little left of centre (the student)
    ]
    assert primary_index(boxes, 640, 480) == 1


def test_liveness_uses_same_image_aspect_ratio_as_identity(tmp_path, monkeypatch):
    # In a landscape frame, scoring normalized boxes as a square chooses the other person.
    boxes = [(75, 125, 225, 275), (350, 140, 500, 260)]
    assert primary_index(boxes, 640, 480) == 0
    faces = [
        [SimpleNamespace(x=x0 / 640, y=y0 / 480), SimpleNamespace(x=x1 / 640, y=y1 / 480)] for x0, y0, x1, y1 in boxes
    ]
    result = SimpleNamespace(
        face_landmarks=faces,
        face_blendshapes=[
            [
                SimpleNamespace(category_name="eyeBlinkLeft", score=value),
                SimpleNamespace(category_name="eyeBlinkRight", score=value),
            ]
            for value in (0.1, 0.9)
        ],
    )
    monkeypatch.setitem(
        sys.modules,
        "mediapipe",
        SimpleNamespace(
            Image=lambda **kwargs: kwargs,
            ImageFormat=SimpleNamespace(SRGB=1),
        ),
    )
    monkeypatch.setattr(
        "attendx.face.engine.metrics_from_landmarks", lambda landmarks, blink: FrameMetrics(n_faces=1, blink=blink)
    )
    engine = RealFaceEngine(tmp_path, primary_face=True)
    engine._lm = SimpleNamespace(detect=lambda image: result)
    assert engine.frame_metrics(np.zeros((480, 640, 3), dtype=np.uint8)).blink == 0.1


def test_hotspot_tries_windows_choice_then_auto_then_explicit_bands():
    from attendx.faculty.network import BAND_2_4_GHZ, BAND_5_GHZ, BAND_AUTO, hotspot_band_order

    assert hotspot_band_order(BAND_AUTO) == [BAND_AUTO, BAND_2_4_GHZ, BAND_5_GHZ]
    assert hotspot_band_order(BAND_5_GHZ) == [BAND_5_GHZ, BAND_AUTO, BAND_2_4_GHZ]
    assert hotspot_band_order(None) == [BAND_AUTO, BAND_2_4_GHZ, BAND_5_GHZ]
