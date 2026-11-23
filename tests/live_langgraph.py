"""Opt-in provider-backed cost check; run this file explicitly with pytest."""

import os

import pytest

from conftest import execute_invoice_run


def test_real_provider_branch_cost_and_correctness(langgraph_api):
    assert os.environ.get("OPENAI_API_KEY"), "Set OPENAI_API_KEY for the live LangGraph test"
    assert os.environ.get("MANGEKYO_LANGGRAPH_MODEL"), "Set MANGEKYO_LANGGRAPH_MODEL for the live test"
    price_names = ("INPUT", "CACHED_INPUT", "CACHE_WRITE", "OUTPUT")
    rates = {}
    for name in price_names:
        raw = os.environ.get(f"MANGEKYO_TEST_PRICE_{name}_USD_PER_M")
        assert raw is not None, f"Set MANGEKYO_TEST_PRICE_{name}_USD_PER_M"
        rates[name.lower()] = float(raw)

    client, _ = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    assert client.post(f"/api/v1/runs/{parent_id}/flags", {
        "reason": "Approved account disagrees with the proposal",
        "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })[0] == 200
    status, detail = client.get(f"/api/v1/runs/{parent_id}")
    assert status == 200, detail
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    status, branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "live-correction",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status == 201, branch
    status, child = client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    assert status == 200, child
    assert child["output"]["supplier_account"] == "SAFE-ACCOUNT"

    status, report = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": rates,
    })
    assert status == 200, report
    assert report["cold"]["output"] == report["branch"]["output"]
    assert report["cold"]["provider_usage"]["provider"] == "openai"
    assert report["branch"]["provider_usage"]["provider"] == "openai"
    assert report["duplicate_side_effects"] == 0
    assert report["correct_outcome"] is True
    assert report["saving_demonstrated"] is True, report
