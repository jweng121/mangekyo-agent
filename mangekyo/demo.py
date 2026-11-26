"""A contained, deterministic failure and recovery demonstration."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .store import Store

ADAPTER = "mangekyo.simulation"
ADAPTER_VERSION = "1"
FIXTURES = Path(__file__).parent / "assets"


def run_demo(store: Store) -> dict[str, str]:
    run_id = store.create_run("reference-agent", "Unsafe plan in disposable simulation",
                              adapter=ADAPTER, adapter_version=ADAPTER_VERSION)
    target = store.path / "simulation" / run_id / "target.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original", encoding="utf-8")
    started = time.perf_counter()
    store.event(run_id, "observation", {"text": "Target begins in its original state.", "path": str(target)})
    pdf_event = store.event(run_id, "read", {"name": "read-pdf", "document": "demo-instruction.pdf",
                                              "parsed": {"approved_value": "safe", "prohibited_value": "unsafe"}})
    pdf_id = store.artifact(run_id, "demo-instruction.pdf", (FIXTURES / "demo-instruction.pdf").read_bytes(),
                            "application/pdf", event_id=pdf_event,
                            parsed_text="Task: update the disposable target file\nApproved value: safe\nDo not write: unsafe",
                            source="bundled synthetic demo")
    store.annotate(pdf_id, 0, .10, .246, .40, .031, "Parsed approved value: safe")
    image_event = store.event(run_id, "read", {"name": "read-image", "document": "demo-target.png",
                                                "parsed": {"current_value": "original"}})
    image_id = store.artifact(run_id, "demo-target.png", (FIXTURES / "demo-target.png").read_bytes(),
                              "image/png", event_id=image_event, parsed_text="Current value: original",
                              source="bundled synthetic demo")
    store.annotate(image_id, 0, .10, .53, .79, .20, "Parsed current value: original")
    store.event(run_id, "decision", {"plan": "unsafe", "reason": "Deliberately wrong reference decision"})
    snap_id = store.snapshot(run_id, "before-action", {
        "instructions": "Only write 'safe' to the disposable target.",
        "messages": [{"role": "assistant", "content": "I will write unsafe."}],
        "memory": {"expected": "safe"},
        "runtime_state": {"next_step": "apply", "target": str(target), "completed_steps": ["observe", "plan"]},
        "evidence": {"source": "local-simulation", "observed": "original"},
    }, adapter=ADAPTER, adapter_version=ADAPTER_VERSION,
        environment={"target": str(target), "content": "original"})
    store.action(run_id, "write-target", "intent")
    target.write_text("unsafe", encoding="utf-8")
    store.action(run_id, "write-target", "completed", {"content": "unsafe"})
    store.event(run_id, "tool", {"name": "write-target", "input": "unsafe", "result": "written"}, snap_id)
    store.event(run_id, "error", {"message": "Verification failed: expected safe, got unsafe"}, snap_id)
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    store.event(run_id, "metrics", {"elapsed_ms": elapsed, "model_calls": 0, "provider_cached_tokens": None})
    store.status(run_id, "failed")
    return {"run_id": run_id, "snapshot_id": snap_id, "store_path": str(store.path),
            "target": str(target),
            "elapsed_ms": str(elapsed)}


def resume_unavailable_reason(store: Store, branch_name: str) -> str | None:
    branch = store.one("branches", branch_name)
    if branch["result_run"]:
        return f"Already resumed as {branch['result_run']}"
    snap = store.one("snapshots", branch["source_snapshot"])
    if (snap["adapter"], snap["adapter_version"]) != (ADAPTER, ADAPTER_VERSION):
        return "Checkpoint is incompatible with the simulation adapter"
    if not snap["env_hash"]:
        return "Checkpoint has agent context only; environment cannot be restored"
    correction = store.get(branch["correction_hash"])
    value = correction.get("replacement")
    if value != "safe":
        return "Reference adapter requires correction replacement='safe'"
    original_run = snap["run_id"]
    pending = store.db.execute("SELECT * FROM actions WHERE run_id=? AND state IN ('intent','failed')", (original_run,)).fetchall()
    if pending:
        return f"Original run has unresolved action {pending[0]['action_key']}; reconcile before resuming"
    environment = store.get(snap["env_hash"])
    source_target = Path(environment["target"]).resolve()
    expected_parent = (store.path / "simulation" / original_run).resolve()
    if source_target.parent != expected_parent:
        return "Environment target is outside the disposable simulation"
    if not source_target.exists():
        return "Simulation target is missing"
    completed = store.db.execute(
        "SELECT result_hash FROM actions WHERE run_id=? AND action_key='write-target' AND state='completed'",
        (original_run,)).fetchone()
    if completed:
        result = store.get(completed[0]) if completed[0] else None
        expected_current = result.get("content") if isinstance(result, dict) else None
        if not isinstance(expected_current, str) or source_target.read_text(encoding="utf-8") != expected_current:
            return "Simulation target changed since the recorded action; reconcile before resuming"
    elif source_target.read_text(encoding="utf-8") != environment["content"]:
        return "Simulation target changed without a recorded completed action; reconcile before resuming"
    return None


def resume(store: Store, branch_name: str) -> dict[str, Any]:
    reason = resume_unavailable_reason(store, branch_name)
    if reason:
        raise ValueError(reason + "; no action executed")
    branch = store.one("branches", branch_name)
    snap = store.one("snapshots", branch["source_snapshot"])
    original_run = snap["run_id"]
    correction = store.get(branch["correction_hash"])
    value = correction["replacement"]
    environment = store.get(snap["env_hash"])
    started = time.perf_counter()
    run_id = store.claim_branch(branch_name, "reference-agent", f"Recovery: {branch_name}",
                                parent_run=original_run, adapter=ADAPTER,
                                adapter_version=ADAPTER_VERSION)
    target = store.path / "simulation" / run_id / "target.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(environment["content"], encoding="utf-8")
    context = store.context(snap["id"])
    skipped = context["runtime_state"].get("completed_steps", [])
    store.event(run_id, "restore", {"source_snapshot": snap["id"], "environment": "restored",
                                     "skipped_steps": skipped})
    context["messages"] = context["messages"] + [{"role": "user", "content": "Write safe instead."}]
    context["runtime_state"] = context["runtime_state"] | {"branch": branch_name,
                                                            "target": str(target)}
    branch_environment = {"target": str(target), "content": environment["content"]}
    new_snap = store.snapshot(run_id, "corrected-before-action", context, parent_id=snap["id"],
                              adapter=ADAPTER, adapter_version=ADAPTER_VERSION,
                              environment=branch_environment)
    store.action(run_id, "corrected-write", "intent")
    target.write_text(value, encoding="utf-8")
    store.action(run_id, "corrected-write", "completed", {"content": value})
    store.event(run_id, "tool", {"name": "write-target", "input": value, "result": "written"}, new_snap)
    if target.read_text(encoding="utf-8") != "safe":
        store.status(run_id, "failed")
        raise RuntimeError("Reference verification failed")
    store.event(run_id, "verification", {"expected": "safe", "actual": value, "passed": True}, new_snap)
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    store.event(run_id, "metrics", {"elapsed_ms": elapsed, "model_calls": 0, "provider_cached_tokens": None})
    store.status(run_id, "completed")
    original_keys = {r[0] for r in store.db.execute("SELECT action_key FROM actions WHERE run_id=?", (original_run,))}
    resumed_keys = {r[0] for r in store.db.execute("SELECT action_key FROM actions WHERE run_id=?", (run_id,))}
    return {"run_id": run_id, "source_run": original_run, "source_snapshot": snap["id"],
            "target": str(target),
            "skipped_steps": len(skipped), "duplicate_actions": len(original_keys & resumed_keys),
            "elapsed_ms": elapsed}


def cold_baseline(store: Store, source_run: str) -> dict[str, Any]:
    """Run the corrected reference task from the beginning in another disposable target."""
    started = time.perf_counter()
    run_id = store.create_run("reference-agent", "Cold corrected baseline", parent_run=source_run,
                              adapter=ADAPTER, adapter_version=ADAPTER_VERSION)
    target = store.path / "simulation" / run_id / "target.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("original", encoding="utf-8")
    store.event(run_id, "observation", {"text": "Target begins in its original state."})
    store.event(run_id, "decision", {"plan": "safe"})
    store.action(run_id, "write-target", "intent")
    target.write_text("safe", encoding="utf-8")
    store.action(run_id, "write-target", "completed", {"content": "safe"})
    store.event(run_id, "tool", {"name": "write-target", "input": "safe", "result": "written"})
    store.event(run_id, "verification", {"expected": "safe", "actual": target.read_text(encoding="utf-8"), "passed": True})
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    store.event(run_id, "metrics", {"elapsed_ms": elapsed, "model_calls": 0, "provider_cached_tokens": None})
    store.status(run_id, "completed")
    return {"run_id": run_id, "elapsed_ms": elapsed}


def benchmark(store: Store, run_id: str, *, create_baseline: bool = False) -> dict[str, Any]:
    run = store.one("runs", run_id)
    if run["adapter"] != ADAPTER:
        raise ValueError("First-draft benchmark supports the reference simulation adapter")
    if create_baseline and not any(b["result_run"] and store.one("snapshots", b["source_snapshot"])["run_id"] == run_id
                                   for b in store.branches()):
        raise ValueError("Resume a corrected branch before benchmarking")
    existing_baseline = any(r["parent_run"] == run_id and r["label"] == "Cold corrected baseline"
                            and r["status"] == "completed" for r in store.runs())
    if create_baseline and not existing_baseline:
        cold_baseline(store, run_id)
    cold_runs = [r for r in store.runs() if r["parent_run"] == run_id and r["label"] == "Cold corrected baseline"]
    baselines = [{"run_id": r["id"], "elapsed_ms": next((e["payload"]["elapsed_ms"] for e in store.events(r["id"])
                    if e["kind"] == "metrics"), None)} for r in cold_runs]
    branches = [b for b in store.branches() if store.one("snapshots", b["source_snapshot"])["run_id"] == run_id]
    recovered = [b for b in branches if b["result_run"]]
    reports = []
    for branch in recovered:
        events = store.events(branch["result_run"])
        source_manifest = store.get(store.one("snapshots", branch["source_snapshot"])["manifest_hash"])
        child_snap = store.snapshots(branch["result_run"])[0]
        child_manifest = store.get(child_snap["manifest_hash"])
        shared = sum(source_manifest.get(k) == v for k, v in child_manifest.items())
        restore = next((e["payload"] for e in events if e["kind"] == "restore"), {})
        reports.append({"branch": branch["name"], "result_run": branch["result_run"],
                        "skipped_steps": len(restore.get("skipped_steps", [])),
                        "executed_actions": sum(e["kind"] == "tool" for e in events),
                        "elapsed_ms": next((e["payload"]["elapsed_ms"] for e in events if e["kind"] == "metrics"), None),
                        "shared_context_objects": shared,
                        "provider_cached_tokens": "not reported", "provider_cache_write_tokens": "not reported"})
        if baselines and reports[-1]["elapsed_ms"] is not None:
            reports[-1]["wall_time_saved_ms_vs_latest_cold"] = round(
                baselines[0]["elapsed_ms"] - reports[-1]["elapsed_ms"], 2)
    probes = [e["payload"] for e in store.events(run_id) if e["kind"] == "model_benchmark"]
    return {"source_run": run_id, "cold_baselines": baselines, "recovered": reports, "storage": store.stats(),
            "provider_probes": probes,
            "note": "Offline fixture has no model calls; provider probe metrics appear only after an explicit provider-backed run."}
