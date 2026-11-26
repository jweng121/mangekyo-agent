"""Project selection and launch configuration for the terminal UI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .project import CONFIG, add_project
from .setup_project import connect_project


SELECTION = "tui-project.json"
ENTRYPOINTS = ("agent.py", "run_agent.py", "main.py")


def project_python(project: Path) -> Path | None:
    for candidate in (project / ".venv" / "Scripts" / "python.exe",
                      project / ".venv" / "bin" / "python"):
        if candidate.is_file():
            return candidate
    return None


def active_project(store_path: Path) -> Path | None:
    marker = store_path / SELECTION
    if marker.is_file():
        try:
            path = Path(json.loads(marker.read_text(encoding="utf-8"))["project"])
            if path.is_dir():
                return path
        except (OSError, ValueError, KeyError, TypeError):
            pass
    cwd = Path.cwd()
    return cwd if (cwd / CONFIG).is_file() else None


def launch_config(project: Path) -> list[str] | None:
    path = project / CONFIG
    if not path.is_file():
        return None
    config = json.loads(path.read_text(encoding="utf-8"))
    value = config.get("tui_launch")
    if value is None:
        return None
    if not isinstance(value, list) or not value or not all(
            isinstance(arg, str) and arg for arg in value):
        raise ValueError("tui_launch must be a nonempty command array")
    return value


def save_launch_config(project: Path, command: list[str]) -> None:
    path = project / CONFIG
    config = json.loads(path.read_text(encoding="utf-8"))
    config["tui_launch"] = command
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_launch(project: Path, command: list[str]) -> list[str]:
    python = project_python(project)
    if "{python}" in command and python is None and getattr(sys, "frozen", False):
        raise ValueError("Project has no .venv Python; type launch with its Python command once")
    executable = str(python or sys.executable)
    return [executable if arg == "{python}" or (index == 0 and arg in {"python", "python3"}
                           and python is not None) else arg
            for index, arg in enumerate(command)]


def register_project(project: Path, store_path: Path,
                     graph_specs: list[str] | None = None) -> dict:
    project = project.expanduser().resolve()
    info = add_project(project, graph_specs)
    command = launch_config(project)
    if command is None:
        entrypoint = next((name for name in ENTRYPOINTS if (project / name).is_file()), None)
        if entrypoint:
            command = ["{python}", entrypoint]
            save_launch_config(project, command)
    python = project_python(project)
    sdk = ("using Mangekyo's Python interpreter" if command and command[0] == "{python}"
           and not getattr(sys, "frozen", False) else
           "no project .venv; process capture is available, internal tracing needs the SDK")
    if python:
        try:
            connect_project(project, verbose=False)
            sdk = f"connected to {python}"
        except (OSError, ValueError, RuntimeError) as exc:
            sdk = f"connection failed: {exc}"
    marker = store_path / SELECTION
    marker.write_text(json.dumps({"project": str(project)}) + "\n", encoding="utf-8")
    capture_note = ("Standard LangChain model/tool calls can be traced during launch; "
                    "custom calls and safe resume still need agent hooks."
                    if info["integration"] == "langgraph" else
                    "Launch captures the process; add RunRecorder or trace_call for internal calls and checkpoints.")
    return {"project": str(project), "integration": info["integration"],
            "launch": command, "sdk": sdk, "capabilities": info["capabilities"],
            "capture_note": capture_note}
