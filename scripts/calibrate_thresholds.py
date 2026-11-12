"""Validate AttendX's face-verification thresholds on YOUR population (procedure in
docs/thresholds.md). Nothing here is assumed: every number printed is measured on the folder you
supply.

Input folder layout (consented images only; never commit it):

    faces/
      student_a/  img1.jpg img2.jpg ...   (>= enroll_k + 1 images, ideally captured with the
      student_b/  ...                      phones and lighting used for attendance)

For every identity the first ``--enroll-k`` usable images build a template exactly as AttendX
enrollment does; every remaining image is a genuine probe for its own template and an impostor
probe for every other template. Single-image scores are reported, and also the deployed
3-frame median rule (MATCH / NON-MATCH / ABSTAIN) on groups of three probes.

Usage (from the repository root):
    backend/.venv/Scripts/python.exe scripts/calibrate_thresholds.py faces/ --out calib.json
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from attendx.config import RUNTIME_DEFAULTS  # noqa: E402
from attendx.face.engine import RealFaceEngine, decode_image  # noqa: E402
from attendx.services.verification import EnrollmentError, build_template, decide  # noqa: E402

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def rates(gen: np.ndarray, imp: np.ndarray, t: float) -> tuple[float, float]:
    fnmr = float((gen < t).mean()) if gen.size else float("nan")
    fmr = float((imp >= t).mean()) if imp.size else float("nan")
    return fmr, fnmr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--enroll-k", type=int, default=3)
    ap.add_argument("--models", type=Path, default=ROOT / "models")
    ap.add_argument("--match", type=float, default=RUNTIME_DEFAULTS["match_threshold"])
    ap.add_argument("--nonmatch", type=float, default=RUNTIME_DEFAULTS["nonmatch_threshold"])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    rt = dict(RUNTIME_DEFAULTS)
    eng = RealFaceEngine(args.models)
    eng.warmup()
    templates: dict[str, np.ndarray] = {}
    probes: dict[str, list[np.ndarray]] = {}
    skipped: dict[str, int] = {}
    for d in sorted(p for p in args.folder.iterdir() if p.is_dir()):
        embs = []
        for f in sorted(d.iterdir()):
            if f.suffix.lower() not in EXTS:
                continue
            obs = eng.observe(decode_image(f.read_bytes(), max_side=1600), rt)
            if obs.usable and obs.embedding is not None:
                embs.append(obs.embedding)
            else:
                skipped[d.name] = skipped.get(d.name, 0) + 1
        if len(embs) <= args.enroll_k:
            print(f"skip {d.name}: only {len(embs)} usable images", file=sys.stderr)
            continue
        try:
            templates[d.name], _ = build_template(embs[: args.enroll_k], rt)
        except EnrollmentError as exc:
            print(f"skip {d.name}: {exc}", file=sys.stderr)
            continue
        probes[d.name] = embs[args.enroll_k :]
    ids = list(templates)
    if len(ids) < 2:
        print("need at least two identities with enough usable images", file=sys.stderr)
        return 1

    gen, imp = [], []
    for a in ids:
        for e in probes[a]:
            for b in ids:
                (gen if a == b else imp).append(float(e @ templates[b]))
    g, i = np.array(gen), np.array(imp)

    # deployed rule: median of 3 frames (genuine triples within one identity; impostor triples
    # = one identity's probes against another identity's template)
    rule = {kind: {"match": 0, "non_match": 0, "abstain": 0} for kind in ("genuine", "impostor")}
    rt_rule = {**rt, "match_threshold": args.match, "nonmatch_threshold": args.nonmatch}
    for a in ids:
        triples = list(combinations(probes[a], 3))[:50]
        for b in ids:
            for tr in triples:
                d = decide([float(e @ templates[b]) for e in tr], rt_rule).decision
                rule["genuine" if a == b else "impostor"][d] += 1

    grid = []
    for t in np.round(np.arange(0.10, 0.71, 0.05), 2):
        fmr, fnmr = rates(g, i, float(t))
        grid.append({"threshold": float(t), "FMR": round(fmr, 5), "FNMR": round(fnmr, 5)})
    report = {
        "identities": len(ids),
        "genuine_scores": int(g.size),
        "impostor_scores": int(i.size),
        "skipped_images": skipped,
        "genuine_percentiles": {p: round(float(np.percentile(g, p)), 4) for p in (1, 5, 10, 50)},
        "impostor_percentiles": {p: round(float(np.percentile(i, p)), 4) for p in (50, 90, 95, 99)},
        "impostor_max": round(float(i.max()), 4),
        "single_score_rates": grid,
        "three_frame_rule": {"match_threshold": args.match, "nonmatch_threshold": args.nonmatch, **rule},
        "note": "Measured on the supplied folder only. Small samples give wide uncertainty; "
        "report the counts with any rate you quote.",
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
