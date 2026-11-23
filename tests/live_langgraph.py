"""Opt-in provider-backed cost check; run this file explicitly with pytest."""

import json
import os
from pathlib import Path

import pytest

from conftest import execute_invoice_run


def _load_local_config(path: Path | None = None, environ: dict | None = None):
    """Load only live-test settings from the ignored project-local file."""
    path = path or Path(__file__).resolve().parents[1] / ".env.local"
    environ = os.environ if environ is None else environ
    if not path.exists():
        return
    allowed = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MANGEKYO_LANGGRAPH_MODEL",
               *(f"MANGEKYO_TEST_PRICE_{name}_USD_PER_M"
                 for name in ("INPUT", "CACHED_INPUT", "CACHE_WRITE", "OUTPUT"))}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.strip().partition("=")
        if not separator or key not in allowed or environ.get(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        environ[key] = value


@pytest.fixture
def live_config():
    _load_local_config()


@pytest.fixture
def configured_api(live_config, langgraph_api):
    return langgraph_api


def test_real_provider_branch_cost_and_correctness(configured_api):
    model = os.environ.get("MANGEKYO_LANGGRAPH_MODEL")
    assert model, "Set MANGEKYO_LANGGRAPH_MODEL for the live test"
    provider = "anthropic" if model.startswith("claude-") else "openai"
    key_name = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    assert os.environ.get(key_name), f"Set {key_name} in .env.local for the live LangGraph test"
    price_names = ("INPUT", "CACHED_INPUT", "CACHE_WRITE", "OUTPUT")
    rates = {}
    for name in price_names:
        raw = os.environ.get(f"MANGEKYO_TEST_PRICE_{name}_USD_PER_M")
        assert raw is not None, f"Set MANGEKYO_TEST_PRICE_{name}_USD_PER_M"
        rates[name.lower()] = float(raw)

    client, _ = configured_api
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
    print("\nLive LangGraph branch benchmark:\n" + json.dumps(report, indent=2, sort_keys=True))
    assert report["cold"]["output"] == report["branch"]["output"]
    assert report["cold"]["provider_usage"]["provider"] == provider
    assert report["branch"]["provider_usage"]["provider"] == provider
    assert report["duplicate_side_effects"] == 0
    assert report["correct_outcome"] is True
    assert report["saving_demonstrated"] is True, report
