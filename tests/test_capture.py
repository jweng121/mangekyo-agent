"""A run's capture report reflects saved data rather than setup promises."""

from __future__ import annotations

import json
import sys

from mangekyo.capture import capture_report
from mangekyo.checks import check_run
from mangekyo.cli import main, show_item
from mangekyo.launch import launch
from mangekyo.store import Store
from conftest import execute_invoice_run


def test_process_run_does_not_claim_internal_capture(tmp_path):
    with Store(tmp_path / "history") as store:
        run_id = store.create_run("existing-agent", "task", adapter="process")
        store.event(run_id, "launch", {"capabilities": {"trace": True, "live_resume": True}})
        store.event(run_id, "process", {"pid": 123})
        store.event(run_id, "exit", {"exit_code": 0})
        report = show_item(store, run_id)["capture"]
        assert report["process_lifecycle"]["status"] == "captured"
        assert report["model_inputs"]["status"] == "missing"
        assert report["tool_results"]["status"] == "missing"
        assert report["context"]["status"] == "missing"
        assert report["restorable_checkpoints"]["status"] == "missing"


def test_partial_model_tool_and_evidence_capture_is_visible(tmp_path):
    with Store(tmp_path / "history") as store:
        run_id = store.create_run("agent", "task")
        store.event(run_id, "model", {"input": {"messages": ["hello"]}, "result": "hi"})
        store.event(run_id, "model", {"usage": {"input_tokens": 2}})
        store.event(run_id, "tool", {"payload": {"name": "read", "input": "a", "result": "b"}})
        store.event(run_id, "tool", {"payload": {"name": "write", "input": "c"}})
        event_id = store.event(run_id, "observation", {"text": "seen"})
        store.artifact(run_id, "page.png", b"\x89PNG\r\n\x1a\n" + b"0" * 16,
                       "image/png", event_id=event_id)
        store.snapshot(run_id, "context-only", {"messages": ["hello"]})
        report = capture_report(store, run_id)
        assert report["model_inputs"]["status"] == "partial"
        assert report["model_outputs"]["status"] == "partial"
        assert report["tool_calls"]["status"] == "captured"
        assert report["tool_results"]["status"] == "partial"
        assert report["evidence"]["artifacts"] == 1
        assert report["context"]["snapshots"] == 1
        assert report["restorable_checkpoints"]["runtime_backed"] == 0


def test_interrupted_tool_start_shows_call_without_result(tmp_path):
    with Store(tmp_path / "history") as store:
        run_id = store.create_run("agent", "task")
        store.event(run_id, "tool_start", {"name": "send_payment", "input": {"id": 42}})
        store.status(run_id, "interrupted")
        report = capture_report(store, run_id)
        assert report["tool_calls"]["status"] == "captured"
        assert report["tool_results"]["status"] == "missing"


def test_one_completed_and_one_pending_tool_is_partial(tmp_path):
    with Store(tmp_path / "history") as store:
        run_id = store.create_run("agent", "task")
        store.event(run_id, "tool_start", {"framework_run_id": "one", "input": "a"})
        store.event(run_id, "tool", {"framework_run_id": "one", "result": "done"})
        store.event(run_id, "tool_start", {"framework_run_id": "two", "input": "b"})
        report = capture_report(store, run_id)
        assert report["tool_calls"]["status"] == "captured"
        assert report["tool_results"]["status"] == "partial"
        assert report["tool_results"]["observed"] == 1
        assert report["tool_results"]["events"] == 2


def test_child_capture_failure_appears_in_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "agent.py"
    script.write_text("from mangekyo.capture import record_capture_failure\n"
                      "record_capture_failure('model:invoke', RuntimeError('secret'))\n",
                      encoding="utf-8")
    with Store(tmp_path / "history") as store:
        assert launch(store, [sys.executable, str(script)]) == 0
        run_id = store.runs()[0]["id"]
        report = capture_report(store, run_id)
        assert report["capture_failures"] == [{"stage": "model:invoke", "error_type": "RuntimeError"}]
        assert not (store.path / "capture-failures" / f"{run_id}.jsonl").exists()
        assert "secret" not in json.dumps(store.events(run_id))


def test_batch_output_can_be_checked_without_agent_instrumentation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "existing_agent.py"
    script.write_text("print('wrong-table')\n", encoding="utf-8")
    with Store(tmp_path / "history") as store:
        assert launch(store, [sys.executable, str(script)], capture_output=True) == 0
        run_id = store.runs()[0]["id"]
        output = next(event["payload"] for event in store.events(run_id)
                      if event["kind"] == "process_output")
        assert output["stdout"].strip() == "wrong-table"
        assert output["truncated"]["stdout"] is False
        assert capture_report(store, run_id)["process_output"]["status"] == "captured"
        result = check_run(store, run_id, {"kind": "process_output",
                                           "expected": {"stdout": "correct-table\n"}})
        assert result["passed"] is False
        assert result["execution_status"] == "completed"


def test_dashboard_reports_observed_langgraph_capture(langgraph_api):
    client, _ = langgraph_api
    run_id, _ = execute_invoice_run(client)
    status, detail = client.get(f"/api/run/{run_id}")
    assert status == 200
    report = detail["capture"]
    assert report["process_lifecycle"]["status"] == "missing"
    assert report["model_inputs"]["status"] == "missing"
    assert report["context"]["status"] == "captured"
    assert report["restorable_checkpoints"]["runtime_backed"] >= 1


def test_context_only_branch_does_not_suggest_live_resume(tmp_path, capsys):
    home = tmp_path / "history"
    with Store(home) as store:
        run_id = store.create_run("agent", "task")
        snapshot = store.snapshot(run_id, "before-decision", {"state": 1})
        store.status(run_id, "completed")
    assert main(["--home", str(home), "branch", snapshot, "-m", "review"]) == 0
    assert "live resume requires a compatible runtime adapter" in capsys.readouterr().out
    assert main(["--home", str(home), "resume", "review"]) == 1
    assert "no live resume adapter" in capsys.readouterr().err


def test_batch_output_is_bounded_and_literal_redaction_applies(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MANGEKYO_REDACT", "private-token")
    script = tmp_path / "noisy.py"
    script.write_text("print('private-token' + 'x' * 300000)\n", encoding="utf-8")
    with Store(tmp_path / "history") as store:
        assert launch(store, [sys.executable, str(script)], capture_output=True) == 0
        run_id = store.runs()[0]["id"]
        output = next(event["payload"] for event in store.events(run_id)
                      if event["kind"] == "process_output")
        assert output["truncated"]["stdout"] is True
        assert len(output["stdout"]) <= 256000
        assert "private-token" not in output["stdout"]
        assert "[REDACTED]" in output["stdout"]
    capsys.readouterr()
