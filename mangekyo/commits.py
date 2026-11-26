"""Immutable accepted corrections with snapshot and regression evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .store import Store


def _latest_check(store: Store, run_id: str, passed: bool) -> dict[str, Any] | None:
    return next((event["payload"] | {"result_event_id": event["id"]}
                 for event in reversed(store.events(run_id))
                 if event["kind"] == "eval_result" and event["payload"].get("passed") is passed), None)


def commit_branch(store: Store, branch_name: str) -> dict[str, Any]:
    branch = store.one("branches", branch_name)
    source = store.one("snapshots", branch["source_snapshot"])
    child_id = branch["result_run"]
    if not child_id or store.one("runs", child_id)["status"] != "completed":
        raise ValueError("Branch needs a completed corrected run before commit")
    passed = _latest_check(store, child_id, True)
    if not passed:
        raise ValueError("Check the corrected run and confirm it passes before commit")
    snapshots = store.snapshots(child_id)
    if not snapshots:
        raise ValueError("Corrected run has no updated snapshot to commit")
    corrected = snapshots[-1]
    case = dict(passed["case"])
    case.pop("event_id", None)
    source_events = store.events(source["run_id"])
    if not any(event["kind"] == "eval_result" and
               event["payload"].get("passed") is False and
               {k: v for k, v in event["payload"].get("case", {}).items()
                if k != "event_id"} == case for event in source_events):
        raise ValueError("Original run must fail the same regression case before commit")
    registration = next((event["payload"] for event in source_events
                         if event["kind"] == "registration"), {})
    source_output = next((event["payload"] for event in reversed(source_events)
                          if event["kind"] == "output"), None)
    correction = store.get(branch["correction_hash"])
    payload = {"schema_version": 1, "branch": branch_name,
               "source_run": source["run_id"], "source_snapshot": source["id"],
               "corrected_run": child_id, "corrected_snapshot": corrected["id"],
               "corrected_manifest_hash": corrected["manifest_hash"],
               "correction": correction, "regression_case": case,
               "training_example": {"input": registration.get("input", case.get("input")),
                                    "observed": source_output, "expected": case["expected"],
                                    "correction": correction},
               "passing_check_event": passed["result_event_id"]}
    digest = store.put(payload)
    payload = store.get(digest)
    folder = store.path / "commits"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{digest}.json"
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError:
        pass
    return {"commit_id": digest, "path": str(target), **payload}


def read_commit(store: Store, commit_id: str) -> dict[str, Any]:
    if len(commit_id) != 64 or any(char not in "0123456789abcdef" for char in commit_id):
        raise ValueError("Invalid commit ID")
    path = Path(store.path) / "commits" / f"{commit_id}.json"
    if not path.is_file():
        raise ValueError(f"Commit not found: {commit_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if store.get(commit_id) != payload:
        raise ValueError("Commit content does not match its ID")
    return payload
