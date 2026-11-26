"""Describe the evidence actually present in one run."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .store import Store


def record_capture_failure(stage: str, exc: BaseException) -> None:
    """Leave a child-process failure for the launcher even when SQLite is unavailable."""
    path = os.environ.get("MANGEKYO_CAPTURE_FAILURES")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"stage": stage, "error_type": type(exc).__name__}) + "\n")
            stream.flush()
    except OSError:
        pass


def _values(event: dict[str, Any]) -> dict[str, Any]:
    payload = event["payload"]
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("payload")
    return nested if isinstance(nested, dict) else payload


def _field(events: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, Any]:
    observed = sum(any(key in _values(event) and _values(event)[key] is not None
                       for key in keys) for event in events)
    total = len(events)
    return {"status": "missing" if not observed else "captured" if observed == total else "partial",
            "observed": observed, "events": total}


def _tool_results(starts: list[dict[str, Any]], ends: list[dict[str, Any]]) -> dict[str, Any]:
    if not starts:
        return _field(ends, ("result", "output", "error"))
    started_ids = {_values(event).get("framework_run_id") for event in starts}
    ended_ids = {_values(event).get("framework_run_id") for event in ends
                 if any(key in _values(event) for key in ("result", "output", "error"))}
    matched = sum(_values(event).get("framework_run_id") in ended_ids for event in starts)
    other = [event for event in ends
             if _values(event).get("framework_run_id") not in started_ids]
    observed = matched + sum(any(key in _values(event) for key in ("result", "output", "error"))
                             for event in other)
    total = len(starts) + len(other)
    return {"status": "missing" if not observed else "captured" if observed == total else "partial",
            "observed": observed, "events": total}


def _checkpoint_support(store: Store, snapshot: dict[str, Any],
                        registration: dict[str, Any] | None) -> tuple[bool, str]:
    adapter = snapshot["adapter"]
    if adapter == "mangekyo.simulation" and snapshot["adapter_version"] == "1":
        if not snapshot["env_hash"]:
            return False, "No environment checkpoint"
        environment = store.get(snapshot["env_hash"])
        target = environment.get("target") if isinstance(environment, dict) else None
        if not isinstance(target, str):
            return False, "Simulation target is missing from the checkpoint"
        path = Path(target).resolve()
        expected = (store.path / "simulation" / snapshot["run_id"]).resolve()
        if path.parent != expected or not path.is_file():
            return False, "Simulation target is unavailable"
        return True, "Runtime and environment checkpoint present; resume rechecks actions"
    if adapter == "langgraph" and snapshot["adapter_version"] == "1":
        context = store.context(snapshot["id"])
        locator = context.get("graph_checkpoint")
        if not isinstance(locator, dict) or not locator.get("checkpoint_id") or not context.get("last_node"):
            return False, "No usable LangGraph checkpoint locator"
        run = store.one("runs", snapshot["run_id"])
        path = store.path / "langgraph" / f"{run['parent_run'] or snapshot['run_id']}.sqlite3"
        if not path.is_file():
            return False, "LangGraph checkpoint database is unavailable"
        if not isinstance(registration, dict):
            return False, "LangGraph runtime registration is missing"
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
            with SqliteSaver.from_conn_string(str(path)) as saver:
                if saver.get_tuple({"configurable": locator}) is None:
                    return False, "LangGraph checkpoint is unavailable"
        except Exception as exc:
            return False, f"LangGraph checkpoint check failed: {type(exc).__name__}"
        return True, "Runtime checkpoint present; resume rechecks graph compatibility, environment, and actions"
    return False, "No live resume adapter for this checkpoint"


def capture_report(store: Store, run_id: str, *, events: list[dict[str, Any]] | None = None,
                   snapshots: list[dict[str, Any]] | None = None,
                   artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Report observed capture, never advertised project capabilities."""
    store.one("runs", run_id)
    events = store.events(run_id) if events is None else events
    snapshots = store.snapshots(run_id) if snapshots is None else snapshots
    artifacts = store.artifacts(run_id) if artifacts is None else artifacts
    kinds = {event["kind"] for event in events}
    process = {"launch", "process", "exit", "interrupted"} & kinds
    if "launch" in process and "error" in kinds:
        process.add("error")
    if {"launch", "process"} <= process and ({"exit", "interrupted", "error"} & process):
        process_status = "captured"
    else:
        process_status = "partial" if process else "missing"
    models = [event for event in events if event["kind"] == "model"]
    tool_starts = [event for event in events if event["kind"] == "tool_start"]
    tools = [event for event in events if event["kind"] == "tool"]
    checkpoints = []
    registration = next((event["payload"] for event in events
                         if event["kind"] == "registration"), None)
    for snapshot in snapshots:
        supported, reason = _checkpoint_support(store, snapshot, registration)
        checkpoints.append({"snapshot_id": snapshot["id"], "runtime_backed": supported,
                            "reason": reason})
    failures = [_values(event) for event in events if event["kind"] == "capture_error"]
    backed = sum(item["runtime_backed"] for item in checkpoints)
    return {
        "basis": "Observed run events, snapshots, and artifacts; configured capabilities are ignored",
        "process_lifecycle": {"status": process_status, "observed_events": sorted(process)},
        "process_output": {"status": "captured" if "process_output" in kinds else "missing"},
        "model_inputs": _field(models, ("input", "request", "messages", "prompt")),
        "model_outputs": _field(models, ("result", "response", "output", "error")),
        "tool_calls": _field(tool_starts or tools, ("input", "args", "arguments")),
        "tool_results": _tool_results(tool_starts, tools),
        "context": {"status": "captured" if snapshots else "missing", "snapshots": len(snapshots)},
        "evidence": {"status": "captured" if artifacts else "missing", "artifacts": len(artifacts)},
        "restorable_checkpoints": {"status": "candidate" if backed else "missing",
                                    "runtime_backed": backed, "snapshots": checkpoints,
                                    "note": "Runtime-backed is not approval to resume; compatibility and side effects are rechecked at resume time."},
        "capture_failures": failures,
        "missing_data_note": "A missing field means it was not saved; it does not prove the agent made no such calls.",
    }
