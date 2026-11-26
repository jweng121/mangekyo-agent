"""Loopback LangGraph integration and measured branch comparison.

Graph factories are selected from an operator-owned allowlist. A factory takes
one LangGraph checkpointer and returns a compiled graph. Graph nodes can report
provider usage in a ``usage_items`` state update; this adapter never invents
token counts when a provider did not report them.
"""

from __future__ import annotations

import importlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .store import Store
from .project import CONFIG

ADAPTER = "langgraph"
ADAPTER_VERSION = "1"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _required_text(body: dict, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, f"{key} must be a nonempty string")
    return value.strip()


def _dict(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ApiError(400, f"{name} must be an object")
    return value


def _event(store: Store, run_id: str, kind: str) -> dict | None:
    return next((e for e in reversed(store.events(run_id)) if e["kind"] == kind), None)


def _registration(store: Store, run_id: str) -> dict:
    run = store.one("runs", run_id)
    if run["adapter"] != ADAPTER:
        raise ApiError(409, "Run is not a LangGraph run")
    event = _event(store, run_id, "registration")
    if not event:
        raise ApiError(409, "Run has no LangGraph registration")
    return event["payload"]


def _output(store: Store, run_id: str) -> dict | None:
    event = _event(store, run_id, "output")
    return event["payload"] if event else None


def _usage_events(store: Store, run_id: str) -> list[dict]:
    return [e["payload"]["usage"] for e in store.events(run_id)
            if e["kind"] == "model" and isinstance(e["payload"].get("usage"), dict)]


def saved_benchmarks(store: Store, run_id: str) -> list[dict]:
    """Read completed LangGraph comparisons without rerunning a graph or model."""
    run = store.one("runs", run_id)
    if run["adapter"] != ADAPTER:
        raise ValueError("Run is not a LangGraph run")
    root_id = run["parent_run"] or run_id
    reports = []
    for branch in store.branches():
        if not branch["result_run"]:
            continue
        snap = store.one("snapshots", branch["source_snapshot"])
        if snap["run_id"] != root_id:
            continue
        event = _event(store, branch["result_run"], "branch_benchmark")
        if event:
            reports.append(_with_cache_note(event["payload"]))
    return reports


def _with_cache_note(report: dict) -> dict:
    """Explain the reported cache delta, including reports saved before this field existed."""
    if "provider_cache_note" in report:
        return report
    cold = report.get("cold", {}).get("provider_usage", {})
    branch = report.get("branch", {}).get("provider_usage", {})
    cold_read = cold.get("cached_input_tokens")
    branch_read = branch.get("cached_input_tokens")
    if cold_read == branch_read == 0:
        note = ("Both corrected paths reported 0 provider cache-read tokens, so no "
                "prompt-cache discount was observed. Model cost differences came from "
                "different work and token usage, not provider prompt caching.")
    elif isinstance(cold_read, int) and isinstance(branch_read, int):
        note = (f"Provider cache-read tokens: cold {cold_read}, branch {branch_read}. "
                "The cache saving compares their input-token discounts at the configured rates; "
                "cache writes are priced separately in model cost.")
    else:
        note = "Provider cache-read usage was not reported for both paths; no cache saving is verified."
    return {**report, "provider_cache_note": note}


def _cost_of_usage(items: list[dict], rates: dict[str, float]) -> tuple[dict, float, float]:
    if not items:
        raise ApiError(409, "Provider usage is missing; cost saving cannot be verified")
    providers = {(item.get("provider"), item.get("model")) for item in items}
    if len(providers) != 1:
        raise ApiError(409, "Mixed provider or model usage cannot be priced as one run")
    totals = {"input_tokens": 0, "cached_input_tokens": 0,
              "cache_write_tokens": 0, "output_tokens": 0}
    for item in items:
        for key in totals:
            value = item.get(key)
            if not isinstance(value, int) or value < 0:
                raise ApiError(409, f"Provider did not report valid {key}")
            totals[key] += value
        if item["cached_input_tokens"] + item["cache_write_tokens"] > item["input_tokens"]:
            raise ApiError(409, "Cached and written input exceeds reported input tokens")
    ordinary = totals["input_tokens"] - totals["cached_input_tokens"] - totals["cache_write_tokens"]
    cost = (ordinary * rates["input"] + totals["cached_input_tokens"] * rates["cached_input"]
            + totals["cache_write_tokens"] * rates["cache_write"]
            + totals["output_tokens"] * rates["output"]) / 1_000_000
    cache_discount = totals["cached_input_tokens"] * (rates["input"] - rates["cached_input"]) / 1_000_000
    totals.update({"provider": next(iter(providers))[0], "model": next(iter(providers))[1]})
    return totals, cost, cache_discount


class LangGraphApi:
    def __init__(self, store_path: Path, *, project_config: Path | None = None):
        self.store_path = Path(store_path)
        project_config = Path(project_config or os.environ.get("MANGEKYO_PROJECT_CONFIG", Path.cwd() / CONFIG))
        configured = {}
        if project_config.is_file():
            configured = json.loads(project_config.read_text(encoding="utf-8")).get("langgraph_graphs", {})
        raw = os.environ.get("MANGEKYO_LANGGRAPH_GRAPHS", json.dumps(configured))
        try:
            self.graphs = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("MANGEKYO_LANGGRAPH_GRAPHS must contain a JSON object") from exc
        if not isinstance(self.graphs, dict) or not all(
            isinstance(key, str) and isinstance(value, str) and ":" in value
            for key, value in self.graphs.items()
        ):
            raise ValueError("MANGEKYO_LANGGRAPH_GRAPHS must map names to module:factory")
        self.lock = threading.RLock()

    def benchmarks_for_run(self, store: Store, run_id: str) -> list[dict]:
        """Return saved branch comparisons for the dashboard's run inspector."""
        return saved_benchmarks(store, run_id)

    def _factory(self, alias: str):
        spec = self.graphs.get(alias)
        if not spec:
            raise ApiError(400, f"Graph {alias!r} is not configured")
        module_name, attribute = spec.split(":", 1)
        try:
            module = importlib.import_module(module_name)
            factory = getattr(module, attribute)
        except (ImportError, AttributeError) as exc:
            raise ApiError(409, f"Configured graph factory {spec!r} is unavailable") from exc
        if not callable(factory):
            raise ApiError(409, f"Configured graph factory {spec!r} is not callable")
        return factory

    def _checkpointer_path(self, run_id: str) -> Path:
        folder = self.store_path / "langgraph"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{run_id}.sqlite3"

    def get(self, path: str) -> tuple[int, dict]:
        parts = [unquote(part) for part in path.strip("/").split("/")]
        with Store(self.store_path) as store:
            if len(parts) == 4 and parts[:3] == ["api", "v1", "runs"]:
                run_id = parts[3]
                run = store.one("runs", run_id)
                flag = _event(store, run_id, "review_flag")
                output = _output(store, run_id)
                events = store.events(run_id)
                for event in events:
                    if event["kind"] == "model":
                        event["usage"] = event["payload"].get("usage")
                return 200, {"run": run, "events": events, "snapshots": store.snapshots(run_id),
                             "output": output["output"] if output else None,
                             "review_status": "flagged" if flag else "unreviewed"}
            if len(parts) == 4 and parts[:3] == ["api", "v1", "snapshots"]:
                snap = store.one("snapshots", parts[3])
                context = store.context(snap["id"])
                return 200, {"snapshot": snap, **context}
            if len(parts) == 5 and parts[:3] == ["api", "v1", "branches"] and parts[4] == "benchmark":
                branch = store.one("branches", parts[3])
                if not branch["result_run"]:
                    raise ApiError(409, "Branch has not been resumed")
                saved = _event(store, branch["result_run"], "branch_benchmark")
                if not saved:
                    raise ApiError(404, "Branch has no benchmark yet")
                return 200, _with_cache_note(saved["payload"])
        raise ApiError(404, "Not found")

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        if not isinstance(body, dict):
            raise ApiError(400, "JSON body must be an object")
        parts = [unquote(part) for part in path.strip("/").split("/")]
        with self.lock, Store(self.store_path) as store:
            if parts == ["api", "v1", "langgraph", "runs"]:
                alias = _required_text(body, "graph")
                factory = self._factory(alias)
                registration = {"graph": alias, "task_id": _required_text(body, "task_id"),
                                "thread_id": _required_text(body, "thread_id"),
                                "input": _dict(body.get("input"), "input"),
                                "graph_version": getattr(factory, "graph_version", "unknown")}
                inherited = os.environ.get("MANGEKYO_RUN_ID")
                if inherited:
                    run = store.one("runs", inherited)
                    if run["status"] != "running" or run["adapter"] != "process":
                        raise ApiError(409, "Launcher run is not available for LangGraph registration")
                    if _event(store, inherited, "registration"):
                        raise ApiError(409, "Launcher run already has a LangGraph registration")
                    with store.db:
                        store.db.execute("UPDATE runs SET adapter=?, adapter_version=? WHERE id=?",
                                         (ADAPTER, ADAPTER_VERSION, inherited))
                    run_id = inherited
                else:
                    run_id = store.create_run(alias, _required_text(body, "label"),
                                              adapter=ADAPTER, adapter_version=ADAPTER_VERSION)
                store.event(run_id, "registration", registration)
                return 201, {"run_id": run_id, "adapter": ADAPTER, "status": "running",
                             "capabilities": {"trace": True, "checkpoint_inspection": True,
                                              "live_resume": bool(getattr(factory, "resume_safe", False)
                                                                  and callable(getattr(factory, "validate_checkpoint", None)))}}
            if len(parts) == 6 and parts[:4] == ["api", "v1", "langgraph", "runs"]:
                run_id, action = parts[4:]
                registration = _registration(store, run_id)
                if action == "events":
                    kind = _required_text(body, "kind")
                    if kind not in {"model", "tool", "error", "observation"}:
                        raise ApiError(400, "Unsupported event kind")
                    event_body = _dict(body.get("payload"), "payload")
                    payload = {"node": _required_text(body, "node"), "payload": event_body}
                    if "usage" in body:
                        payload["usage"] = _dict(body["usage"], "usage")
                    if kind == "tool" and ("action_key" in event_body or "action_state" in event_body):
                        key = _required_text(event_body, "action_key")
                        state = _required_text(event_body, "action_state")
                        if state not in {"intent", "completed", "failed"}:
                            raise ApiError(400, "Invalid action_state")
                        store.action(run_id, key, state, event_body.get("result"))
                    return 201, {"event_id": store.event(run_id, kind, payload)}
                if action == "checkpoints":
                    locator = _dict(body.get("graph_checkpoint"), "graph_checkpoint")
                    if locator.get("thread_id") != registration["thread_id"]:
                        raise ApiError(409, "Checkpoint thread does not match registered run")
                    _required_text(locator, "checkpoint_id")
                    context = {"graph_checkpoint": locator,
                               "state": _dict(body.get("state"), "state"),
                               "completed_steps": body.get("completed_steps", []),
                               "last_node": body.get("last_node")}
                    if not isinstance(context["completed_steps"], list):
                        raise ApiError(400, "completed_steps must be a list")
                    snapshot_id = store.snapshot(run_id, _required_text(body, "name"), context,
                                                 adapter=ADAPTER, adapter_version=ADAPTER_VERSION)
                    snap = store.one("snapshots", snapshot_id)
                    return 201, {"snapshot_id": snapshot_id, "manifest_hash": snap["manifest_hash"]}
                if action == "execute":
                    if store.one("runs", run_id)["status"] != "running" or _output(store, run_id):
                        raise ApiError(409, "Run has already executed")
                    return 200, self._execute(store, run_id, registration, registration["input"])
            if len(parts) == 5 and parts[:3] == ["api", "v1", "runs"]:
                run_id, action = parts[3:]
                if action == "flags":
                    _registration(store, run_id)
                    reason = _required_text(body, "reason")
                    expected = _dict(body.get("expected"), "expected")
                    store.event(run_id, "review_flag", {"reason": reason, "expected": expected})
                    return 200, {"run_id": run_id, "review_status": "flagged"}
                if action == "branches":
                    _registration(store, run_id)
                    snapshot_id = _required_text(body, "snapshot_id")
                    snap = store.one("snapshots", snapshot_id)
                    if (snap["run_id"] != run_id or snap["adapter"] != ADAPTER
                            or snap["adapter_version"] != ADAPTER_VERSION):
                        raise ApiError(409, "Snapshot does not belong to this LangGraph run")
                    name = _required_text(body, "name")
                    correction = _dict(body.get("correction"), "correction")
                    if not correction:
                        raise ApiError(400, "correction cannot be empty")
                    try:
                        store.one("branches", name)
                    except KeyError:
                        pass
                    else:
                        raise ApiError(409, "Branch name already exists")
                    store.branch(snapshot_id, name, correction)
                    return 201, {"branch_id": name, "source_snapshot": snapshot_id}
            if len(parts) == 5 and parts[:3] == ["api", "v1", "branches"]:
                branch_id, action = parts[3:]
                if action == "resume":
                    return 200, self._resume(store, branch_id)
                if action == "benchmark":
                    return 200, self._benchmark(store, branch_id, body)
        raise ApiError(404, "Not found")

    def _execute(self, store: Store, run_id: str, registration: dict, input_state: dict,
                 *, source_run: str | None = None, fork: dict | None = None,
                 correction: dict | None = None) -> dict:
        from langgraph.checkpoint.sqlite import SqliteSaver
        from .langgraph_tools import MangekyoToolHandler

        db_run = source_run or run_id
        path = self._checkpointer_path(db_run)
        started = time.perf_counter()
        checkpoint_ms = 0.0
        try:
            with SqliteSaver.from_conn_string(str(path)) as saver:
                graph = self._factory(registration["graph"])(saver)
                thread_id = registration["thread_id"]
                live_config = {"configurable": {"thread_id": thread_id}}
                if fork:
                    source_config = {"configurable": fork["graph_checkpoint"]}
                    if saver.get_tuple(source_config) is None:
                        raise ApiError(409, "LangGraph checkpoint is unavailable")
                    saved = graph.get_state(source_config)
                    if saved.config["configurable"].get("checkpoint_id") != fork["graph_checkpoint"]["checkpoint_id"]:
                        raise ApiError(409, "LangGraph checkpoint is unavailable")
                    config = graph.update_state(source_config, correction or {},
                                                as_node=fork["last_node"])
                    invocation = None
                else:
                    config = live_config
                    invocation = input_state
                config = {**config, "callbacks": [MangekyoToolHandler(store.path, run_id)]}
                for update in graph.stream(invocation, config, stream_mode="updates"):
                    for node, delta in update.items():
                        if not isinstance(delta, dict):
                            continue
                        store.event(run_id, "node", {"node": node})
                        for usage in delta.get("usage_items", []):
                            store.event(run_id, "model", {"node": node, "usage": usage})
                        for item in delta.get("tool_items", []):
                            if not isinstance(item, dict):
                                raise ApiError(409, "Graph tool_items must contain objects")
                            store.event(run_id, "tool", {"node": node, "payload": item})
                            if "action_key" in item or "action_state" in item:
                                key = _required_text(item, "action_key")
                                state = _required_text(item, "action_state")
                                if state not in {"intent", "completed", "failed"}:
                                    raise ApiError(409, "Graph reported invalid action_state")
                                store.action(run_id, key, state, item.get("result"))
                        snapshot_state = graph.get_state(live_config)
                        locator = snapshot_state.config["configurable"]
                        context = {"graph_checkpoint": {
                            "thread_id": locator["thread_id"],
                            "checkpoint_id": locator["checkpoint_id"],
                            "checkpoint_ns": locator.get("checkpoint_ns", "")},
                            "state": snapshot_state.values,
                            "completed_steps": snapshot_state.values.get("steps", []),
                            "last_node": node}
                        began = time.perf_counter()
                        store.snapshot(run_id, "after-" + node.split("_")[0], context,
                                       adapter=ADAPTER, adapter_version=ADAPTER_VERSION)
                        checkpoint_ms += (time.perf_counter() - began) * 1000
                final = graph.get_state(live_config).values
        except Exception as exc:
            store.event(run_id, "error", {"message": str(exc)})
            store.status(run_id, "failed")
            raise
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        output = final.get("output")
        store.event(run_id, "output", {"output": output, "elapsed_ms": elapsed_ms,
                                       "checkpoint_overhead_ms": round(checkpoint_ms, 3)})
        store.status(run_id, "completed")
        return {"run_id": run_id, "status": "completed", "output": output,
                "elapsed_ms": elapsed_ms}

    def _resume(self, store: Store, branch_id: str) -> dict:
        branch = store.one("branches", branch_id)
        if branch["result_run"]:
            raise ApiError(409, "Branch has already been resumed")
        snap = store.one("snapshots", branch["source_snapshot"])
        parent_id = snap["run_id"]
        if store.one("runs", parent_id)["status"] == "running":
            raise ApiError(409, "Original run is still active; stop it and reconcile actions before resuming")
        registration = _registration(store, parent_id)
        factory = self._factory(registration["graph"])
        if not getattr(factory, "resume_safe", False):
            raise ApiError(409, "Graph has not declared resume safe; no child run created")
        if getattr(factory, "graph_version", "unknown") != registration["graph_version"]:
            raise ApiError(409, "Graph version changed since the source run")
        context = store.context(snap["id"])
        if snap["adapter"] != ADAPTER or not context.get("last_node"):
            raise ApiError(409, "Checkpoint cannot resume this LangGraph adapter")
        validator = getattr(factory, "validate_checkpoint", None)
        if not callable(validator):
            raise ApiError(409, "Graph has no checkpoint environment validator; reconcile before resuming")
        try:
            validator(context)
        except (OSError, ValueError) as exc:
            raise ApiError(409, f"Checkpoint environment is incompatible: {exc}") from exc
        unresolved = store.db.execute(
            "SELECT action_key FROM actions WHERE run_id=? AND state IN ('intent','failed')", (parent_id,)
        ).fetchone()
        if unresolved:
            raise ApiError(409, f"Original run has unresolved action {unresolved[0]}")
        completed_after = store.db.execute(
            "SELECT action_key FROM actions WHERE run_id=? AND state='completed' AND created>?",
            (parent_id, snap["created"]),
        ).fetchone()
        if completed_after:
            raise ApiError(409, f"Original run completed action {completed_after[0]} after this checkpoint; reconcile before resuming")
        for event in store.events(parent_id):
            if event["created"] <= snap["created"] or event["kind"] != "tool":
                continue
            payload = event["payload"].get("payload")
            if isinstance(payload, dict) and payload.get("action_state") == "completed":
                raise ApiError(409, f"Original run completed action {payload.get('action_key')} after this checkpoint; reconcile before resuming")
        correction = store.get(branch["correction_hash"])
        from langgraph.checkpoint.sqlite import SqliteSaver
        with SqliteSaver.from_conn_string(str(self._checkpointer_path(parent_id))) as saver:
            graph = self._factory(registration["graph"])(saver)
            source_config = {"configurable": context["graph_checkpoint"]}
            if saver.get_tuple(source_config) is None:
                raise ApiError(409, "LangGraph checkpoint is unavailable; no child run created")
            saved = graph.get_state(source_config)
            if saved.config["configurable"].get("checkpoint_id") != context["graph_checkpoint"]["checkpoint_id"]:
                raise ApiError(409, "LangGraph checkpoint is unavailable; no child run created")
        try:
            child_id = store.claim_branch(branch_id, registration["graph"],
                                          "Recovery: " + branch_id, parent_run=parent_id,
                                          adapter=ADAPTER, adapter_version=ADAPTER_VERSION)
        except ValueError as exc:
            raise ApiError(409, str(exc)) from exc
        store.event(child_id, "registration", registration)
        store.event(child_id, "restore", {"source_snapshot": snap["id"],
                                          "skipped_steps": context["completed_steps"]})
        result = self._execute(store, child_id, registration, registration["input"],
                               source_run=parent_id, fork=context, correction=correction)
        return {**result, "parent_run": parent_id, "source_snapshot": snap["id"],
                "graph_checkpoint": context["graph_checkpoint"],
                "skipped_steps": context["completed_steps"]}

    def _benchmark(self, store: Store, branch_id: str, body: dict) -> dict:
        branch = store.one("branches", branch_id)
        child_id = branch["result_run"]
        if not child_id or store.one("runs", child_id)["status"] != "completed":
            raise ApiError(409, "Branch has not completed a resumed run")
        prior = _event(store, child_id, "branch_benchmark")
        if prior:
            if prior["payload"]["configured_price_per_million_usd"] != body.get("price_per_million_usd"):
                raise ApiError(409, "Benchmark already exists with different price rates")
            return _with_cache_note(prior["payload"])
        supplied = _dict(body.get("price_per_million_usd"), "price_per_million_usd")
        rates = {}
        for key in ("input", "cached_input", "cache_write", "output"):
            value = supplied.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ApiError(400, f"Invalid {key} price rate")
            rates[key] = float(value)
        snap = store.one("snapshots", branch["source_snapshot"])
        parent_id = snap["run_id"]
        context = store.context(snap["id"])
        registration = _registration(store, parent_id)
        factory = self._factory(registration["graph"])
        if not getattr(factory, "benchmark_safe", False):
            raise ApiError(409, "Graph has not declared a contained cold benchmark safe")
        if getattr(factory, "graph_version", "unknown") != registration["graph_version"]:
            raise ApiError(409, "Graph version changed since the source run")
        validator = getattr(factory, "validate_checkpoint", None)
        if validator is not None:
            try:
                validator(context)
            except (OSError, ValueError) as exc:
                raise ApiError(409, f"Checkpoint environment is incompatible: {exc}") from exc
        flag = _event(store, parent_id, "review_flag")
        if not flag or not flag["payload"].get("expected"):
            raise ApiError(409, "Flag the source run with an expected outcome before benchmarking")
        correction = store.get(branch["correction_hash"])
        child_items = _usage_events(store, child_id)
        source_items = _usage_events(store, parent_id)
        child_usage, child_cost, child_discount = _cost_of_usage(child_items, rates)
        source_usage, source_cost, _ = _cost_of_usage(source_items, rates)
        cold_id = store.create_run(registration["graph"], "Cold corrected baseline: " + branch_id,
                                   parent_run=parent_id, adapter=ADAPTER,
                                   adapter_version=ADAPTER_VERSION)
        cold_registration = {**registration, "thread_id": registration["thread_id"] + "-cold-" + cold_id}
        store.event(cold_id, "registration", cold_registration)
        cold_result = self._execute(store, cold_id, cold_registration,
                                    {**registration["input"], **correction})
        cold_items = _usage_events(store, cold_id)
        cold_usage, cold_cost, cold_discount = _cost_of_usage(cold_items, rates)
        if (cold_usage["provider"], cold_usage["model"]) != (child_usage["provider"], child_usage["model"]):
            raise ApiError(409, "Cold and branch runs used different providers or models")
        child_output = _output(store, child_id)
        cold_output = _output(store, cold_id)
        tool_counts = {key: sum(event["kind"] == "tool" for event in store.events(ident))
                       for key, ident in (("source", parent_id), ("cold", cold_id),
                                          ("branch", child_id))}
        skipped = (_event(store, child_id, "restore") or {"payload": {"skipped_steps": []}})["payload"]["skipped_steps"]
        skipped_items = [item for item in cold_items if item.get("node") in skipped]
        skipped_cost = _cost_of_usage(skipped_items, rates)[1] if skipped_items else 0.0
        original_actions = {row[0] for row in store.db.execute(
            "SELECT action_key FROM actions WHERE run_id=? AND state='completed'", (parent_id,))}
        branch_actions = {row[0] for row in store.db.execute(
            "SELECT action_key FROM actions WHERE run_id=? AND state='completed'", (child_id,))}
        duplicates = len(original_actions & branch_actions)
        saving = cold_cost - child_cost
        same_output = cold_result["output"] == child_output["output"]
        expected = flag["payload"]["expected"]
        correct = bool(expected and all(
            cold_result["output"].get(key) == value and child_output["output"].get(key) == value
            for key, value in expected.items()
        ))
        demonstrated = bool(same_output and correct and saving > 0 and duplicates == 0)
        report = {"branch_id": branch_id, "source_run": parent_id, "source_snapshot": snap["id"],
                  "graph_checkpoint": context["graph_checkpoint"],
                  "configured_price_per_million_usd": rates,
                  "source": {"run_id": parent_id, "provider_usage": source_usage,
                             "model_cost_usd": source_cost,
                             "tool_calls": tool_counts["source"]},
                  "cold": {"run_id": cold_id, "output": cold_output["output"],
                           "elapsed_ms": cold_output["elapsed_ms"],
                           "checkpoint_overhead_ms": cold_output["checkpoint_overhead_ms"],
                           "provider_usage": cold_usage, "model_cost_usd": cold_cost,
                           "tool_calls": tool_counts["cold"]},
                  "branch": {"run_id": child_id, "output": child_output["output"],
                             "elapsed_ms": child_output["elapsed_ms"],
                             "checkpoint_overhead_ms": child_output["checkpoint_overhead_ms"],
                             "provider_usage": child_usage, "model_cost_usd": child_cost,
                             "tool_calls": tool_counts["branch"]},
                  "net_model_saving_usd": saving,
                  "cold_total_model_cost_usd": source_cost + cold_cost,
                  "branch_total_model_cost_usd": source_cost + child_cost,
                  "wall_time_saved_ms": cold_output["elapsed_ms"] - child_output["elapsed_ms"],
                  "skipped_steps": skipped,
                  "tool_calls_avoided": max(0, tool_counts["cold"] - tool_counts["branch"]),
                  "skipped_step_saving_usd": skipped_cost,
                  "provider_cache_saving_usd": child_discount - cold_discount,
                  "duplicate_side_effects": duplicates,
                  "same_output": same_output,
                  "correct_outcome": correct,
                  "saving_demonstrated": demonstrated,
                  "verdict": "saving demonstrated" if demonstrated else "no saving demonstrated",
                  "note": "Incremental corrected-rerun model cost only; the original failed run is common to both paths. Rates are operator supplied, not verified billing."}
        report = _with_cache_note(report)
        store.event(child_id, "branch_benchmark", report)
        return report
