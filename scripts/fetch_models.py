"""Populate AttendX's model folder (default ./models, gitignored) with the three model files.

* SCRFD det_10g.onnx (InsightFace buffalo_l v0.7)           - face detection + 5 landmarks
* AdaFace IR-101 WebFace4M model.safetensors (CVLface)       - 512-d face embeddings
* MediaPipe face_landmarker.task (float16, v1)               - liveness landmarks/blendshapes

Usage:
    python scripts/fetch_models.py                      # download from the official sources
    python scripts/fetch_models.py --from-dir C:/Path/To/veilx_data/models
                                                        # copy (read-only) from a local folder

Every file is verified against a pinned SHA-256 before it is accepted. Model files are
research-licensed (non-commercial) and must never be committed to Git.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = {
    "scrfd/det_10g.onnx": {
        "sha256": "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91",
        "local": ["insightface_buffalo_l_v0.7/det_10g.onnx"],
        "url": "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
        "zip_member": "det_10g.onnx",
    },
    "adaface_ir101_webface4m/model.safetensors": {
        "sha256": "21adb6220e8799a0e658f16946df9649c7269f432fe9810a7b9c4ad1241080a8",
        "local": [
            "minchul__cvlface_adaface_ir101_webface4m/"
            "f2b38d9e24bfe301490d8dd081d8924b102333dd/model.safetensors"
        ],
        "url": "https://huggingface.co/minchul/cvlface_adaface_ir101_webface4m/resolve/"
        "f2b38d9e24bfe301490d8dd081d8924b102333dd/model.safetensors",
    },
    "mediapipe/face_landmarker.task": {
        "sha256": "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
        "local": ["mediapipe/face_landmarker.task"],
        "url": "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task",
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "attendx-fetch-models"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", type=Path, default=ROOT / "models")
    ap.add_argument("--from-dir", type=Path, help="local folder to copy from (never modified)")
    ap.add_argument("--print-hashes", action="store_true")
    args = ap.parse_args()
    ok = True
    for rel, meta in FILES.items():
        dest = args.dest / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and sha256(dest) == meta["sha256"]:
            print(f"[ok]   {rel}")
            continue
        src = None
        if args.from_dir:
            for cand in meta["local"]:
                p = args.from_dir / cand
                if p.is_file():
                    src = p
                    break
        tmp = dest.with_suffix(dest.suffix + ".part")
        if src is not None:
            print(f"[copy] {rel} <- {src}")
            shutil.copyfile(src, tmp)
        else:
            print(f"[get]  {rel}")
            if "zip_member" in meta:
                zpath = dest.parent / "download.zip"
                download(meta["url"], zpath)
                with zipfile.ZipFile(zpath) as z, z.open(meta["zip_member"]) as m:
                    tmp.write_bytes(m.read())
                zpath.unlink()
            else:
                download(meta["url"], tmp)
        got = sha256(tmp)
        if args.print_hashes:
            print(f"       sha256 {got}")
        if got != meta["sha256"]:
            print(f"[FAIL] {rel}: SHA-256 {got} differs from the pinned value; file discarded")
            tmp.unlink()
            ok = False
            continue
        tmp.replace(dest)
        print(f"[ok]   {rel}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
