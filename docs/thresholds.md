# Face-verification thresholds: provisional values and how to validate them

## Why VEIL-X's thresholds are not reused

VEIL-X calibrated a quality-stratified logistic rule with Learn-then-Test on **synthetic
DigiFace-1M faces with synthetic occlusions**. Its own replication showed that the error targets
did **not** transfer to a different synthetic population. Student selfies on phone cameras are
another population again. AttendX therefore reuses VEIL-X's *models and code*, but not its
calibrated decision thresholds.

## The deployed rule

For each attempt the server embeds up to four frontal frames (two before and two after the
challenge actions) and computes cosine similarity with the student's template:

| Condition | Decision |
|---|---|
| fewer than 2 usable frames | ABSTAIN (insufficient evidence) |
| median < `nonmatch_threshold` | NON-MATCH |
| median ≥ `match_threshold` **and** every frame ≥ `nonmatch_threshold` | MATCH |
| otherwise | ABSTAIN (uncertain or inconsistent) |

A frame is usable only if it shows exactly one face that passes every quality gate: SCRFD
score ≥ 0.6, 5-point alignment residual ≤ 7.34 (both VEIL-X Phase 4F geometric values), face
side ≥ 80 px, brightness within 40–225, Laplacian sharpness ≥ 12, and AdaFace feature norm ≥ 14.

## Provisional defaults (admin-editable under *Settings*)

| Setting | Default | Basis |
|---|---|---|
| `match_threshold` | 0.40 | VEIL-X development data: different-person p90 ≈ 0.20, same-person median ≈ 0.52 (occluded synthetic faces). Placed well above the impostor bulk. |
| `nonmatch_threshold` | 0.25 | Above the typical impostor range, leaving an ABSTAIN band between 0.25 and 0.40. |
| `min_feature_norm` | 14 | Below VEIL-X's development p10 (16.2). VEIL-X found that very low-norm inputs, even noise, can score as matches. |
| `enroll_min_consistency` | 0.50 | Minimum pairwise similarity between enrollment images. |

**These values are provisional.** Before relying on them, validate them as described below.

## Evidence so far (synthetic only)

`docs/results/synthetic_calibration_digiface.json`, produced with the real pipeline on 10
synthetic DigiFace identities (8 usable; 34 genuine and 238 impostor single-frame scores):

* genuine p1 = 0.571, p5 = 0.632; impostor p99 = 0.343, impostor max = 0.389;
* single frame at 0.25: FMR 6.7 % (16/238), so the 0.25 bound alone is **not** a safe acceptance
  threshold; this is why MATCH needs a median ≥ 0.40;
* deployed 3-frame rule: genuine 73/73 MATCH; impostor 0 MATCH, 485 NON-MATCH, 26 ABSTAIN.

This is a tiny synthetic sample. It shows the procedure works; it is **not** an accuracy figure
for students or phone cameras.

## Validation procedure (do this with your own consenting participants)

1. Collect, with written consent, 8–10 images per person for at least 20 people, taken with the
   phones, distances and lighting used in class. Keep the folder private; never commit it.
2. Run:
   ```powershell
   backend\.venv\Scripts\python.exe scripts\calibrate_thresholds.py C:\private\faces --out calib.json
   ```
3. Read `single_score_rates` (FMR/FNMR per threshold) and `three_frame_rule`. Choose
   `match_threshold` so that **no** impostor triple is a MATCH and the impostor single-frame
   maximum is clearly below it. Choose `nonmatch_threshold` near the genuine p1. Report the
   counts with every rate (for example "0 of 485 impostor triples").
4. Enter the values under *Settings* (the change is audited) and keep `calib.json` with the
   project records.
5. Repeat whenever the camera, the population or the model changes.

Optional visibility heat maps from VEIL-X are not part of AttendX's decision path. If you add
them for administrators, validate them separately before letting them influence anything.
