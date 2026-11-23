"""Branch cost must use recorded provider usage and a matched cold rerun."""

import pytest

from conftest import execute_invoice_run


def test_branch_benchmark_proves_net_model_saving(langgraph_api):
    client, _ = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    assert client.post(f"/api/v1/runs/{parent_id}/flags", {
        "reason": "Approved supplier record disagrees with proposed account",
        "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })[0] == 200
    status, detail = client.get(f"/api/v1/runs/{parent_id}")
    assert status == 200, detail
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    status, branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "cost-comparison",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status == 201, branch
    assert client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})[0] == 200

    prices = {"input": 1.0, "cached_input": .1, "cache_write": 1.25, "output": 2.0}
    status, report = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": prices,
    })
    assert status == 200, report
    assert report["cold"]["output"] == report["branch"]["output"]
    assert report["cold"]["provider_usage"]["input_tokens"] > report["branch"]["provider_usage"]["input_tokens"]
    assert report["cold"]["model_cost_usd"] > report["branch"]["model_cost_usd"]
    assert report["source"]["model_cost_usd"] > 0
    assert "read_invoice" in report["skipped_steps"]
    assert report["cold_total_model_cost_usd"] > report["branch_total_model_cost_usd"]
    assert report["net_model_saving_usd"] == pytest.approx(
        report["cold"]["model_cost_usd"] - report["branch"]["model_cost_usd"]
    )
    assert report["saving_demonstrated"] is True
    assert report["verdict"] == "saving demonstrated"
    assert report["correct_outcome"] is True
    assert report["skipped_step_saving_usd"] > 0
    assert "provider_cache_saving_usd" in report
    assert report["duplicate_side_effects"] == 0

    status, saved = client.get(f"/api/v1/branches/{branch['branch_id']}/benchmark")
    assert status == 200, saved
    assert saved == report


def test_cheaper_but_wrong_branch_is_not_called_a_saving(langgraph_api):
    client, _ = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    assert client.post(f"/api/v1/runs/{parent_id}/flags", {
        "reason": "Expected the approved account",
        "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })[0] == 200
    detail = client.get(f"/api/v1/runs/{parent_id}")[1]
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "wrong-but-cheap",
        "correction": {"supplier_account": "WRONG-ACCOUNT"},
    })[1]
    assert client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})[0] == 200
    report = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": {"input": 1.0, "cached_input": .1,
                                  "cache_write": 1.25, "output": 2.0},
    })[1]
    assert report["net_model_saving_usd"] > 0
    assert report["correct_outcome"] is False
    assert report["saving_demonstrated"] is False
    assert report["verdict"] == "no saving demonstrated"


def test_benchmark_refuses_a_cost_claim_without_a_resumed_branch(langgraph_api):
    client, _ = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    status, detail = client.get(f"/api/v1/runs/{parent_id}")
    assert status == 200, detail
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    status, branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "not-resumed",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status == 201, branch
    status, report = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": {"input": 1.0, "cached_input": .1, "cache_write": 1.25, "output": 2.0},
    })
    assert status == 409, report
    assert "error" in report


def test_benchmark_requires_expected_outcome_before_cold_run(langgraph_api):
    client, home = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    detail = client.get(f"/api/v1/runs/{parent_id}")[1]
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "missing-expected",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })[1]
    assert client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})[0] == 200
    from mangekyo.store import Store
    with Store(home) as store:
        before = len(store.runs())
    status, report = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": {"input": 1.0, "cached_input": .1,
                                  "cache_write": 1.25, "output": 2.0},
    })
    assert status == 409, report
    assert "expected outcome" in report["error"].lower()
    with Store(home) as store:
        assert len(store.runs()) == before
