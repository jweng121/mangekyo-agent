"""Record a reviewed candidate first divergence with explicit evidence status."""

from __future__ import annotations

from typing import Any

from .store import Store


def mark_divergence(store: Store, run_id: str, event_id: str, reason: str) -> dict[str, Any]:
    store.one("runs", run_id)
    events = store.events(run_id)
    target = next((event for event in events if event["id"] == event_id), None)
    if target is None:
        raise ValueError("Selected event does not belong to that run")
    if not reason.strip():
        raise ValueError("A reason is required")
    verified = any(event["kind"] == "eval_result" and
                   event["payload"].get("passed") is False and
                   event["payload"].get("source_event_id") == event_id
                   for event in events)
    result = {"source_event_id": event_id, "source_event_seq": target["seq"],
              "reason": reason.strip(), "classification": "verified" if verified else "suspected"}
    result["diagnosis_event_id"] = store.event(run_id, "diagnosis", result,
                                               target["snapshot_id"])
    return result
