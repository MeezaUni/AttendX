# Vendored from VEIL-X (github.com/MeezaUni/VEIL-X, commit e37aef5, src/veilx/models/preprocess.py).
# Unchanged except for import paths. MIT licence (VEIL-X code).
"""Model input preparation (numpy only; tested without torch).

Converts aligned uint8 crops to the exact NCHW float32 tensor a backbone expects. It never
resizes, re-aligns or composites: a wrong size, dtype or a non-opaque alpha channel raises.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from attendx.face.spec import PreprocessSpec


def drop_opaque_alpha(images: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """(N,H,W,4) -> (N,H,W,3) only when alpha is 255 everywhere (DigiFace is fully opaque)."""
    if images.shape[-1] == 3:
        return images
    if images.shape[-1] != 4:
        raise ValueError(f"expected 3 or 4 channels, got {images.shape[-1]}")
    if not bool((images[..., 3] == 255).all()):
        raise ValueError("non-opaque alpha channel; refusing to composite silently")
    return np.ascontiguousarray(images[..., :3])


def to_model_input(images_rgb: NDArray[np.uint8], spec: PreprocessSpec) -> NDArray[np.float32]:
    """``images_rgb``: (N,H,W,3|4) uint8 in **RGB** order. Returns (N,3,S,S) float32."""
    if images_rgb.dtype != np.uint8:
        raise TypeError(f"expected uint8 images, got {images_rgb.dtype}")
    if images_rgb.ndim != 4:
        raise ValueError(f"expected (N,H,W,C), got shape {images_rgb.shape}")
    s = spec.input_size
    if images_rgb.shape[1:3] != (s, s):
        raise ValueError(f"expected {s}x{s} aligned crops, got {images_rgb.shape[1:3]}")
    x = drop_opaque_alpha(images_rgb).astype(np.float32) / np.float32(255.0)
    if spec.channel_order == "BGR":
        x = x[..., ::-1]
    mean = np.asarray(spec.mean, dtype=np.float32)
    std = np.asarray(spec.std, dtype=np.float32)
    x = (x - mean) / std
    return np.ascontiguousarray(x.transpose(0, 3, 1, 2), dtype=np.float32)
