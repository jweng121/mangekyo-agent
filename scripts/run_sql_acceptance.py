"""Run the keyless wrong-table, fork, eval, commit, and local-model push flow."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mangekyo.checks import check_run
from mangekyo.commits import commit_branch
from mangekyo.diagnosis import mark_divergence
from mangekyo.langgraph_api import LangGraphApi
from mangekyo.project import add_project
from mangekyo.push import push_commit
from mangekyo.store import Store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(".mangekyo-sql-demo"))
    args = parser.parse_args()
    home = args.home.resolve()
    project = home / ("sql-agent-" + uuid.uuid4().hex[:8])
    project.mkdir(parents=True)
    config = add_project(project)
    model_file = project / "active-sql-model.json"
    model_file.write_text(json.dumps({"version": "v1", "table_for_bookings": "invoices"}))
    config_data = json.loads(Path(config["config"]).read_text())
    config_data["current_model"] = {"version": "v1", "artifact": model_file.name}
    pipeline = Path(__file__).with_name("sql_model_pipeline.py")
    config_data["push"] = {stage: [sys.executable, str(pipeline), stage]
                           for stage in ("trainer", "evaluator", "activator")}
    Path(config["config"]).write_text(json.dumps(config_data, indent=2) + "\n")
    os.environ["MANGEKYO_SQL_MODEL"] = str(model_file)
    os.environ["MANGEKYO_LANGGRAPH_GRAPHS"] = json.dumps({
        "sql": "mangekyo.examples.sql_agent:build_graph"})
    api = LangGraphApi(home)
    _, registered = api.post("/api/v1/langgraph/runs", {
        "graph": "sql", "task_id": "sql-demo", "thread_id": uuid.uuid4().hex,
        "label": "Count Toronto bookings", "input": {"question": "Count Toronto bookings"}})
    run_id = registered["run_id"]
    _, original = api.post(f"/api/v1/langgraph/runs/{run_id}/execute", {})
    expected = {"output": {"table": "bookings", "count": 3}}
    with Store(home) as store:
        table_event = next(event for event in store.events(run_id)
                           if event["kind"] == "tool" and
                           event["payload"].get("payload", {}).get("name") == "select_table")
        check_run(store, run_id, {"event_id": table_event["id"],
                                  "expected": {"payload": {"result": {"table": "bookings"}}}})
        diagnosis = mark_divergence(store, run_id, table_event["id"],
                                    "Bookings question used the invoices table")
        failed = check_run(store, run_id, {"expected": expected})
    api.post(f"/api/v1/runs/{run_id}/flags", {
        "reason": "The agent selected invoices for a bookings question",
        "expected": expected["output"]})
    _, detail = api.get(f"/api/v1/runs/{run_id}")
    source = next(s for s in detail["snapshots"] if s["name"] == "after-choose")
    branch_name = "correct-table-" + run_id
    api.post(f"/api/v1/runs/{run_id}/branches", {
        "snapshot_id": source["id"], "name": branch_name,
        "correction": {"selected_table": "bookings"}})
    _, corrected = api.post(f"/api/v1/branches/{branch_name}/resume", {})
    with Store(home) as store:
        passed = check_run(store, corrected["run_id"], {"expected": expected})
    _, comparison = api.post(f"/api/v1/branches/{branch_name}/benchmark", {
        "price_per_million_usd": {"input": 1, "cached_input": 0,
                                  "cache_write": 0, "output": 1}})
    with Store(home) as store:
        saved = commit_branch(store, branch_name)
        pushed = push_commit(store, saved["commit_id"], project)
    report = {"store": str(home), "project": str(project), "source_run": run_id,
              "source_output": original["output"], "source_check": failed["outcome"],
              "first_wrong_event": diagnosis["source_event_id"],
              "diagnosis": diagnosis["classification"],
              "corrected_run": corrected["run_id"], "corrected_output": corrected["output"],
              "corrected_check": passed["outcome"],
              "skipped_steps": corrected["skipped_steps"],
              "tool_calls_avoided": comparison["tool_calls_avoided"],
              "model_saving_usd": comparison["net_model_saving_usd"],
              "model_saving_basis": "Deterministic fixture usage at illustrative prices",
              "commit_id": saved["commit_id"], "pushed_model_version": pushed["model_version"],
              "held_out_passed": pushed["evaluation"]["held_out_passed"]}
    print(json.dumps(report, indent=2))
    return 0 if (failed["outcome"] == "failed" and passed["outcome"] == "passed" and
                 comparison["saving_demonstrated"] and pushed["model_version"] == "v2") else 1


if __name__ == "__main__":
    raise SystemExit(main())
