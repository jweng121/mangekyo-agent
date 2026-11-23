"""Expected immutable checkpoint and LangGraph locator contract."""

from conftest import register_invoice_run


def test_checkpoint_retains_graph_locator_and_content_hash(langgraph_api):
    client, _ = langgraph_api
    run_id = register_invoice_run(client)
    checkpoint = {
        "name": "after-read", "graph_checkpoint": {
            "thread_id": "invoice-42", "checkpoint_id": "graph-cp-1", "checkpoint_ns": ""},
        "state": {"invoice_id": "INV-42", "supplier_id": "SUP-42"},
        "completed_steps": ["read_invoice"],
    }
    status, first = client.post(f"/api/v1/langgraph/runs/{run_id}/checkpoints", checkpoint)
    assert status == 201, first
    assert first["snapshot_id"]
    assert len(first["manifest_hash"]) == 64

    status, second = client.post(f"/api/v1/langgraph/runs/{run_id}/checkpoints", checkpoint)
    assert status == 201, second
    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["manifest_hash"] == first["manifest_hash"]

    status, saved = client.get(f"/api/v1/snapshots/{first['snapshot_id']}")
    assert status == 200, saved
    assert saved["snapshot"]["run_id"] == run_id
    assert saved["graph_checkpoint"]["checkpoint_id"] == "graph-cp-1"
    assert saved["state"]["supplier_id"] == "SUP-42"
    assert saved["completed_steps"] == ["read_invoice"]
