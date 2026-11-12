"""Reproducible onedir Windows package. Run with backend/.venv/Scripts/python.exe."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist/faculty")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Reuse PyInstaller's dependency cache for a local source update",
    )
    options = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Build the Windows executable on Windows with Python 3.12.")
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("Run npm ci && npm run build in frontend first.")
    assets = ROOT / "build/faculty/assets"
    assets.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (256, 256), (31, 58, 150, 255))
    draw = ImageDraw.Draw(image)
    draw.line([(55, 130), (105, 180), (205, 70)], fill="white", width=24, joint="curve")
    icon = assets / "attendx.ico"
    image.save(
        icon, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        "AttendXFaculty",
        "--icon",
        str(icon),
        "--paths",
        str(ROOT / "backend"),
        "--distpath",
        str(options.dist_dir.resolve()),
        "--workpath",
        str(ROOT / "build/faculty/work"),
        "--specpath",
        str(ROOT / "build/faculty"),
        "--add-data",
        f"{ROOT / 'frontend/dist'};frontend/dist",
        "--add-data",
        f"{assets};assets",
        "--collect-all",
        "mediapipe",
        "--collect-all",
        "onnxruntime",
        "--collect-submodules",
        "winrt.windows.networking",
        "--collect-submodules",
        "winrt.windows.foundation",
        "--exclude-module",
        "PyQt5",
        "--exclude-module",
        "PyQt6",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "IPython",
        str(ROOT / "scripts/faculty_entry.py"),
    ]
    # Native tools elsewhere on this workstation ship incompatible DLLs with common names
    if options.incremental:
        args.remove("--clean")
    # (notably Poppler's versioned ICU versus Qt's Windows ICU API). Never collect from PATH.
    env = os.environ.copy()
    windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
    env["PATH"] = os.pathsep.join(
        [
            str(Path(sys.executable).parent),
            sys.base_prefix,
            str(windows / "System32"),
            str(windows),
        ]
    )
    for key in ("PYTHONPATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(key, None)
    subprocess.run(args, cwd=ROOT, env=env, check=True)
    print(options.dist_dir.resolve() / "AttendXFaculty/AttendXFaculty.exe")
    print(
        "Distribute the entire AttendXFaculty directory. Model weights remain external; see docs/v2/OPERATIONS.md."
    )


if __name__ == "__main__":
    main()
