import json
import sys
import uuid
from pathlib import Path

import pytest

from mangekyo.cli import main
from mangekyo.langgraph_api import LangGraphApi
from mangekyo.launch import launch
from mangekyo.project import add_project
from mangekyo.store import Store


def test_launched_langgraph_agent_keeps_one_run_and_snapshots(tmp_path, monkeypatch):
    pytest.importorskip("langgraph")
    project = tmp_path / "sql-project"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\ndependencies = ["langgraph"]\n')
    add_project(project, ["sql=mangekyo.examples.sql_agent:build_graph"])
    config_file = project / ".mangekyo-agent.json"
    config = json.loads(config_file.read_text())
    config["current_model"] = {"version": "v1", "artifact": "active-sql-model.json"}
    config_file.write_text(json.dumps(config))
    (project / "active-sql-model.json").write_text(
        '{"version":"v1","table_for_bookings":"invoices"}')
    monkeypatch.chdir(project)
    script = Path(__file__).resolve().parent.parent / "scripts" / "sql_cli_agent.py"
    with Store(tmp_path / "history") as store:
        assert launch(store, [sys.executable, str(script)]) == 0
        runs = store.runs()
        assert len(runs) == 1
        run = runs[0]
        assert run["adapter"] == "langgraph"
        kinds = [event["kind"] for event in store.events(run["id"])]
        assert kinds[0] == "launch" and kinds[-1] == "exit"
        assert "registration" in kinds and "tool" in kinds and "output" in kinds
        assert any(snap["name"] == "after-choose" for snap in store.snapshots(run["id"]))


def test_cli_check_branch_resume_diff_commit(tmp_path, monkeypatch, capsys):
    pytest.importorskip("langgraph")
    monkeypatch.setenv("MANGEKYO_LANGGRAPH_GRAPHS", json.dumps({
        "sql": "mangekyo.examples.sql_agent:build_graph"}))
    api = LangGraphApi(tmp_path)
    _, registered = api.post("/api/v1/langgraph/runs", {
        "graph": "sql", "task_id": "test", "thread_id": uuid.uuid4().hex,
        "label": "Count Toronto bookings", "input": {"question": "Count Toronto bookings"}})
    run_id = registered["run_id"]
    api.post(f"/api/v1/langgraph/runs/{run_id}/execute", {})
    _, detail = api.get(f"/api/v1/runs/{run_id}")
    snapshot = next(s for s in detail["snapshots"] if s["name"] == "after-choose")
    case = tmp_path / "case.json"
    case.write_text(json.dumps({"expected": {"output": {"table": "bookings", "count": 3}}}))
    correction = tmp_path / "correction.json"
    correction.write_text('{"selected_table":"bookings"}')
    prefix = ["--home", str(tmp_path)]
    assert main(prefix + ["check", run_id, "--case", str(case)]) == 2
    capsys.readouterr()
    assert main(prefix + ["branch", run_id, "--at", snapshot["id"], "-m", "fix",
                          "--correction-file", str(correction)]) == 0
    capsys.readouterr()
    assert main(prefix + ["resume", "fix"]) == 0
    child = json.loads(capsys.readouterr().out)
    assert main(prefix + ["check", child["run_id"], "--case", str(case)]) == 0
    capsys.readouterr()
    assert main(prefix + ["diff", run_id, "fix"]) == 0
    compared = json.loads(capsys.readouterr().out)
    assert compared["corrected_check"]["passed"] is True
    assert compared["changed_state"]["selected_table"] == {
        "before": "invoices", "after": "bookings"}
    assert any(step["name"] == "select_table" for step in compared["original_tool_steps"])
    assert main(prefix + ["commit", "fix"]) == 0
    assert json.loads(capsys.readouterr().out)["corrected_run"] == child["run_id"]
