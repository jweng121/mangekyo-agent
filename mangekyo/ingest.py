"""Language-neutral JSON run import for agents without a Python SDK."""

from __future__ import annotations

from typing import Any

from .store import Store


def ingest_run(store: Store, document: dict[str, Any]) -> dict[str, Any]:
    """Import a versioned trace. Imported checkpoints are inspectable, not live-resumable."""
    if document.get("schema_version") != 1:
        raise ValueError("Trace schema_version must be 1")
    attached_id = document.get("run_id")
    agent = document.get("agent")
    label = document.get("label")
    status = document.get("status", "completed")
    events = document.get("events")
    if attached_id is None:
        if not isinstance(agent, str) or not agent.strip():
            raise ValueError("Trace agent must be a nonempty string")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Trace label must be a nonempty string")
    elif not isinstance(attached_id, str):
        raise ValueError("Trace run_id must be a string")
    if status not in {"completed", "failed", "interrupted"}:
        raise ValueError("Invalid trace status")
    if not isinstance(events, list) or not events:
        raise ValueError("Trace events must be a nonempty list")
    for item in events:
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
            raise ValueError("Each trace event needs a kind")
        if item["kind"] == "snapshot":
            if not isinstance(item.get("name"), str) or not isinstance(item.get("context"), dict):
                raise ValueError("Snapshot needs a name and context object")
        elif not isinstance(item.get("payload"), dict):
            raise ValueError("Trace event payload must be an object")
    if attached_id is None:
        run_id = store.create_run(agent, label, adapter="json-trace")
    else:
        if store.one("runs", attached_id)["status"] != "running":
            raise ValueError("Can only attach a trace to a running run")
        run_id = attached_id
    snapshots = store.snapshots(run_id)
    parent = snapshots[-1]["id"] if snapshots else None
    for item in events:
        if item["kind"] == "snapshot":
            parent = store.snapshot(run_id, item["name"], item["context"], parent_id=parent,
                                    adapter="json-trace")
        else:
            store.event(run_id, item["kind"], item["payload"], parent)
    if attached_id is None:
        store.status(run_id, status)
    return {"run_id": run_id, "status": store.one("runs", run_id)["status"],
            "events": len(events),
            "capabilities": {"trace": True, "checkpoint_inspection": True,
                             "live_resume": False}}
