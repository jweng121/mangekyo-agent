"""Run the contained invoice fork through the same LangGraph endpoint handlers."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from mangekyo.langgraph_api import LangGraphApi


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(".mangekyo"))
    parser.add_argument("--input-price", type=float, default=None)
    parser.add_argument("--cached-input-price", type=float, default=None)
    parser.add_argument("--cache-write-price", type=float, default=None)
    parser.add_argument("--output-price", type=float, default=None)
    args = parser.parse_args()
    provided = (args.input_price, args.cached_input_price,
                args.cache_write_price, args.output_price)
    if any(value is not None for value in provided) and not all(value is not None for value in provided):
        parser.error("Provide all four price rates or none")
    if os.environ.get("MANGEKYO_LANGGRAPH_MODEL") and not all(value is not None for value in provided):
        parser.error("Real model mode needs four explicit USD-per-million price rates")
    rates = dict(zip(("input", "cached_input", "cache_write", "output"),
                     provided if all(value is not None for value in provided)
                     else (1.0, .1, 1.25, 2.0)))

    os.environ.setdefault("MANGEKYO_LANGGRAPH_GRAPHS", json.dumps(
        {"invoice": "mangekyo.examples.invoice:build_graph"}))
    api = LangGraphApi(args.home.resolve())
    _, registered = api.post("/api/v1/langgraph/runs", {
        "graph": "invoice", "task_id": "invoice-42", "thread_id": "invoice-42",
        "label": "Review synthetic invoice 42", "input": {"invoice_id": "INV-42"},
    })
    parent_id = registered["run_id"]
    _, parent = api.post(f"/api/v1/langgraph/runs/{parent_id}/execute", {})
    api.post(f"/api/v1/runs/{parent_id}/flags", {
        "reason": "Account disagrees with approved synthetic supplier record",
        "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })
    _, detail = api.get(f"/api/v1/runs/{parent_id}")
    snapshot = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    branch_name = "fix-account-" + parent_id
    _, branch = api.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": snapshot["id"], "name": branch_name,
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    _, child = api.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    _, report = api.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": rates,
    })
    print(json.dumps({"home": str(args.home.resolve()), "parent_run": parent_id,
                      "parent_output": parent["output"], "snapshot": snapshot["id"],
                      "branch": branch_name, "child_run": child["run_id"],
                      "child_output": child["output"], "skipped_steps": child["skipped_steps"],
                      "benchmark": report}, indent=2))
    print("\nNext: \"" + sys.executable + "\" -m mangekyo --home \""
          + str(args.home.resolve()) + "\" dashboard")
    if not os.environ.get("MANGEKYO_LANGGRAPH_MODEL"):
        print("Model usage above is deterministic fixture data, not provider billing.")
    return 0 if report["saving_demonstrated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
