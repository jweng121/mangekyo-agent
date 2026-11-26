"""Connect a Python virtual environment without asking the user to run pip."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import json
from importlib.metadata import distribution, version
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname


def connect_project(project: Path, *, verbose: bool = True) -> str:
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
    installed_wheel = not wheels and not (source / "pyproject.toml").exists()
    if installed_wheel:
        current_version = version("mangekyo-agent")
        check = subprocess.run([str(python), "-c",
                                "from importlib.metadata import version; import mangekyo; "
                                "print(version('mangekyo-agent')); print(mangekyo.__file__)"],
                               cwd=project, text=True, capture_output=True, timeout=20)
        lines = check.stdout.splitlines()
        if check.returncode == 0 and len(lines) >= 2 and lines[0] == current_version:
            return lines[1]
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
        direct_url = distribution("mangekyo-agent").read_text("direct_url.json")
        local_wheel = None
        if direct_url:
            location = urlparse(json.loads(direct_url).get("url", ""))
            if location.scheme == "file":
                candidate = Path(url2pathname(location.path))
                if candidate.is_file() and candidate.suffix == ".whl":
                    local_wheel = candidate
        package = local_wheel or f"mangekyo-agent=={current_version}"
        temp = None
    if verbose:
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
