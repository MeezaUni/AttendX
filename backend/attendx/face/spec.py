# Adapted from VEIL-X (github.com/MeezaUni/VEIL-X, commit e37aef5, src/veilx/models/spec.py).
# Only the AdaFace IR-101 backbone is kept; pinned values are unchanged.
"""Pinned specification of the frozen AdaFace IR-101 backbone and the SCRFD detector file."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

ARCFACE_TEMPLATE_112: tuple[tuple[float, float], ...] = (
    (38.2946, 51.6963),
    (73.5318, 51.5014),
    (56.0252, 71.7366),
    (41.5493, 92.3655),
    (70.7299, 92.2041),
)


@dataclass(frozen=True)
class PreprocessSpec:
    """``(x / 255 - mean) / std`` per channel, RGB, NCHW float32, 112x112 aligned crops."""

    input_size: int = 112
    channel_order: Literal["RGB", "BGR"] = "RGB"
    mean: tuple[float, float, float] = (0.5, 0.5, 0.5)
    std: tuple[float, float, float] = (0.5, 0.5, 0.5)
    alignment_template: tuple[tuple[float, float], ...] = ARCFACE_TEMPLATE_112
    flip_tta: bool = False

    def fingerprint(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


@dataclass(frozen=True)
class BackboneSpec:
    backbone_id: str
    hf_repo: str
    revision: str
    weights_file: str
    weights_sha256: str
    weights_bytes: int
    state_dict_prefix: str
    embedding_dim: int
    preprocess: PreprocessSpec


ADAFACE_IR101 = BackboneSpec(
    backbone_id="adaface_ir101_webface4m",
    hf_repo="minchul/cvlface_adaface_ir101_webface4m",
    revision="f2b38d9e24bfe301490d8dd081d8924b102333dd",
    weights_file="model.safetensors",
    weights_sha256="21adb6220e8799a0e658f16946df9649c7269f432fe9810a7b9c4ad1241080a8",
    weights_bytes=260_980_552,
    state_dict_prefix="model.net.",
    embedding_dim=512,
    preprocess=PreprocessSpec(),
)

# SCRFD det_10g from InsightFace buffalo_l v0.7 (same file VEIL-X pins).
SCRFD_FILE = "det_10g.onnx"
SCRFD_SHA256 = "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91"

# Relative layout inside ATTENDX_MODELS_DIR (populated by scripts/fetch_models.py).
ADAFACE_DIR = "adaface_ir101_webface4m"
SCRFD_DIR = "scrfd"
MEDIAPIPE_DIR = "mediapipe"
MEDIAPIPE_FILE = "face_landmarker.task"
