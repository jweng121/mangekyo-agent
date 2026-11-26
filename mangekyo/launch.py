"""Launch a command and identify its execution in local run history."""

from __future__ import annotations

import os
import json
import subprocess
import sys
import threading
from pathlib import Path

from .store import Store
from .project import CONFIG

OUTPUT_LIMIT = 256_000


def _stream_output(pipe, destination, chunks: list[bytes]) -> bool:
    retained = 0
    truncated = False
    try:
        while data := pipe.read(4096):
            if hasattr(destination, "buffer"):
                destination.buffer.write(data)
            else:
                destination.write(data.decode("utf-8", errors="replace"))
            destination.flush()
            available = OUTPUT_LIMIT - retained
            if available > 0:
                chunks.append(data[:available])
                retained += min(len(data), available)
            if len(data) > available:
                truncated = True
    finally:
        pipe.close()
    return truncated


def _collect_capture_failures(store: Store, run_id: str, path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            failure = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(failure, dict) and isinstance(failure.get("stage"), str):
            store.event(run_id, "capture_error", {
                "stage": failure["stage"], "error_type": failure.get("error_type", "unknown")})
    path.unlink()


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


def launch(store: Store, command: list[str], label: str | None = None,
           *, capture_output: bool = False) -> int:
    if not command:
        raise ValueError("Provide a command after --, for example: mangekyo run -- python agent.py")
    if command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("Provide a command after --")

    name = agent_name(command)
    project_config = Path.cwd() / CONFIG
    configuration = None
    if project_config.is_file():
        configuration = json.loads(project_config.read_text(encoding="utf-8"))
        if not isinstance(configuration, dict) or configuration.get("schema_version") != 1:
            raise ValueError(f"Unsupported {CONFIG}")
    run_id = store.create_run(name, label or " ".join(command), adapter="process")
    store.event(run_id, "launch", {"argv": command, "cwd": str(Path.cwd()), "agent": name,
                                   "project_integration": configuration.get("integration")
                                   if configuration else None,
                                   "capabilities": configuration.get("capabilities")
                                   if configuration else None})
    print(f"Mangekyo recording {run_id} ({name})", flush=True)
    env = os.environ.copy()
    env["MANGEKYO_RUN_ID"] = run_id
    env["MANGEKYO_HOME"] = str(store.path)
    failure_path = store.path / "capture-failures" / f"{run_id}.jsonl"
    failure_path.parent.mkdir(parents=True, exist_ok=True)
    env["MANGEKYO_CAPTURE_FAILURES"] = str(failure_path)
    env["MANGEKYO_COMMAND_JSON"] = json.dumps(
        [sys.executable] if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "mangekyo"])
    if configuration:
        env["MANGEKYO_PROJECT_CONFIG"] = str(project_config)
        mode = configuration.get("instrumentation", {}).get("mode")
        if mode == "python-langchain-auto":
            package = Path(__file__).resolve().parent
            paths = [str(package / "bootstrap"), str(package.parent)]
            if env.get("PYTHONPATH"):
                paths.append(env["PYTHONPATH"])
            env["PYTHONPATH"] = os.pathsep.join(paths)
            env["MANGEKYO_AUTO_TRACE"] = mode
    try:
        process = subprocess.Popen(command, env=env,
                                   stdout=subprocess.PIPE if capture_output else None,
                                   stderr=subprocess.PIPE if capture_output else None)
        store.event(run_id, "process", {"pid": process.pid})
        chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
        truncation: dict[str, bool] = {}
        threads: list[threading.Thread] = []
        if capture_output:
            def drain(name: str, pipe, destination) -> None:
                truncation[name] = _stream_output(pipe, destination, chunks[name])

            for name, pipe, destination in (("stdout", process.stdout, sys.stdout),
                                             ("stderr", process.stderr, sys.stderr)):
                worker = threading.Thread(target=drain, args=(name, pipe, destination), daemon=True)
                worker.start()
                threads.append(worker)
        try:
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            code = process.wait()
            for worker in threads:
                worker.join()
            _collect_capture_failures(store, run_id, failure_path)
            if capture_output:
                store.event(run_id, "process_output", {
                    name: b"".join(chunks[name]).decode("utf-8", errors="replace") for name in chunks
                } | {"truncated": truncation})
            store.event(run_id, "interrupted", {"exit_code": code})
            store.status(run_id, "interrupted")
            return 130
    except OSError as exc:
        _collect_capture_failures(store, run_id, failure_path)
        store.event(run_id, "error", {"message": str(exc)})
        store.status(run_id, "failed")
        raise
    for worker in threads:
        worker.join()
    _collect_capture_failures(store, run_id, failure_path)
    if capture_output:
        store.event(run_id, "process_output", {
            name: b"".join(chunks[name]).decode("utf-8", errors="replace") for name in chunks
        } | {"truncated": truncation})
    store.event(run_id, "exit", {"exit_code": code})
    store.status(run_id, "completed" if code == 0 else "failed")
    print(f"Mangekyo run {run_id} exited {code}", flush=True)
    return code
