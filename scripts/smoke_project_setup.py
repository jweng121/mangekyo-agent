"""Exercise bundled SDK installation into a project venv and setup rerun."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: smoke_project_setup.py PATH_TO_MANGEKYO|--source")
    command_prefix = ([sys.executable, "-m", "mangekyo"] if sys.argv[1] == "--source"
                      else [str(Path(sys.argv[1]).resolve())])
    with tempfile.TemporaryDirectory(prefix="mangekyo-project-setup-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        store = root / "store"
        venv = project / ".venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=120)
        project_python = (venv / "Scripts" / "python.exe" if sys.platform == "win32"
                          else venv / "bin" / "python")

        def command(*args: str) -> str:
            completed = subprocess.run([*command_prefix, "--home", str(store), *args],
                                       cwd=project, text=True, capture_output=True, timeout=180)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            return completed.stdout

        first = command("setup", "--project", str(project))
        assert "SDK import verified:" in first
        assert 'from mangekyo import RunRecorder, Store' in first
        assert 'run.record("tool", name="read"' in first
        demo = json.JSONDecoder().raw_decode(command("demo"))[0]
        assert demo["store_path"] == str(store.resolve())
        second = command("setup", "--project", str(project))
        assert "SDK import verified:" in second
        import_check = subprocess.run([str(project_python), "-c",
                                       "import mangekyo; print(mangekyo.__file__)"],
                                      cwd=project, text=True, capture_output=True, timeout=30)
        assert import_check.returncode == 0, import_check.stderr
        doctor = json.loads(command("doctor"))
        assert doctor["runs"] == 1 and doctor["database_integrity"] == "ok"
        print(f"Project setup smoke passed: SDK import, rerun preservation, demo {demo['run_id']}")


if __name__ == "__main__":
    main()
