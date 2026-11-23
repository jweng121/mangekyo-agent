"""A corrected branch must execute the original graph from its checkpoint."""

from conftest import execute_invoice_run


def test_flag_fork_and_resume_preserves_parent_run(langgraph_api):
    client, _ = langgraph_api
    parent_id, result = execute_invoice_run(client)
    assert result["output"]["supplier_account"] == "WRONG-ACCOUNT"
    assert result["status"] == "completed"  # A plausible but wrong answer is a human failure.

    status, flagged = client.post(f"/api/v1/runs/{parent_id}/flags", {
        "reason": "Account disagrees with approved supplier record",
        "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status == 200, flagged
    assert flagged["review_status"] == "flagged"

    status, detail = client.get(f"/api/v1/runs/{parent_id}")
    assert status == 200, detail
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    status, branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "correct-account",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status == 201, branch
    status, child = client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    assert status == 200, child
    assert child["run_id"] != parent_id
    assert child["parent_run"] == parent_id
    assert child["source_snapshot"] == checkpoint["id"]
    assert child["output"]["supplier_account"] == "SAFE-ACCOUNT"
    assert "read_invoice" in child["skipped_steps"]

    status, original = client.get(f"/api/v1/runs/{parent_id}")
    assert status == 200, original
    assert original["output"]["supplier_account"] == "WRONG-ACCOUNT"
