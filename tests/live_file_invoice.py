"""Opt-in provider-backed check for the file-reading LangGraph integration."""

from __future__ import annotations

import json
import os

from live_langgraph import configured_api, live_config


def test_real_provider_file_workflow(configured_api, tmp_path):
    model = os.environ.get("MANGEKYO_LANGGRAPH_MODEL")
    assert model, "Set MANGEKYO_LANGGRAPH_MODEL in .env.local"
    provider = "anthropic" if model.startswith("claude-") else "openai"
    key = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    assert os.environ.get(key), f"Set {key} in .env.local"
    rates = {}
    for name in ("INPUT", "CACHED_INPUT", "CACHE_WRITE", "OUTPUT"):
        raw = os.environ.get(f"MANGEKYO_TEST_PRICE_{name}_USD_PER_M")
        assert raw is not None, f"Set MANGEKYO_TEST_PRICE_{name}_USD_PER_M"
        rates[name.lower()] = float(raw)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "invoice.json").write_text(json.dumps({
        "invoice_id": "INV-42", "supplier_id": "supplier-7",
        "proposed_account": "WRONG-ACCOUNT",
    }), encoding="utf-8")
    (workspace / "suppliers.csv").write_text(
        "supplier_id,approved_account\nsupplier-7,SAFE-ACCOUNT\n", encoding="utf-8",
    )
    client, _ = configured_api
    status, registered = client.post("/api/v1/langgraph/runs", {
        "graph": "file_invoice", "task_id": "live-file-invoice",
        "thread_id": "live-file-invoice", "label": "Live file invoice review",
        "input": {"workspace": str(workspace)},
    })
    assert status == 201, registered
    run_id = registered["run_id"]
    status, original = client.post(f"/api/v1/langgraph/runs/{run_id}/execute", {})
    assert status == 200, original
    assert original["output"]["supplier_account"] == "WRONG-ACCOUNT"
    detail = client.get(f"/api/v1/runs/{run_id}")[1]
    assert len([event for event in detail["events"] if event["kind"] == "tool"]) == 2
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-load")
    assert client.post(f"/api/v1/runs/{run_id}/flags", {
        "reason": "Supplier register disagrees with proposed account",
        "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })[0] == 200
    status, branch = client.post(f"/api/v1/runs/{run_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "live-file-correction",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    assert status == 201, branch
    status, child = client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    assert status == 200, child
    assert child["skipped_steps"] == ["load_documents"]
    status, report = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": rates,
    })
    assert status == 200, report
    print("\nLive file-backed LangGraph benchmark:\n" + json.dumps(report, indent=2, sort_keys=True))
    assert report["same_output"] is True
    assert report["correct_outcome"] is True
    assert report["duplicate_side_effects"] == 0
    assert report["skipped_step_saving_usd"] > 0
    assert report["saving_demonstrated"] is True
