"""Portable, deterministic outcome checks over recorded run events."""

from __future__ import annotations

from typing import Any

from .store import Store


def outcome_from_events(events: list[dict[str, Any]]) -> str:
    checks = [event for event in events if event["kind"] == "eval_result"]
    if not checks:
        return "unreviewed"
    return "passed" if all(event["payload"].get("passed") is True for event in checks) else "failed"


def _matches(actual: Any, expected: Any) -> bool:
    """An expected object may assert only the fields that matter."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _matches(actual[key], value) for key, value in expected.items()
        )
    return actual == expected


def check_run(store: Store, run_id: str, case: dict[str, Any]) -> dict[str, Any]:
    """Check a final result or a specific event without altering process status.

    The JSON case is language independent. A caller may select an event by ID,
    or the latest event of a kind (``output`` by default). ``expected`` is
    compared as a partial object to the event payload.
    """
    run = store.one("runs", run_id)
    if "expected" not in case or not isinstance(case["expected"], dict):
        raise ValueError("Check case needs an expected object")
    event_id = case.get("event_id")
    kind = case.get("kind", "output")
    if event_id is not None and not isinstance(event_id, str):
        raise ValueError("event_id must be a string")
    if not isinstance(kind, str) or not kind:
        raise ValueError("kind must be a nonempty string")
    events = store.events(run_id)
    if event_id:
        selected = next((event for event in events if event["id"] == event_id), None)
    else:
        selected = next((event for event in reversed(events) if event["kind"] == kind), None)
    if selected is None:
        raise ValueError(f"No matching {kind} event in run {run_id}")
    passed = _matches(selected["payload"], case["expected"])
    result = {"run_id": run_id, "execution_status": run["status"],
              "outcome": "passed" if passed else "failed", "passed": passed,
              "source_event_id": selected["id"], "source_event_seq": selected["seq"],
              "observed": selected["payload"], "case": case}
    result["result_event_id"] = store.event(run_id, "eval_result", result,
                                            selected["snapshot_id"])
    return result
