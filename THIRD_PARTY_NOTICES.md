# Third-party notices

## Models (downloaded by `scripts/fetch_models.py`, never redistributed in this repository)

| Model | Source | Licence / terms | Citation |
|---|---|---|---|
| SCRFD `det_10g.onnx` (InsightFace `buffalo_l` v0.7), SHA-256 `5838f7fe…5b91` | github.com/deepinsight/insightface | InsightFace pretrained models: **non-commercial research only** | J. Guo et al., *Sample and Computation Redistribution for Efficient Face Detection*, ICLR 2022 |
| AdaFace IR-101, WebFace4M (`minchul/cvlface_adaface_ir101_webface4m`, rev `f2b38d9e`), SHA-256 `21adb622…80a8` | huggingface.co (CVLface) | CVLface code MIT; weights trained on WebFace4M, which is **non-commercial research only** | M. Kim, A. K. Jain, X. Liu, *AdaFace: Quality Adaptive Margin for Face Recognition*, CVPR 2022 |
| MediaPipe Face Landmarker `face_landmarker.task` (float16 v1), SHA-256 `64184e22…c9ff` | storage.googleapis.com/mediapipe-models | Apache-2.0 | Google MediaPipe |
| RapidOCR / PaddleOCR ONNX models (bundled in `rapidocr-onnxruntime`) | PyPI | Apache-2.0 | PaddleOCR, RapidAI |

Because of the InsightFace and WebFace4M terms, AttendX as configured is for **non-commercial
academic use only**.

## Code reused from VEIL-X

`backend/attendx/face/scrfd.py`, `align.py` and `preprocess.py` are copied from VEIL-X
(github.com/MeezaUni/VEIL-X, commit `e37aef5`) with changed import paths only. `adaface.py` and
`spec.py` adapt VEIL-X's IR-101 architecture, strict safetensors loader and backbone
specification. The prior AttendX MIT grant is retained for these reused or adapted files.
See [the MIT notice for the VEIL-X-derived code](LICENSES/VEIL-X-MIT.txt).

## Libraries

Backend: FastAPI, Starlette, Uvicorn, SQLAlchemy, Alembic, Pydantic (MIT/BSD); PyTorch (BSD);
ONNX Runtime (MIT); OpenCV (Apache-2.0); NumPy (BSD); MediaPipe (Apache-2.0); argon2-cffi (MIT);
cryptography (Apache-2.0/BSD); openpyxl (MIT); pdfplumber (MIT); Pillow (MIT-CMU).

Frontend: React, React Router (MIT); Vite (MIT); Tailwind CSS (MIT); @mediapipe/tasks-vision
(Apache-2.0); Inter font via @fontsource-variable/inter (SIL OFL 1.1).

V2 desktop: PySide6 / Qt and shiboken6 (LGPL-3.0 / GPL / commercial alternatives; this
prototype uses the open-source LGPL distribution with separate shared libraries), qrcode
(BSD), PyInstaller (GPL with its application-distribution exception), PyWinRT (MIT).
Distribute the complete onedir package with its shared Qt libraries and applicable notices;
review the Qt licensing obligations before any wider redistribution. Qt deployment reference:
https://doc.qt.io/qtforpython-6/deployment/index.html .

V2 browser QR scanner: @zxing/browser and @zxing/library (Apache-2.0),
https://github.com/zxing-js/browser . Development mail catcher: Mailpit (MIT),
https://github.com/axllent/mailpit . External model licensing restrictions above still apply.
