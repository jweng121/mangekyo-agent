"""Connect a Python virtual environment without asking the user to run pip."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def connect_project(project: Path) -> str:
    project = project.expanduser().resolve()
    if not project.is_dir():
        raise ValueError(f"Project directory does not exist: {project}")
    candidates = [project / ".venv" / "Scripts" / "python.exe",
                  project / ".venv" / "bin" / "python"]
    python = next((p for p in candidates if p.is_file()), None)
    if python is None:
        raise ValueError(f"No .venv found in {project}. Create a project virtual environment first.")
    bundle = Path(getattr(sys, "_MEIPASS", "")) / "sdk"
    wheels = list(bundle.glob("mangekyo_agent-*.whl")) if bundle.is_dir() else []
    source = Path(__file__).parent.parent
    if wheels:
        package = wheels[0]
        temp = None
    elif (source / "pyproject.toml").exists():
        temp = tempfile.TemporaryDirectory()
        built = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                                "--no-cache-dir", "--wheel-dir", temp.name, str(source)],
                               cwd=project, text=True, capture_output=True, timeout=180)
        if built.returncode:
            temp.cleanup()
            raise RuntimeError("SDK wheel build failed: " + (built.stderr or built.stdout)[-600:])
        package = next(Path(temp.name).glob("mangekyo_agent-*.whl"))
    else:
        raise RuntimeError("Bundled Mangekyo SDK is missing; use a complete standalone build")
    print(f"Installing Mangekyo SDK into {python} from {package}")
    try:
        completed = subprocess.run([str(python), "-m", "pip", "install", "--no-cache-dir", "--no-deps", str(package)],
                                   cwd=project, text=True, capture_output=True, timeout=180)
    finally:
        if temp:
            temp.cleanup()
    if completed.returncode:
        raise RuntimeError("SDK installation failed: " + (completed.stderr or completed.stdout)[-600:])
    check = subprocess.run([str(python), "-c", "import mangekyo; print(mangekyo.__file__)"],
                           cwd=project, text=True, capture_output=True, timeout=20)
    if check.returncode:
        raise RuntimeError("SDK installation completed but import verification failed: " + check.stderr[-400:])
    return check.stdout.strip()
