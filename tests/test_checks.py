import json

from mangekyo.checks import check_run
from mangekyo.cli import main
from mangekyo.diagnosis import mark_divergence
from mangekyo.store import Store


def test_completed_run_can_fail_outcome_check(tmp_path, capsys):
    with Store(tmp_path) as store:
        run_id = store.create_run("sql-agent", "Revenue question")
        decision_id = store.event(run_id, "tool", {
            "name": "select_table", "result": {"table": "invoices"}})
        store.event(run_id, "output", {"output": {"revenue": 100}})
        store.status(run_id, "completed")
        result = check_run(store, run_id, {
            "event_id": decision_id,
            "expected": {"result": {"table": "payments"}},
        })
        assert result["execution_status"] == "completed"
        assert result["outcome"] == "failed"
        assert result["source_event_id"] == decision_id
        assert store.one("runs", run_id)["status"] == "completed"
        assert store.events(run_id)[-1]["kind"] == "eval_result"
        diagnosis = mark_divergence(store, run_id, decision_id, "Wrong table")
        assert diagnosis["classification"] == "verified"

    case_file = tmp_path / "case.json"
    case_file.write_text(json.dumps({"expected": {"output": {"revenue": 100}}}))
    assert main(["--home", str(tmp_path), "check", run_id, "--case", str(case_file)]) == 0
    assert json.loads(capsys.readouterr().out)["outcome"] == "passed"
