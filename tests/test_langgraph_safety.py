"""Unsafe or incompatible resumes must fail without creating a child run."""

from conftest import execute_invoice_run, register_invoice_run
from mangekyo.store import Store


def test_unresolved_action_blocks_resume(langgraph_api):
    client, home = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    status, detail = client.get(f"/api/v1/runs/{parent_id}")
    assert status == 200, detail
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    status, branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "must-block",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status == 201, branch
    with Store(home) as store:
        store.action(parent_id, "payment-42", "intent")
        before = len(store.runs())

    status, error = client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    assert status == 409, error
    assert "unresolved" in error["error"].lower()
    with Store(home) as store:
        assert len(store.runs()) == before
        assert store.one("branches", branch["branch_id"])["result_run"] is None


def test_completed_action_after_checkpoint_blocks_resume(langgraph_api):
    client, home = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    detail = client.get(f"/api/v1/runs/{parent_id}")[1]
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    status, event = client.post(f"/api/v1/langgraph/runs/{parent_id}/events", {
        "kind": "tool", "node": "external_payment",
        "payload": {"action_key": "payment-42", "action_state": "completed",
                    "result": "simulated external effect"},
    })
    assert status == 201, event
    branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "completed-after-checkpoint",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })[1]
    with Store(home) as store:
        before = len(store.runs())
    status, error = client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    assert status == 409, error
    assert "completed action" in error["error"].lower()
    with Store(home) as store:
        assert len(store.runs()) == before


def test_snapshot_from_another_run_cannot_be_branched(langgraph_api):
    client, _ = langgraph_api
    first_id, _ = execute_invoice_run(client)
    status, detail = client.get(f"/api/v1/runs/{first_id}")
    assert status == 200, detail
    snapshot_id = next(s["id"] for s in detail["snapshots"] if s["name"] == "after-read")
    second_id = client.post("/api/v1/langgraph/runs", {
        "graph": "invoice", "task_id": "another", "thread_id": "another",
        "label": "Another invoice", "input": {"invoice_id": "INV-42"},
    })[1]["run_id"]
    status, error = client.post(f"/api/v1/runs/{second_id}/branches", {
        "snapshot_id": snapshot_id, "name": "wrong-parent",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status in {400, 409}, error
    assert "error" in error


def test_unmaterialized_checkpoint_cannot_create_child(langgraph_api):
    client, home = langgraph_api
    run_id = register_invoice_run(client)
    status, snapshot = client.post(f"/api/v1/langgraph/runs/{run_id}/checkpoints", {
        "name": "after-read", "graph_checkpoint": {
            "thread_id": "invoice-42", "checkpoint_id": "not-in-langgraph", "checkpoint_ns": ""},
        "state": {"invoice_id": "INV-42"}, "completed_steps": ["read_invoice"],
        "last_node": "read_invoice",
    })
    assert status == 201, snapshot
    status, branch = client.post(f"/api/v1/runs/{run_id}/branches", {
        "snapshot_id": snapshot["snapshot_id"], "name": "unmaterialized",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status == 201, branch
    with Store(home) as store:
        before = len(store.runs())
    status, error = client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    assert status == 409, error
    with Store(home) as store:
        assert len(store.runs()) == before


def test_duplicate_completed_action_invalidates_savings(langgraph_api):
    client, home = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    client.post(f"/api/v1/runs/{parent_id}/flags", {
        "reason": "Wrong account", "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })
    detail = client.get(f"/api/v1/runs/{parent_id}")[1]
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "duplicate-action",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })[1]
    child = client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})[1]
    with Store(home) as store:
        store.action(parent_id, "external-payment", "completed")
        store.action(child["run_id"], "external-payment", "completed")
    status, report = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": {"input": 1.0, "cached_input": .1,
                                  "cache_write": 1.25, "output": 2.0},
    })
    assert status == 200, report
    assert report["duplicate_side_effects"] == 1
    assert report["saving_demonstrated"] is False


def test_unapproved_graph_cannot_resume(langgraph_api):
    client, home = langgraph_api
    status, registered = client.post("/api/v1/langgraph/runs", {
        "graph": "unapproved", "task_id": "unsafe", "thread_id": "unsafe",
        "label": "No resume approval", "input": {"invoice_id": "INV-42"},
    })
    assert status == 201, registered
    run_id = registered["run_id"]
    assert client.post(f"/api/v1/langgraph/runs/{run_id}/execute", {})[0] == 200
    detail = client.get(f"/api/v1/runs/{run_id}")[1]
    snap = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    branch = client.post(f"/api/v1/runs/{run_id}/branches", {
        "snapshot_id": snap["id"], "name": "unsafe-fork",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })[1]
    with Store(home) as store:
        before = len(store.runs())
    status, error = client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    assert status == 409, error
    assert "resume safe" in error["error"].lower()
    with Store(home) as store:
        assert len(store.runs()) == before


def test_cold_benchmark_requires_separate_approval(langgraph_api):
    client, home = langgraph_api
    status, registered = client.post("/api/v1/langgraph/runs", {
        "graph": "resume_only", "task_id": "resume-only", "thread_id": "resume-only",
        "label": "No cold rerun approval", "input": {"invoice_id": "INV-42"},
    })
    assert status == 201, registered
    run_id = registered["run_id"]
    assert client.post(f"/api/v1/langgraph/runs/{run_id}/execute", {})[0] == 200
    detail = client.get(f"/api/v1/runs/{run_id}")[1]
    snap = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    branch = client.post(f"/api/v1/runs/{run_id}/branches", {
        "snapshot_id": snap["id"], "name": "resume-without-cold",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })[1]
    assert client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})[0] == 200
    with Store(home) as store:
        before = len(store.runs())
    status, error = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": {"input": 1.0, "cached_input": .1,
                                  "cache_write": 1.25, "output": 2.0},
    })
    assert status == 409, error
    assert "cold benchmark safe" in error["error"].lower()
    with Store(home) as store:
        assert len(store.runs()) == before
