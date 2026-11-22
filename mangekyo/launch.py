"""Launch a command and identify its execution in local run history."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .store import Store


def agent_name(command: list[str]) -> str:
    name = Path(command[0]).stem
    if name.lower() in {"python", "python3", "py", "node"} and len(command) > 1:
        for index, arg in enumerate(command[1:], 1):
            if arg in {"-c", "-e"}:
                return name
            if arg == "-m" and index + 1 < len(command):
                return command[index + 1]
            if not arg.startswith("-"):
                return Path(arg).stem
    return name


def launch(store: Store, command: list[str], label: str | None = None) -> int:
    if not command:
        raise ValueError("Provide a command after --, for example: mangekyo run -- python agent.py")
    if command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("Provide a command after --")

    name = agent_name(command)
    run_id = store.create_run(name, label or " ".join(command), adapter="process")
    store.event(run_id, "launch", {"argv": command, "cwd": str(Path.cwd()), "agent": name})
    print(f"Mangekyo recording {run_id} ({name})", flush=True)
    env = os.environ.copy()
    env["MANGEKYO_RUN_ID"] = run_id
    env["MANGEKYO_HOME"] = str(store.path)
    try:
        process = subprocess.Popen(command, env=env)
        store.event(run_id, "process", {"pid": process.pid})
        try:
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            code = process.wait()
            store.event(run_id, "interrupted", {"exit_code": code})
            store.status(run_id, "interrupted")
            return 130
    except OSError as exc:
        store.event(run_id, "error", {"message": str(exc)})
        store.status(run_id, "failed")
        raise
    store.event(run_id, "exit", {"exit_code": code})
    store.status(run_id, "completed" if code == 0 else "failed")
    print(f"Mangekyo run {run_id} exited {code}", flush=True)
    return code
