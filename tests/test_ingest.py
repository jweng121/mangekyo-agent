import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mangekyo.cli import main
from mangekyo.ingest import ingest_run
from mangekyo.store import Store


def test_json_trace_can_be_inspected_and_checked(tmp_path, capsys):
    trace = {"schema_version": 1, "agent": "typescript-sql-agent", "label": "Revenue",
             "events": [
                 {"kind": "tool", "payload": {"name": "list_tables", "result": ["payments"]}},
                 {"kind": "snapshot", "name": "after-discovery",
                  "context": {"tables": ["payments"]}},
                 {"kind": "tool", "payload": {"name": "select_table", "result": "invoices"}},
                 {"kind": "output", "payload": {"output": {"table": "invoices"}}},
             ]}
    trace_file = tmp_path / "trace.json"
    trace_file.write_text(json.dumps(trace), encoding="utf-8")
    assert main(["--home", str(tmp_path / "store"), "ingest", str(trace_file)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["capabilities"]["live_resume"] is False
    with Store(tmp_path / "store") as store:
        events = store.events(result["run_id"])
        snapshots = store.snapshots(result["run_id"])
        assert events[-1]["snapshot_id"] == snapshots[0]["id"]
        assert store.context(snapshots[0]["id"])["tables"] == ["payments"]


def test_portable_trace_can_attach_to_launcher_run(tmp_path):
    with Store(tmp_path) as store:
        run_id = store.create_run("node-agent", "task", adapter="process")
        result = ingest_run(store, {"schema_version": 1, "run_id": run_id,
                                    "events": [{"kind": "model", "payload": {"output": "ok"}}]})
        assert result["run_id"] == run_id
        assert result["status"] == "running"
        assert len(store.runs()) == 1
        assert store.events(run_id)[0]["kind"] == "model"


def test_node_agent_imports_into_one_run(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node is unavailable")
    script = Path(__file__).resolve().parent.parent / "examples" / "node-sql-agent.js"
    completed = subprocess.run([sys.executable, "-m", "mangekyo", "--home", str(tmp_path),
                                "run", "--", "node", str(script)],
                               text=True, capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    with Store(tmp_path) as store:
        runs = store.runs()
        assert len(runs) == 1
        assert runs[0]["status"] == "completed"
        events = store.events(runs[0]["id"])
        assert any(event["kind"] == "tool" and
                   event["payload"]["name"] == "select_table" for event in events)
