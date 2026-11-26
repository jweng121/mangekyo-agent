"""A real file-reading graph can fork without repeating completed tool work."""

from __future__ import annotations

import json

from mangekyo.store import Store


RATES = {"input": 1.0, "cached_input": .1, "cache_write": 1.25, "output": 2.0}


def _run(client, workspace, task):
    status, registered = client.post("/api/v1/langgraph/runs", {
        "graph": "file_invoice", "task_id": task, "thread_id": task,
        "label": "Review invoice from workspace", "input": {"workspace": str(workspace)},
    })
    assert status == 201, registered
    run_id = registered["run_id"]
    status, result = client.post(f"/api/v1/langgraph/runs/{run_id}/execute", {})
    assert status == 200, result
    return run_id, result


def _branch(client, run_id, snapshot_id, name):
    status, branch = client.post(f"/api/v1/runs/{run_id}/branches", {
        "snapshot_id": snapshot_id, "name": name,
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status == 201, branch
    return branch["branch_id"]


def test_file_tool_reads_are_recorded_and_skipped_on_resume(langgraph_api, tmp_path):
    client, _ = langgraph_api
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "invoice.json").write_text(json.dumps({
        "invoice_id": "INV-42", "supplier_id": "supplier-7",
        "proposed_account": "WRONG-ACCOUNT",
    }), encoding="utf-8")
    (workspace / "suppliers.csv").write_text(
        "supplier_id,approved_account\nsupplier-7,SAFE-ACCOUNT\n", encoding="utf-8",
    )

    run_id, original = _run(client, workspace, "file-invoice-42")
    assert original["output"]["supplier_account"] == "WRONG-ACCOUNT"
    detail = client.get(f"/api/v1/runs/{run_id}")[1]
    reads = [event for event in detail["events"] if event["kind"] == "tool"]
    assert {event["payload"]["payload"]["path"] for event in reads} == {
        "invoice.json", "suppliers.csv",
    }
    assert {event["payload"]["payload"]["cache_status"] for event in reads} == {"miss"}
    assert all(len(event["payload"]["payload"]["sha256"]) == 64 for event in reads)
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-load")
    assert client.post(f"/api/v1/runs/{run_id}/flags", {
        "reason": "Proposed account differs from supplier register",
        "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })[0] == 200
    branch_id = _branch(client, run_id, checkpoint["id"], "correct-file-invoice")
    status, child = client.post(f"/api/v1/branches/{branch_id}/resume", {})
    assert status == 200, child
    assert child["output"]["supplier_account"] == "SAFE-ACCOUNT"
    assert child["skipped_steps"] == ["load_documents"]
    child_detail = client.get(f"/api/v1/runs/{child['run_id']}")[1]
    assert not [event for event in child_detail["events"] if event["kind"] == "tool"]
    status, report = client.post(f"/api/v1/branches/{branch_id}/benchmark", {
        "price_per_million_usd": RATES,
    })
    assert status == 200, report
    assert report["saving_demonstrated"] is True
    assert report["duplicate_side_effects"] == 0
    assert report["skipped_step_saving_usd"] > 0
    assert report["cold"]["tool_calls"] == 2
    assert report["branch"]["tool_calls"] == 0
    assert report["tool_calls_avoided"] == 2
    cold_detail = client.get(f"/api/v1/runs/{report['cold']['run_id']}")[1]
    cold_reads = [event for event in cold_detail["events"] if event["kind"] == "tool"]
    assert len(cold_reads) == 2
    assert {event["payload"]["payload"]["cache_status"] for event in cold_reads} == {"hit"}


def test_file_graph_blocks_action_completed_after_checkpoint(langgraph_api, tmp_path):
    client, home = langgraph_api
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "invoice.json").write_text(json.dumps({
        "invoice_id": "INV-42", "supplier_id": "supplier-7",
        "proposed_account": "WRONG-ACCOUNT",
    }), encoding="utf-8")
    (workspace / "suppliers.csv").write_text(
        "supplier_id,approved_account\nsupplier-7,SAFE-ACCOUNT\n", encoding="utf-8",
    )
    run_id, _ = _run(client, workspace, "file-invoice-side-effect")
    detail = client.get(f"/api/v1/runs/{run_id}")[1]
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-load")
    branch_id = _branch(client, run_id, checkpoint["id"], "blocked-file-invoice")
    status, _ = client.post(f"/api/v1/langgraph/runs/{run_id}/events", {
        "kind": "tool", "node": "external_action",
        "payload": {"action_key": "payment-42", "action_state": "completed"},
    })
    assert status == 201
    with Store(home) as store:
        before = len(store.runs())
    status, error = client.post(f"/api/v1/branches/{branch_id}/resume", {})
    assert status == 409, error
    assert "completed action" in error["error"].lower()
    with Store(home) as store:
        assert len(store.runs()) == before


def test_changed_source_file_blocks_checkpoint_reuse(langgraph_api, tmp_path):
    client, home = langgraph_api
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "invoice.json").write_text(json.dumps({
        "invoice_id": "INV-42", "supplier_id": "supplier-7",
        "proposed_account": "WRONG-ACCOUNT",
    }), encoding="utf-8")
    register = workspace / "suppliers.csv"
    register.write_text("supplier_id,approved_account\nsupplier-7,SAFE-ACCOUNT\n", encoding="utf-8")
    run_id, _ = _run(client, workspace, "file-invoice-changed")
    detail = client.get(f"/api/v1/runs/{run_id}")[1]
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-load")
    branch_id = _branch(client, run_id, checkpoint["id"], "stale-file-invoice")
    register.write_text("supplier_id,approved_account\nsupplier-7,NEW-ACCOUNT\n", encoding="utf-8")
    with Store(home) as store:
        before = len(store.runs())
    status, error = client.post(f"/api/v1/branches/{branch_id}/resume", {})
    assert status == 409, error
    assert "suppliers.csv changed" in error["error"]
    with Store(home) as store:
        assert len(store.runs()) == before


def test_file_graph_rejects_workspace_outside_operator_root(langgraph_api, tmp_path):
    client, _ = langgraph_api
    outside = tmp_path.parent / "outside-file-invoice"
    outside.mkdir(exist_ok=True)
    (outside / "invoice.json").write_text(json.dumps({
        "invoice_id": "INV-42", "supplier_id": "supplier-7",
        "proposed_account": "WRONG-ACCOUNT",
    }), encoding="utf-8")
    (outside / "suppliers.csv").write_text(
        "supplier_id,approved_account\nsupplier-7,SAFE-ACCOUNT\n", encoding="utf-8",
    )
    status, registered = client.post("/api/v1/langgraph/runs", {
        "graph": "file_invoice", "task_id": "outside-root", "thread_id": "outside-root",
        "label": "Outside operator root", "input": {"workspace": str(outside)},
    })
    assert status == 201, registered
    status, error = client.post(f"/api/v1/langgraph/runs/{registered['run_id']}/execute", {})
    assert status == 400, error
    assert "inside MANGEKYO_FILE_INVOICE_ROOT" in error["error"]
