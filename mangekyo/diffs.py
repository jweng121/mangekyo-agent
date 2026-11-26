"""Compare an original run with a corrected branch without inventing savings."""

from __future__ import annotations

from typing import Any

from .store import Store


def _last(events: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    return next((event for event in reversed(events) if event["kind"] == kind), None)


def _tool_steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps = []
    for event in events:
        if event["kind"] != "tool":
            continue
        payload = event["payload"]
        item = payload.get("payload", payload)
        steps.append({"event_id": event["id"], "node": payload.get("node"),
                      "name": item.get("name"), "input": item.get("input"),
                      "result": item.get("result"), "error": item.get("error")})
    return steps


def diff_branch(store: Store, run_id: str, branch_name: str) -> dict[str, Any]:
    branch = store.one("branches", branch_name)
    snapshot = store.one("snapshots", branch["source_snapshot"])
    if snapshot["run_id"] != run_id:
        raise ValueError("Branch does not belong to the selected run")
    child_id = branch["result_run"]
    if not child_id:
        raise ValueError("Branch has not been resumed")
    before = store.events(run_id)
    after = store.events(child_id)
    before_output = _last(before, "output")
    after_output = _last(after, "output")
    restore = _last(after, "restore")
    benchmark = _last(after, "branch_benchmark")
    source_state = store.context(snapshot["id"])
    child_snapshots = store.snapshots(child_id)
    corrected_state = store.context(child_snapshots[-1]["id"]) if child_snapshots else {}
    source_values = source_state.get("state", source_state)
    corrected_values = corrected_state.get("state", corrected_state)
    changed_state = {key: {"before": source_values.get(key), "after": corrected_values.get(key)}
                     for key in sorted(source_values.keys() | corrected_values.keys())
                     if source_values.get(key) != corrected_values.get(key)}
    return {"source_run": run_id, "branch": branch_name, "corrected_run": child_id,
            "source_snapshot": snapshot["id"],
            "changed_state": changed_state,
            "original_tool_steps": _tool_steps(before),
            "corrected_tool_steps": _tool_steps(after),
            "original_output": before_output["payload"] if before_output else None,
            "corrected_output": after_output["payload"] if after_output else None,
            "original_check": (_last(before, "eval_result") or {}).get("payload"),
            "corrected_check": (_last(after, "eval_result") or {}).get("payload"),
            "source_tool_calls": sum(e["kind"] == "tool" for e in before),
            "corrected_tool_calls": sum(e["kind"] == "tool" for e in after),
            "skipped_steps": (restore or {}).get("payload", {}).get("skipped_steps", []),
            "measured_cost": benchmark["payload"] if benchmark else None}
