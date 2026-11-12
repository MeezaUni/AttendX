"""Tests with the real SCRFD / AdaFace / MediaPipe models (skipped when models are absent).

Face images: set ATTENDX_TEST_FACES to a folder with sub-folders per identity (e.g. a few
synthetic DigiFace-1M identities). Such images are never committed. Without it, only the
model-loading, determinism and no-face behaviours are tested."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from attendx.config import PROJECT_DIR, RUNTIME_DEFAULTS
from attendx.face import spec

MODELS = Path(os.environ.get("ATTENDX_MODELS_DIR", PROJECT_DIR / "models"))
HAVE_MODELS = (MODELS / spec.ADAFACE_DIR / "model.safetensors").is_file() and (
    MODELS / spec.SCRFD_DIR / spec.SCRFD_FILE
).is_file()
pytestmark = [pytest.mark.models, pytest.mark.slow,
              pytest.mark.skipif(not HAVE_MODELS, reason="face models not installed")]  # fmt: skip
RT = dict(RUNTIME_DEFAULTS)


@pytest.fixture(scope="module")
def engine():
    from attendx.face.engine import RealFaceEngine

    e = RealFaceEngine(MODELS, "auto", verify_hashes=True)
    e.warmup()
    yield e
    e.close()


def test_engine_loads_with_pinned_hashes(engine):
    st = engine.status()
    assert st["detector_loaded"] and st["embedder_loaded"] and st["landmarker_loaded"]
    assert st["device"] in ("cpu", "cuda", "cuda:0")


def test_no_face_in_blank_or_noise(engine):
    blank = np.full((480, 640, 3), 128, np.uint8)
    assert engine.observe(blank, RT).problems == ["no face detected"]
    noise = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    assert not engine.observe(noise, RT).usable
    assert engine.frame_metrics(blank).n_faces == 0


def test_embedding_is_deterministic_and_normalised(engine):
    rng = np.random.default_rng(1)
    crop = rng.integers(0, 255, (1, 112, 112, 3), dtype=np.uint8)
    e1, n1 = engine._adaface().embed(crop)
    e2, n2 = engine._adaface().embed(crop)
    assert e1.shape == (1, 512)
    np.testing.assert_allclose(e1, e2, atol=1e-5)
    assert abs(np.linalg.norm(e1[0]) - 1) < 1e-4 and n1[0] > 0


def test_tampered_weights_are_refused(tmp_path):
    from attendx.face.adaface import ModelLoadError, load_adaface

    bad = tmp_path / "model.safetensors"
    bad.write_bytes(b"0" * 100)
    with pytest.raises(ModelLoadError):
        load_adaface(spec.ADAFACE_IR101, tmp_path)


FACES = os.environ.get("ATTENDX_TEST_FACES")


def _load_identities():  # type: ignore[no-untyped-def]
    import cv2

    root = Path(FACES)  # type: ignore[arg-type]
    out = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        imgs = []
        for f in sorted(d.iterdir())[:6]:
            bgr = cv2.imread(str(f))
            if bgr is None:
                continue
            # DigiFace crops are tight 112x112: pad so that the detector sees context
            bgr = cv2.copyMakeBorder(cv2.resize(bgr, (224, 224)), 128, 128, 128, 128, cv2.BORDER_REPLICATE)
            imgs.append(np.ascontiguousarray(bgr[:, :, ::-1]))
        if len(imgs) >= 4:
            out[d.name] = imgs
    return out


@pytest.mark.skipif(not FACES, reason="ATTENDX_TEST_FACES not set")
def test_identity_match_and_mismatch(engine):
    """Same identity -> higher cosine than different identities (behavioural check, NOT an
    accuracy measurement)."""
    from attendx.services.verification import build_template, cosine

    ids = _load_identities()
    assert len(ids) >= 2
    rt = {**RT, "min_feature_norm": 0.0, "min_sharpness": 0.0, "enroll_min_consistency": -1.0}
    names = list(ids)
    embs = {}
    for n in names:
        obs = [engine.observe(img, rt) for img in ids[n]]
        embs[n] = [o.embedding for o in obs if o.embedding is not None]
        assert len(embs[n]) >= 3, f"{n}: faces not detected"
    genuine, impostor = [], []
    for n in names:
        tpl, _ = build_template(embs[n][:3], rt)
        genuine += [cosine(e, tpl) for e in embs[n][3:]]
        for m in names:
            if m != n:
                impostor += [cosine(e, tpl) for e in embs[m][3:]]
    assert np.mean(genuine) > np.mean(impostor) + 0.2, (np.mean(genuine), np.mean(impostor))
