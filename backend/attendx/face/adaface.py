# Adapted from VEIL-X (github.com/MeezaUni/VEIL-X, commit e37aef5):
#   src/veilx/models/architectures.py (CVLfaceIR101, unchanged),
#   src/veilx/models/loader.py (strict safetensors loading, unchanged logic),
#   src/veilx/models/extractor.py (fp32 inference, L2 normalisation, feature norm as quality).
"""Frozen AdaFace IR-101 embedding extractor (inference only).

Loading is strict: safetensors only (no pickle), pinned SHA-256 and size, exact key set,
per-tensor shape/dtype check and ``load_state_dict(strict=True)``. Embeddings are L2-normalised
float32; the pre-normalisation norm (the AdaFace *feature norm*) is returned as a quality proxy.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import torch
from numpy.typing import NDArray
from torch import nn

from attendx.face.preprocess import to_model_input
from attendx.face.spec import BackboneSpec


class ModelLoadError(RuntimeError):
    pass


class _Flatten(nn.Module):
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x.view(x.size(0), -1)


class _BasicBlockIR(nn.Module):
    def __init__(self, in_channel: int, depth: int, stride: int) -> None:
        super().__init__()
        self.shortcut_layer: nn.Module
        if in_channel == depth:
            self.shortcut_layer = nn.MaxPool2d(1, stride)
        else:
            self.shortcut_layer = nn.Sequential(
                nn.Conv2d(in_channel, depth, (1, 1), stride, bias=False), nn.BatchNorm2d(depth)
            )
        self.res_layer = nn.Sequential(
            nn.BatchNorm2d(in_channel),
            nn.Conv2d(in_channel, depth, (3, 3), (1, 1), 1, bias=False),
            nn.BatchNorm2d(depth),
            nn.PReLU(depth),
            nn.Conv2d(depth, depth, (3, 3), stride, 1, bias=False),
            nn.BatchNorm2d(depth),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.res_layer(x) + self.shortcut_layer(x)


_IR101_STAGES = ((64, 64, 3), (64, 128, 13), (128, 256, 30), (256, 512, 3))


class CVLfaceIR101(nn.Module):
    def __init__(self, output_dim: int = 512) -> None:
        super().__init__()
        self.input_layer = nn.Sequential(
            nn.Conv2d(3, 64, (3, 3), 1, 1, bias=False), nn.BatchNorm2d(64), nn.PReLU(64)
        )
        self.output_layer = nn.Sequential(
            nn.BatchNorm2d(512),
            nn.Dropout(0.4),
            _Flatten(),
            nn.Linear(512 * 7 * 7, output_dim),
            nn.BatchNorm1d(output_dim, affine=False),
        )
        units: list[nn.Module] = []
        for in_c, depth, n in _IR101_STAGES:
            units.append(_BasicBlockIR(in_c, depth, 2))
            units.extend(_BasicBlockIR(depth, depth, 1) for _ in range(n - 1))
        self.body = nn.Sequential(*units)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.output_layer(self.body(self.input_layer(x)))


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _strip_prefix(state: Mapping[str, torch.Tensor], prefix: str) -> dict[str, torch.Tensor]:
    bad = [k for k in state if not k.startswith(prefix)]
    if bad:
        raise ModelLoadError(f"{len(bad)} checkpoint keys lack prefix {prefix!r}: {bad[:5]}")
    return {k[len(prefix) :]: v for k, v in state.items()}


def _check_state_compatible(model: nn.Module, state: Mapping[str, torch.Tensor]) -> None:
    expected = model.state_dict()
    missing = sorted(set(expected) - set(state))
    unexpected = sorted(set(state) - set(expected))
    if missing or unexpected:
        raise ModelLoadError(f"key mismatch: missing {missing[:5]}, unexpected {unexpected[:5]}")
    bad = [
        k
        for k, v in expected.items()
        if tuple(state[k].shape) != tuple(v.shape) or state[k].dtype != v.dtype
    ]
    if bad:
        raise ModelLoadError(f"{len(bad)} shape/dtype mismatches: {bad[:3]}")


def load_adaface(spec: BackboneSpec, weights_dir: Path, *, verify_hash: bool = True) -> nn.Module:
    from safetensors.torch import load_file

    path = weights_dir / spec.weights_file
    if not path.is_file():
        raise ModelLoadError(f"AdaFace weights not found at {path}")
    if path.stat().st_size != spec.weights_bytes:
        raise ModelLoadError("AdaFace weight file size differs from the pinned value")
    if verify_hash and sha256_file(path) != spec.weights_sha256:
        raise ModelLoadError("AdaFace weight SHA-256 differs from the pinned value")
    state = _strip_prefix(load_file(str(path), device="cpu"), spec.state_dict_prefix)
    model = CVLfaceIR101(spec.embedding_dim)
    _check_state_compatible(model, state)
    model.load_state_dict(state, strict=True)
    model.eval()
    model.requires_grad_(False)
    return model


class AdaFaceExtractor:
    """fp32 inference on CUDA when available, otherwise CPU."""

    def __init__(
        self, spec: BackboneSpec, weights_dir: Path, *, device: str = "auto", verify_hash=True
    ) -> None:
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.spec = spec
        self.device = torch.device(device)
        self.model = load_adaface(spec, weights_dir, verify_hash=verify_hash).to(self.device)
        torch.backends.cudnn.benchmark = False

    def embed(
        self, crops_rgb: NDArray[np.uint8]
    ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        """(N,112,112,3) uint8 RGB -> (L2-normalised embeddings (N,512), feature norms (N,))."""
        x = to_model_input(crops_rgb, self.spec.preprocess)
        with torch.inference_mode():
            out = self.model(torch.from_numpy(x).to(self.device)).float().cpu().numpy()
        if not np.isfinite(out).all():
            raise FloatingPointError("non-finite embedding values")
        norms = np.linalg.norm(out, axis=1)
        if (norms <= 0).any():
            raise FloatingPointError("zero-norm embedding")
        return (out / norms[:, None]).astype(np.float32), norms.astype(np.float32)
