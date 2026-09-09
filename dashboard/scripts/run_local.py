from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "backend")
    return subprocess.call([
        sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"),
        "--host", "127.0.0.1", "--port", "7860", "--workers", "1",
    ], env=environment)


if __name__ == "__main__":
    raise SystemExit(main())

