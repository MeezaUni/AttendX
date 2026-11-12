"""Face engine: SCRFD detection + 5-point alignment + AdaFace embedding (identity), and MediaPipe
Face Landmarker metrics (liveness). Images are processed in memory only and never logged.

``FaceEngine`` is the protocol the API depends on; ``RealFaceEngine`` loads the models lazily,
``FakeFaceEngine`` (tests) returns deterministic synthetic observations.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from attendx.face import spec
from attendx.face.align import align_to_template, alignment_residual

U8 = NDArray[np.uint8]


@dataclass
class FaceObservation:
    """Identity-path result for one image."""

    n_faces: int
    det_score: float = 0.0
    residual: float = 0.0
    face_px: float = 0.0
    sharpness: float = 0.0
    brightness: float = 0.0
    crop: U8 | None = None  # 112x112 RGB aligned crop of the single face
    embedding: NDArray[np.float32] | None = None
    feature_norm: float = 0.0
    problems: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.problems and self.embedding is not None

    def summary(self) -> dict[str, Any]:
        return {
            "n_faces": self.n_faces,
            "det_score": round(self.det_score, 3),
            "residual": round(self.residual, 2),
            "face_px": round(self.face_px, 1),
            "sharpness": round(self.sharpness, 1),
            "brightness": round(self.brightness, 1),
            "feature_norm": round(self.feature_norm, 2),
            "problems": self.problems,
        }


@dataclass
class FrameMetrics:
    """Liveness-path result for one frame (MediaPipe Face Landmarker)."""

    n_faces: int
    yaw: float = 0.0  # >0: nose towards image right = subject's LEFT on an unmirrored frame
    pitch: float = 0.0  # nose height ratio; decreases when the subject looks UP
    blink: float = 0.0  # mean eyeBlink blendshape score (0 open .. 1 closed)
    cx: float = 0.0  # face centre, normalised [0,1]
    cy: float = 0.0
    size: float = 0.0  # face width, normalised


class FaceEngine(Protocol):
    model_id: str

    def observe(self, rgb: U8, rt: dict[str, Any]) -> FaceObservation: ...

    def frame_metrics(self, rgb: U8) -> FrameMetrics: ...

    def status(self) -> dict[str, Any]: ...


def decode_image(data: bytes, max_side: int = 2048) -> U8:
    """Decode JPEG/PNG/WEBP bytes to RGB uint8 (in memory). Raises ValueError when invalid."""
    import cv2

    if not data:
        raise ValueError("empty image")
    arr = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("not a decodable image")
    h, w = bgr.shape[:2]
    if min(h, w) < 64:
        raise ValueError("image too small")
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        bgr = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return np.ascontiguousarray(bgr[:, :, ::-1])


def crop_quality(crop: U8) -> tuple[float, float]:
    """(sharpness = Laplacian variance, brightness = mean grey) of an aligned crop."""
    import cv2

    grey = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(grey, cv2.CV_64F).var()), float(grey.mean())


def quality_problems(obs: FaceObservation, rt: dict[str, Any], *, check_norm: bool) -> list[str]:
    p: list[str] = []
    if obs.n_faces == 0:
        return ["no face detected"]
    if obs.n_faces > 1:
        return [f"{obs.n_faces} faces visible; only you should be in the frame"]
    if obs.det_score < rt["det_min_score"]:
        p.append("face not clearly visible")
    if obs.residual > rt["max_alignment_residual"]:
        p.append("face is turned or partly hidden")
    if obs.face_px < rt["min_face_px"]:
        p.append("face too small; move closer")
    lo, hi = rt["brightness_range"]
    if obs.brightness < lo:
        p.append("too dark")
    elif obs.brightness > hi:
        p.append("too bright")
    if obs.sharpness < rt["min_sharpness"]:
        p.append("image is blurry; hold still")
    if check_norm and obs.feature_norm < rt["min_feature_norm"]:
        p.append("low face-image quality")
    return p


# MediaPipe face-mesh landmark indices used for pose
_NOSE, _LCHEEK, _RCHEEK, _CHIN = 1, 234, 454, 152
_LEYE, _REYE = 33, 263


def metrics_from_landmarks(lm: NDArray[np.float64], blink: float) -> FrameMetrics:
    """Geometric pose ratios from normalised (x, y) face-mesh landmarks (image coordinates)."""
    nose, lc, rc, chin = lm[_NOSE], lm[_LCHEEK], lm[_RCHEEK], lm[_CHIN]
    left_x, right_x = min(lc[0], rc[0]), max(lc[0], rc[0])
    width = max(right_x - left_x, 1e-6)
    yaw = (nose[0] - left_x) / width - 0.5
    eye_y = (lm[_LEYE][1] + lm[_REYE][1]) / 2.0
    pitch = (nose[1] - eye_y) / max(chin[1] - eye_y, 1e-6)
    xs, ys = lm[:, 0], lm[:, 1]
    return FrameMetrics(
        n_faces=1,
        yaw=float(yaw),
        pitch=float(pitch),
        blink=float(blink),
        cx=float((xs.min() + xs.max()) / 2),
        cy=float((ys.min() + ys.max()) / 2),
        size=float(xs.max() - xs.min()),
    )


class RealFaceEngine:
    model_id = spec.ADAFACE_IR101.backbone_id

    def __init__(self, models_dir: Path, device: str = "auto", verify_hashes: bool = True):
        self.models_dir = models_dir
        self.device_pref = device
        self.verify_hashes = verify_hashes
        self._det: Any = None
        self._ada: Any = None
        self._lm: Any = None
        self._lock = threading.Lock()  # models are not re-entrant across threads
        self.load_error: str | None = None

    # ------------------------------------------------------------------ lazy model loading
    def _detector(self) -> Any:
        if self._det is None:
            from attendx.face.adaface import sha256_file
            from attendx.face.scrfd import SCRFDDetector

            path = self.models_dir / spec.SCRFD_DIR / spec.SCRFD_FILE
            if not path.is_file():
                raise FileNotFoundError(f"SCRFD model missing: {path}")
            if self.verify_hashes and sha256_file(path) != spec.SCRFD_SHA256:
                raise RuntimeError("SCRFD weights differ from the pinned SHA-256")
            self._det = SCRFDDetector(path, det_thresh=0.5, nms_thresh=0.4)
        return self._det

    def _adaface(self) -> Any:
        if self._ada is None:
            from attendx.face.adaface import AdaFaceExtractor

            self._ada = AdaFaceExtractor(
                spec.ADAFACE_IR101,
                self.models_dir / spec.ADAFACE_DIR,
                device=self.device_pref,
                verify_hash=self.verify_hashes,
            )
        return self._ada

    def _landmarker(self) -> Any:
        if self._lm is None:
            from mediapipe.tasks.python import BaseOptions, vision

            path = self.models_dir / spec.MEDIAPIPE_DIR / spec.MEDIAPIPE_FILE
            if not path.is_file():
                raise FileNotFoundError(f"MediaPipe model missing: {path}")
            opts = vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_buffer=path.read_bytes()),
                num_faces=2,
                output_face_blendshapes=True,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
            )
            self._lm = vision.FaceLandmarker.create_from_options(opts)
        return self._lm

    def warmup(self) -> None:
        with self._lock:
            try:
                self._detector()
                self._adaface()
                self._landmarker()
                self.load_error = None
            except Exception as exc:  # surfaced via /api/health
                self.load_error = f"{type(exc).__name__}: {exc}"
                raise

    def close(self) -> None:
        """Release MediaPipe explicitly while its dispatcher is still alive.

        Relying on cyclic-GC finalizers can deadlock a later HTTP worker on Windows.
        The caller stops intake before closing; repeated close is safe.
        """
        with self._lock:
            if self._lm is not None:
                self._lm.close()
                self._lm = None
            self._ada = None
            self._det = None

    def status(self) -> dict[str, Any]:
        dev = None
        if self._ada is not None:
            dev = str(self._ada.device)
        return {
            "engine": "real",
            "model_id": self.model_id,
            "detector_loaded": self._det is not None,
            "embedder_loaded": self._ada is not None,
            "landmarker_loaded": self._lm is not None,
            "device": dev,
            "error": self.load_error,
        }

    # ------------------------------------------------------------------ inference
    def observe(self, rgb: U8, rt: dict[str, Any]) -> FaceObservation:
        with self._lock:
            dets = self._detector().detect(rgb)
            strong = [d for d in dets if d.score >= 0.5]
            obs = FaceObservation(n_faces=len(strong))
            if len(strong) != 1:
                obs.problems = quality_problems(obs, rt, check_norm=False)
                return obs
            d = strong[0]
            lm = d.landmarks.astype(np.float64)
            obs.det_score = float(d.score)
            obs.residual = alignment_residual(lm)
            obs.face_px = float(min(d.box[2] - d.box[0], d.box[3] - d.box[1]))
            crop, _ = align_to_template(rgb, lm)
            obs.crop = crop
            obs.sharpness, obs.brightness = crop_quality(crop)
            emb, norms = self._adaface().embed(crop[None])
            obs.embedding = emb[0]
            obs.feature_norm = float(norms[0])
            obs.problems = quality_problems(obs, rt, check_norm=True)
            return obs

    def frame_metrics(self, rgb: U8) -> FrameMetrics:
        import mediapipe as mp

        with self._lock:
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            res = self._landmarker().detect(image)
        faces = res.face_landmarks or []
        if len(faces) != 1:
            return FrameMetrics(n_faces=len(faces))
        lm = np.array([[p.x, p.y] for p in faces[0]], dtype=np.float64)
        blink = 0.0
        if res.face_blendshapes:
            scores = {c.category_name: c.score for c in res.face_blendshapes[0]}
            blink = (scores.get("eyeBlinkLeft", 0.0) + scores.get("eyeBlinkRight", 0.0)) / 2
        return metrics_from_landmarks(lm, blink)


class FakeFaceEngine:
    """Deterministic engine for tests: an image's identity is encoded in its top-left pixel.

    * pixel (0,0) red channel  -> identity id (0 = no face, 255 = two faces)
    * pixel (0,1) values       -> yaw / pitch / blink metrics for liveness tests
    """

    model_id = "fake-engine"

    def __init__(self) -> None:
        rng = np.random.default_rng(1234)
        base = rng.normal(size=(256, 512)).astype(np.float32)
        self.identities = base / np.linalg.norm(base, axis=1, keepdims=True)

    def status(self) -> dict[str, Any]:
        return {"engine": "fake", "model_id": self.model_id, "error": None}

    def observe(self, rgb: U8, rt: dict[str, Any]) -> FaceObservation:
        ident = int(rgb[0, 0, 0])
        if ident == 0:
            return FaceObservation(n_faces=0, problems=["no face detected"])
        if ident == 255:
            return FaceObservation(n_faces=2, problems=["2 faces visible"])
        noise = (int(rgb[0, 0, 1]) - 128) / 400.0
        e = self.identities[ident].copy()
        e[0] += noise
        e /= np.linalg.norm(e)
        obs = FaceObservation(
            n_faces=1,
            det_score=0.9,
            residual=2.0,
            face_px=200.0,
            sharpness=100.0,
            brightness=120.0,
            embedding=e.astype(np.float32),
            feature_norm=float(rgb[0, 0, 2]) / 5.0,  # 100 -> 20.0
        )
        obs.problems = quality_problems(obs, rt, check_norm=True)
        return obs

    def frame_metrics(self, rgb: U8) -> FrameMetrics:
        ident = int(rgb[0, 0, 0])
        if ident == 0:
            return FrameMetrics(n_faces=0)
        if ident == 255:
            return FrameMetrics(n_faces=2)
        px = rgb[0, 1].astype(np.float64)
        return FrameMetrics(
            n_faces=1,
            yaw=(px[0] - 128) / 400.0,
            pitch=0.5 + (px[1] - 128) / 400.0,
            blink=px[2] / 255.0,
            cx=0.5,
            cy=0.5,
            size=0.4,
        )
