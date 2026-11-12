import numpy as np
import pytest

from attendx.config import RUNTIME_DEFAULTS
from attendx.services.verification import (
    ABSTAIN,
    MATCH,
    NON_MATCH,
    EnrollmentError,
    TemplateCipher,
    build_template,
    decide,
)

RT = dict(RUNTIME_DEFAULTS)


def unit(v):  # type: ignore[no-untyped-def]
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


def test_decision_rule():
    assert decide([0.7, 0.65, 0.6], RT).decision == MATCH
    assert decide([0.05, 0.1], RT).decision == NON_MATCH
    assert decide([0.33, 0.35], RT).decision == ABSTAIN  # uncertain zone
    assert decide([0.7], RT).decision == ABSTAIN  # insufficient evidence
    assert decide([], RT).decision == ABSTAIN
    inconsistent = decide([0.8, 0.75, 0.1], RT)
    assert inconsistent.decision == ABSTAIN and "inconsistent" in inconsistent.reason
    assert decide([0.40, 0.40], RT).decision == MATCH  # boundary inclusive
    assert decide([0.2499, 0.2499], RT).decision == NON_MATCH


def test_thresholds_are_configurable():
    strict = {**RT, "match_threshold": 0.9}
    assert decide([0.7, 0.7], strict).decision == ABSTAIN


def test_build_template_consistency():
    rng = np.random.default_rng(0)
    base = rng.normal(size=512)
    same = [unit(base + 0.2 * rng.normal(size=512)) for _ in range(4)]
    t, cons = build_template(same, RT)
    assert abs(np.linalg.norm(t) - 1) < 1e-5 and cons > 0.5
    with pytest.raises(EnrollmentError, match="at least"):
        build_template(same[:2], RT)
    mixed = same[:2] + [unit(rng.normal(size=512))]
    with pytest.raises(EnrollmentError, match="same person"):
        build_template(mixed, RT)


def test_cipher_roundtrip_and_key_protection(tmp_path):
    c = TemplateCipher.from_settings(None, tmp_path)
    assert (tmp_path / "template.key").is_file()
    t = unit(np.arange(512, dtype=np.float32) + 1)
    blob = c.encrypt(t, "model-a")
    assert t.tobytes() not in blob
    np.testing.assert_array_equal(c.decrypt(blob, "model-a"), t)
    with pytest.raises(ValueError, match="different face model"):
        c.decrypt(blob, "model-b")
    other = TemplateCipher.from_settings(None, tmp_path / "other")  # a different key
    with pytest.raises(ValueError, match="cannot be decrypted"):
        other.decrypt(blob, "model-a")
    # same key file reloads
    np.testing.assert_array_equal(TemplateCipher.from_settings(None, tmp_path).decrypt(blob, "model-a"), t)
