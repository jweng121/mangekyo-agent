"""Build and exercise the installable wheel outside the source checkout."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", action="store_true",
                        help="Use python -m mangekyo when local policy blocks the generated launcher")
    parser.add_argument("--wheel", type=Path,
                        help="Test this already-built wheel instead of rebuilding from source")
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix="mangekyo-wheel-") as directory:
        root = Path(directory)
        if args.wheel:
            wheel = args.wheel.resolve()
            assert wheel.is_file(), wheel
        else:
            wheels = root / "wheels"
            wheels.mkdir()
            subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps",
                            "--no-cache-dir", "--wheel-dir",
                            str(wheels), str(project)], check=True, cwd=root)
            wheel = next(wheels.glob("mangekyo_agent-*.whl"))
        connected_project = root / "connected-project"
        environment = connected_project / ".venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
        python = scripts / ("python.exe" if sys.platform == "win32" else "python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-index",
                        "--no-deps", str(wheel)], check=True, cwd=root)
        launcher = scripts / ("mangekyo.exe" if sys.platform == "win32" else "mangekyo")
        assert launcher.is_file()
        command = [str(python), "-m", "mangekyo"] if args.module else [str(launcher)]
        home = root / "history"

        def invoke(*args: str) -> str:
            return subprocess.run([*command, "--home", str(home), *args],
                                  check=True, capture_output=True, text=True,
                                  timeout=120, cwd=root).stdout

        invoke("setup")
        sample = root / "sample-agent"
        invoke("sample", str(sample))
        assert (sample / "booking-request.pdf").is_file()
        assert (sample / "agent.py").is_file()
        connected = invoke("setup", "--project", str(connected_project))
        assert "SDK import verified:" in connected
        original = json.JSONDecoder().raw_decode(invoke("demo"))[0]
        run_id, snapshot_id = original["run_id"], original["snapshot_id"]
        assert json.loads(invoke("show", run_id))["status"] == "failed"
        invoke("branch", snapshot_id, "-m", "wheel-smoke", "--replacement", "safe")
        recovered = json.loads(invoke("resume", "wheel-smoke"))
        assert recovered["skipped_steps"] > 0
        assert json.loads(invoke("show", recovered["run_id"]))["status"] == "completed"
        assert json.loads(invoke("benchmark", run_id))["recovered"]
        bundle = root / "run.json"
        invoke("bundle", "export", run_id, str(bundle))
        imported_home = root / "imported"
        imported = subprocess.run([*command, "--home", str(imported_home),
                                   "bundle", "import", str(bundle)],
                                  check=True, capture_output=True, text=True,
                                  timeout=120, cwd=root)
        assert json.loads(imported.stdout)["root_run"] == run_id
        imported_run = subprocess.run([*command, "--home", str(imported_home),
                                       "show", run_id], check=True, capture_output=True,
                                      text=True, timeout=120, cwd=root)
        assert json.loads(imported_run.stdout)["status"] == "failed"
        subprocess.run([*command, "team", "--help"], check=True,
                       capture_output=True, text=True, cwd=root)
        check = subprocess.run([str(python), "-c",
            "from importlib.resources import files; p=files('mangekyo').joinpath('assets'); "
            "assert p.joinpath('demo-instruction.pdf').is_file(); "
            "assert files('mangekyo').joinpath('static', 'index.html').is_file()"],
            check=True, capture_output=True, text=True, cwd=root)
        assert check.returncode == 0
        print(f"Wheel smoke passed ({'module' if args.module else 'launcher'}): "
              f"{wheel.name}; {run_id} -> {recovered['run_id']}")


if __name__ == "__main__":
    main()
