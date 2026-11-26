"""Build a standalone launcher on the host OS (requires PyInstaller on the build machine)."""

from __future__ import annotations

import subprocess
import sys
import os
import tempfile
import shutil
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    dist = root / "dist" if sys.platform == "win32" else root / "dist" / sys.platform
    work = root / "build" if sys.platform == "win32" else root / "build" / sys.platform
    spec = root if sys.platform == "win32" else work
    spec.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory)
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                        "--no-cache-dir", "--wheel-dir", str(output), str(root)], check=True)
        built_wheel = next(output.glob("mangekyo_agent-*.whl"))
        wheel = dist / built_wheel.name
        wheel.parent.mkdir(exist_ok=True)
        shutil.copy2(built_wheel, wheel)
        return subprocess.call([
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
            "--name", "mangekyo", "--collect-data", "mangekyo", "--collect-submodules", "mangekyo",
            "--distpath", str(dist), "--workpath", str(work), "--specpath", str(spec),
            "--collect-all", "prompt_toolkit", "--collect-all", "pypdfium2",
            "--collect-all", "playwright", "--collect-all", "PIL",
            "--add-data", f"{wheel}{os.pathsep}sdk",
            str(root / "mangekyo_launcher.py"),
        ], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
