"""Template construction/protection and the attendance-specific 1:1 decision rule.

Decision rule (PROVISIONAL thresholds, admin-configurable, see docs/thresholds.md):

* fewer than 2 usable live frames                        -> ABSTAIN (insufficient evidence)
* median cosine < nonmatch_threshold                       -> NON-MATCH
* median >= match_threshold and every frame >= nonmatch    -> MATCH
* otherwise                                                -> ABSTAIN (uncertain / inconsistent)
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
from cryptography.fernet import Fernet, InvalidToken
from numpy.typing import NDArray

MATCH, NON_MATCH, ABSTAIN = "match", "non_match", "abstain"


@dataclass
class Decision:
    decision: str
    reason: str
    score: float | None
    scores: list[float]


def decide(scores: list[float], rt: dict[str, Any]) -> Decision:
    t_match, t_non = float(rt["match_threshold"]), float(rt["nonmatch_threshold"])
    rounded = [round(float(s), 4) for s in scores]
    if len(scores) < 2:
        return Decision(ABSTAIN, "not enough usable face frames", None, rounded)
    med, mn = float(median(scores)), float(min(scores))
    if med < t_non:
        return Decision(NON_MATCH, "face does not match the enrolled student", med, rounded)
    if med >= t_match and mn >= t_non:
        return Decision(MATCH, "face matches the enrolled student", med, rounded)
    if med >= t_match:
        return Decision(ABSTAIN, "frames were inconsistent; try again", med, rounded)
    return Decision(ABSTAIN, "similarity is in the uncertain zone; try again", med, rounded)


class EnrollmentError(ValueError):
    pass


def build_template(
    embeddings: list[NDArray[np.float32]], rt: dict[str, Any]
) -> tuple[NDArray[np.float32], float]:
    """Mean of L2-normalised embeddings (re-normalised) + min pairwise cosine (consistency)."""
    need = int(rt["enroll_min_frames"])
    if len(embeddings) < need:
        raise EnrollmentError(f"need at least {need} good face images, got {len(embeddings)}")
    e = np.stack(embeddings).astype(np.float32)
    e /= np.linalg.norm(e, axis=1, keepdims=True)
    sims = e @ e.T
    iu = np.triu_indices(len(e), 1)
    consistency = float(sims[iu].min())
    if consistency < float(rt["enroll_min_consistency"]):
        raise EnrollmentError(
            "enrollment images do not look like the same person consistently "
            f"(min similarity {consistency:.2f}); retake them"
        )
    t = e.mean(axis=0)
    return (t / np.linalg.norm(t)).astype(np.float32), consistency


def cosine(a: NDArray[np.float32], b: NDArray[np.float32]) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class TemplateCipher:
    """Fernet (AES-128-CBC + HMAC-SHA256) encryption of templates at rest.

    The key comes from ATTENDX_TEMPLATE_KEY or <data_dir>/template.key (generated on first use).
    Losing the key makes stored templates unusable (students must re-enroll)."""

    def __init__(self, key: bytes) -> None:
        self._f = Fernet(key)

    @classmethod
    def from_settings(cls, explicit: str | None, data_dir: Path) -> TemplateCipher:
        if explicit:
            return cls(explicit.encode())
        path = data_dir / "template.key"
        if not path.is_file():
            data_dir.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key)
        return cls(path.read_bytes().strip())

    def encrypt(self, template: NDArray[np.float32], model_id: str) -> bytes:
        payload = model_id.encode() + b"|" + base64.b64encode(template.astype("<f4").tobytes())
        return self._f.encrypt(payload)

    def seal(self, payload: bytes) -> bytes:
        return self._f.encrypt(payload)

    def open(self, payload: bytes) -> bytes:
        return self._f.decrypt(payload)

    def decrypt(self, blob: bytes, model_id: str) -> NDArray[np.float32]:
        try:
            payload = self._f.decrypt(blob)
        except InvalidToken as exc:
            raise ValueError("template cannot be decrypted with the current key") from exc
        mid, _, b64 = payload.partition(b"|")
        if mid.decode() != model_id:
            raise ValueError("template was created with a different face model; re-enroll")
        return np.frombuffer(base64.b64decode(b64), dtype="<f4").astype(np.float32)
