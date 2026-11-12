"""PyInstaller entry point, separate from the central server CLI."""

from attendx.faculty.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
