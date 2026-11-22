"""Build a standalone launcher on the host OS (requires PyInstaller on the build machine)."""

from __future__ import annotations

import subprocess
import sys
import os
import tempfile
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                        "--no-cache-dir", "--wheel-dir", str(output), str(root)], check=True)
        wheel = next(output.glob("mangekyo_agent-*.whl"))
        return subprocess.call([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
            "--name", "mangekyo", "--collect-data", "mangekyo", "--collect-submodules", "mangekyo",
            "--collect-all", "prompt_toolkit", "--collect-all", "pypdfium2",
            "--collect-all", "playwright", "--add-data", f"{wheel}{os.pathsep}sdk",
            str(root / "mangekyo_launcher.py"),
        ], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
