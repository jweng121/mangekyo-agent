"""Run a file-backed LangGraph correction through Mangekyo's local API."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mangekyo.langgraph_api import LangGraphApi


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=root / "examples" / "file-invoice")
    parser.add_argument("--home", type=Path, default=root / ".mangekyo-file-demo")
    parser.add_argument("--tool-cache-home", type=Path,
                        help="Opt in to a local cache of validated JSON/CSV parses")
    parser.add_argument("--input-price", type=float)
    parser.add_argument("--cached-input-price", type=float)
    parser.add_argument("--cache-write-price", type=float)
    parser.add_argument("--output-price", type=float)
    args = parser.parse_args()
    prices = (args.input_price, args.cached_input_price,
              args.cache_write_price, args.output_price)
    if any(value is not None for value in prices) and not all(value is not None for value in prices):
        parser.error("Provide all four price rates or none")
    real_model = bool(os.environ.get("MANGEKYO_LANGGRAPH_MODEL"))
    if real_model and not all(value is not None for value in prices):
        parser.error("Real model mode needs four explicit USD-per-million price rates")
    rates = dict(zip(("input", "cached_input", "cache_write", "output"),
                     prices if all(value is not None for value in prices)
                     else (1.0, .1, 1.25, 2.0)))

    os.environ.setdefault("MANGEKYO_FILE_INVOICE_ROOT", str(args.workspace.resolve()))
    if args.tool_cache_home:
        os.environ["MANGEKYO_TOOL_CACHE_HOME"] = str(args.tool_cache_home.resolve())
    os.environ.setdefault("MANGEKYO_LANGGRAPH_GRAPHS", json.dumps(
        {"file_invoice": "mangekyo.examples.file_invoice:build_graph"}))
    api = LangGraphApi(args.home.resolve())
    _, registered = api.post("/api/v1/langgraph/runs", {
        "graph": "file_invoice", "task_id": "file-invoice-42",
        "thread_id": "file-invoice-42", "label": "Review a local invoice and supplier register",
        "input": {"workspace": str(args.workspace.resolve())},
    })
    parent_id = registered["run_id"]
    _, original = api.post(f"/api/v1/langgraph/runs/{parent_id}/execute", {})
    api.post(f"/api/v1/runs/{parent_id}/flags", {
        "reason": "Invoice proposal differs from supplier register",
        "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })
    _, detail = api.get(f"/api/v1/runs/{parent_id}")
    checkpoint = next(item for item in detail["snapshots"] if item["name"] == "after-load")
    name = "correct-file-invoice-" + parent_id
    _, branch = api.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": name,
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })
    _, child = api.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    _, report = api.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": rates,
    })
    _, cold_detail = api.get(f"/api/v1/runs/{report['cold']['run_id']}")
    def read_statuses(events):
        return {event["payload"]["payload"]["path"]: event["payload"]["payload"].get("cache_status")
                for event in events if event["kind"] == "tool"}
    print(json.dumps({"parent_run": parent_id, "original_output": original["output"],
                      "checkpoint": checkpoint["id"], "child_run": child["run_id"],
                      "corrected_output": child["output"],
                      "skipped_steps": child["skipped_steps"],
                      "file_read_cache": {"parent": read_statuses(detail["events"]),
                                          "cold": read_statuses(cold_detail["events"])},
                      "benchmark": report}, indent=2))
    if not real_model:
        print("\nThe default model uses deterministic fixture tokens; its prices are illustrative.")
    print(f"Inspect the result: python -m mangekyo --home \"{args.home.resolve()}\" dashboard")
    return 0 if report["saving_demonstrated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
