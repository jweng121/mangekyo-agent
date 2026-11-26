"""Exercise the keyless SQL correction with the public Git-like CLI commands."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(".mangekyo-sql-cli-demo"))
    parser.add_argument("--step-delay", type=float, default=0,
                        help="Pause between demo graph nodes so dashboard updates are visible")
    args = parser.parse_args()
    if args.step_delay < 0 or args.step_delay > 10:
        parser.error("--step-delay must be between 0 and 10 seconds")
    home = args.home.resolve()
    project = home / ("sql-cli-project-" + uuid.uuid4().hex[:8])
    project.mkdir(parents=True)
    (project / "pyproject.toml").write_text('[project]\ndependencies = ["langgraph"]\n')
    model = project / "active-sql-model.json"
    model.write_text(json.dumps({"version": "v1", "table_for_bookings": "invoices"}))
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
    env["MANGEKYO_SQL_MODEL"] = str(model)
    env["MANGEKYO_SQL_STEP_DELAY"] = str(args.step_delay)
    os.environ["MANGEKYO_SQL_STEP_DELAY"] = str(args.step_delay)
    prefix = [sys.executable, "-m", "mangekyo", "--home", str(home)]

    def cli(*argv: str, code: int = 0) -> str:
        result = subprocess.run([*prefix, *argv], cwd=project, env=env,
                                text=True, capture_output=True, check=False)
        if result.returncode != code:
            raise RuntimeError(f"mangekyo {' '.join(argv)} returned {result.returncode}: "
                               f"{result.stdout[-1000:]} {result.stderr[-1000:]}")
        return result.stdout.strip()

    detected = json.loads(cli("add", ".", "--graph",
                              "sql=mangekyo.examples.sql_agent:build_graph"))
    assert detected["integration"] == "langgraph"
    assert detected["capabilities"]["live_resume"] is True
    config_file = project / ".mangekyo-agent.json"
    config = json.loads(config_file.read_text())
    config["current_model"] = {"version": "v1", "artifact": model.name}
    pipeline = ROOT / "scripts" / "sql_model_pipeline.py"
    config["push"] = {stage: [sys.executable, str(pipeline), stage]
                      for stage in ("trainer", "evaluator", "activator")}
    config_file.write_text(json.dumps(config, indent=2) + "\n")
    cli("run", "--", sys.executable, str(ROOT / "scripts" / "sql_cli_agent.py"))
    run_id = json.loads(cli("log"))["runs"][0]["id"]
    source = json.loads(cli("show", run_id))
    assert source["status"] == "completed" and source["adapter"] == "langgraph"
    table_event = next(e for e in source["events"] if e["kind"] == "tool" and
                       e["payload"].get("payload", {}).get("name") == "select_table")
    tool_case = project / "table-case.json"
    tool_case.write_text(json.dumps({"event_id": table_event["id"],
                                    "expected": {"payload": {"result": {"table": "bookings"}}}}))
    assert json.loads(cli("check", run_id, "--case", str(tool_case), code=2))["outcome"] == "failed"
    diagnosis = json.loads(cli("mark", run_id, "--event", table_event["id"],
                               "--reason", "Bookings question selected invoices"))
    outcome_case = project / "outcome-case.json"
    outcome_case.write_text(json.dumps({"expected": {"output": {"table": "bookings", "count": 3}}}))
    failed = json.loads(cli("check", run_id, "--case", str(outcome_case), code=2))
    from mangekyo.langgraph_api import LangGraphApi

    LangGraphApi(home).post(f"/api/v1/runs/{run_id}/flags", {
        "reason": "The agent selected invoices for a bookings question",
        "expected": {"table": "bookings", "count": 3}})
    source = json.loads(cli("show", run_id))
    assert source["outcome"] == "failed" and source["status"] == "completed"
    snapshot = next(s for s in source["snapshots"] if s["name"] == "after-choose")
    correction_file = project / "correction.json"
    correction_file.write_text('{"selected_table":"bookings"}')
    branch = "fix-" + run_id
    cli("branch", run_id, "--at", snapshot["id"], "-m", branch,
        "--correction-file", str(correction_file))
    corrected = json.loads(cli("resume", branch))
    passed = json.loads(cli("check", corrected["run_id"], "--case", str(outcome_case)))

    # The benchmark is an API operation; it compares the branch to a fresh
    # corrected run and saves its measurements for `mangekyo diff`.
    os.environ["MANGEKYO_PROJECT_CONFIG"] = str(config_file)
    os.environ["MANGEKYO_SQL_MODEL"] = str(model)
    _, measured = LangGraphApi(home).post(f"/api/v1/branches/{branch}/benchmark", {
        "price_per_million_usd": {"input": 1, "cached_input": 0,
                                  "cache_write": 0, "output": 1}})
    compared = json.loads(cli("diff", run_id, branch))
    committed = json.loads(cli("commit", branch))
    pushed = json.loads(cli("push", committed["commit_id"], "--project", "."))
    report = {"store": str(home), "project": str(project), "source_run": run_id,
              "source_execution": source["status"], "source_outcome": failed["outcome"],
              "diagnosis": diagnosis["classification"],
              "corrected_run": corrected["run_id"], "corrected_outcome": passed["outcome"],
              "skipped_steps": compared["skipped_steps"],
              "tool_calls_avoided": measured["tool_calls_avoided"],
              "measured_cost": compared["measured_cost"] is not None,
              "commit_id": committed["commit_id"],
              "model_version": pushed["model_version"],
              "held_out_passed": pushed["evaluation"]["held_out_passed"]}
    print(json.dumps(report, indent=2))
    return 0 if (report["diagnosis"] == "verified" and
                 report["corrected_outcome"] == "passed" and
                 report["measured_cost"] and report["model_version"] == "v2") else 1


if __name__ == "__main__":
    raise SystemExit(main())
