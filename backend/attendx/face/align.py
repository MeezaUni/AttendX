# Vendored from VEIL-X (github.com/MeezaUni/VEIL-X, commit e37aef5, src/veilx/detect/align.py).
# Unchanged except for import paths. MIT licence (VEIL-X code).
"""Similarity alignment to the ArcFace 112x112 five-point template (numpy only).

``umeyama`` is the least-squares similarity transform (rotation, uniform scale, translation)
of Umeyama (1991) - the estimator InsightFace's ``norm_crop`` uses through scikit-image's
``SimilarityTransform``. ``warp`` applies the 2x3 matrix with bilinear sampling and a black
border (OpenCV ``warpAffine`` semantics when cv2 is available; a numpy fallback otherwise).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from attendx.face.spec import ARCFACE_TEMPLATE_112

F64 = NDArray[np.float64]
TEMPLATE: F64 = np.asarray(ARCFACE_TEMPLATE_112, dtype=np.float64)


def umeyama(src: F64, dst: F64) -> F64:
    """2x3 matrix M with dst ~= M @ [src, 1] (least-squares similarity, no reflection)."""
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    if src.shape != dst.shape or src.ndim != 2 or src.shape[1] != 2 or len(src) < 2:
        raise ValueError("need matching (N, 2) point sets with N >= 2")
    mu_s, mu_d = src.mean(0), dst.mean(0)
    s, d = src - mu_s, dst - mu_d
    cov = d.T @ s / len(src)
    u, sig, vt = np.linalg.svd(cov)
    e = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        e[1, 1] = -1.0
    rot = u @ e @ vt
    var_s = (s**2).sum() / len(src)
    if var_s <= 0:
        raise ValueError("degenerate source points")
    scale = float(np.trace(np.diag(sig) @ e) / var_s)
    t = mu_d - scale * rot @ mu_s
    return np.hstack([scale * rot, t[:, None]])


def transform_points(m: F64, pts: F64) -> F64:
    pts = np.asarray(pts, dtype=np.float64)
    return pts @ m[:, :2].T + m[:, 2]


def warp(image: NDArray[np.uint8], m: F64, size: int = 112) -> NDArray[np.uint8]:
    """Apply the forward matrix ``m`` (image -> crop) and return a ``size`` x ``size`` crop."""
    try:
        import cv2

        out: NDArray[np.uint8] = cv2.warpAffine(
            image, m, (size, size), flags=cv2.INTER_LINEAR, borderValue=0.0
        )
        return out
    except ImportError:  # pragma: no cover - numpy fallback (bilinear)
        inv = np.linalg.inv(np.vstack([m, [0, 0, 1]]))[:2]
        ys, xs = np.mgrid[0:size, 0:size].astype(np.float64)
        sx = inv[0, 0] * xs + inv[0, 1] * ys + inv[0, 2]
        sy = inv[1, 0] * xs + inv[1, 1] * ys + inv[1, 2]
        x0, y0 = np.floor(sx).astype(int), np.floor(sy).astype(int)
        wx, wy = sx - x0, sy - y0
        h, w = image.shape[:2]
        img = image.astype(np.float64)
        acc = np.zeros((size, size, image.shape[2]))
        for dx, dy, wt in (
            (0, 0, (1 - wx) * (1 - wy)),
            (1, 0, wx * (1 - wy)),
            (0, 1, (1 - wx) * wy),
            (1, 1, wx * wy),
        ):
            xi, yi = x0 + dx, y0 + dy
            ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
            acc += (
                np.where(ok[..., None], img[np.clip(yi, 0, h - 1), np.clip(xi, 0, w - 1)], 0)
                * wt[..., None]
            )
        return np.clip(np.rint(acc), 0, 255).astype(np.uint8)


def align_to_template(
    image: NDArray[np.uint8], landmarks: F64, size: int = 112
) -> tuple[NDArray[np.uint8], F64]:
    """Crop aligned to the ArcFace template; returns (crop, 2x3 matrix)."""
    m = umeyama(np.asarray(landmarks, dtype=np.float64), TEMPLATE * (size / 112.0))
    return warp(image, m, size), m


def alignment_residual(landmarks: F64, size: int = 112) -> float:
    """RMS distance (template pixels) between the template and the similarity-aligned landmarks:
    a cheap alignment-quality signal (large when the five points are not face-shaped)."""
    lm = np.asarray(landmarks, dtype=np.float64)
    dst = TEMPLATE * (size / 112.0)
    m = umeyama(lm, dst)
    return float(np.sqrt(((transform_points(m, lm) - dst) ** 2).sum(axis=1).mean()))
