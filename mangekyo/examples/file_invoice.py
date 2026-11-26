"""Invoice review graph that reads real files in an operator-selected workspace.

The graph only reads local files and produces a proposal. It never sends a
payment or changes the workspace, so a matched cold rerun is safe.
"""

from __future__ import annotations

import csv
import hashlib
import json
import operator
import os
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .invoice import model_call
from ..tool_cache import ParsedReadCache


class FileInvoiceState(TypedDict, total=False):
    workspace: str
    invoice_id: str
    supplier_account: str
    approved_account: str
    invoice_text: str
    output: dict[str, str]
    steps: Annotated[list[str], operator.add]
    usage_items: Annotated[list[dict[str, Any]], operator.add]
    tool_items: Annotated[list[dict[str, Any]], operator.add]


def _read(workspace: Path, name: str) -> tuple[str, dict[str, str]]:
    path = (workspace / name).resolve(strict=True)
    if not path.is_relative_to(workspace) or not path.is_file():
        raise ValueError(f"{name} must be a regular file inside the workspace")
    content = path.read_bytes()
    return content.decode("utf-8"), {
        "tool": "read_file", "path": name, "sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
    }


def _workspace(path: str) -> Path:
    configured = os.environ.get("MANGEKYO_FILE_INVOICE_ROOT")
    if not configured:
        raise ValueError("MANGEKYO_FILE_INVOICE_ROOT must be configured by the operator")
    root = Path(configured).resolve(strict=True)
    workspace = Path(path).resolve(strict=True)
    if not root.is_dir() or not workspace.is_dir() or not workspace.is_relative_to(root):
        raise ValueError("workspace must be a directory inside MANGEKYO_FILE_INVOICE_ROOT")
    return workspace


def load_documents(state: FileInvoiceState) -> FileInvoiceState:
    workspace = _workspace(state["workspace"])
    invoice_text, invoice_tool = _read(workspace, "invoice.json")
    register_text, register_tool = _read(workspace, "suppliers.csv")
    cache_home = os.environ.get("MANGEKYO_TOOL_CACHE_HOME")
    if cache_home and not os.environ.get("MANGEKYO_REDACT", "").strip():
        ttl = float(os.environ.get("MANGEKYO_TOOL_CACHE_TTL", "3600"))
        with ParsedReadCache(cache_home) as cache:
            invoice, invoice_reason = cache.parse(
                workspace=workspace, relative_path="invoice.json", source=invoice_text.encode(),
                parser="json", tool_version="file-invoice-parser-v1",
                context={"encoding": "utf-8"}, ttl_seconds=ttl)
            suppliers, register_reason = cache.parse(
                workspace=workspace, relative_path="suppliers.csv", source=register_text.encode(),
                parser="csv", tool_version="file-invoice-parser-v1",
                context={"encoding": "utf-8", "delimiter": ","}, ttl_seconds=ttl)
    else:
        invoice, suppliers = json.loads(invoice_text), list(csv.DictReader(register_text.splitlines()))
        invoice_reason = register_reason = ("disabled_redaction" if cache_home else "disabled")
    invoice_tool["cache_status"] = invoice_reason
    register_tool["cache_status"] = register_reason
    if not isinstance(invoice, dict) or not all(
        isinstance(invoice.get(key), str) and invoice[key]
        for key in ("invoice_id", "supplier_id", "proposed_account")
    ):
        raise ValueError("invoice.json must contain invoice_id, supplier_id, and proposed_account")
    matches = [row for row in suppliers if row.get("supplier_id") == invoice["supplier_id"]]
    if len(matches) != 1 or not matches[0].get("approved_account"):
        raise ValueError("suppliers.csv must contain exactly one approved account for this supplier")
    usage, extracted = model_call(
        "read_invoice", "Extract the proposed account from this invoice JSON. Return only the account. "
        + invoice_text,
    )
    usage["node"] = "load_documents"
    if invoice["proposed_account"] not in extracted:
        raise ValueError("Model extraction did not match the invoice's proposed account")
    return {
        "invoice_id": invoice["invoice_id"],
        "invoice_text": invoice_text,
        "supplier_account": state.get("supplier_account", invoice["proposed_account"]),
        "approved_account": matches[0]["approved_account"],
        "steps": ["load_documents"],
        "usage_items": [usage],
        "tool_items": [invoice_tool, register_tool],
    }


def propose_payment(state: FileInvoiceState) -> FileInvoiceState:
    account = state["supplier_account"]
    usage, _ = model_call(
        "propose_payment", "Propose a payment for invoice " + state["invoice_id"]
        + " to account ", account + ". Do not send a payment. Return one short sentence.",
    )
    return {
        "output": {"invoice_id": state["invoice_id"], "supplier_account": account,
                   "action": "proposal-only"},
        "steps": ["propose_payment"], "usage_items": [usage],
    }


def build_graph(checkpointer):
    graph = StateGraph(FileInvoiceState)
    graph.add_node("load_documents", load_documents)
    graph.add_node("propose_payment", propose_payment)
    graph.add_edge(START, "load_documents")
    graph.add_edge("load_documents", "propose_payment")
    graph.add_edge("propose_payment", END)
    return graph.compile(checkpointer=checkpointer)


def validate_checkpoint(context: dict) -> None:
    """Reject reuse when a file captured by load_documents has changed."""
    state = context.get("state") or {}
    workspace = _workspace(state["workspace"])
    recorded = {item["path"]: item["sha256"] for item in state.get("tool_items", [])
                if item.get("tool") == "read_file"}
    if set(recorded) != {"invoice.json", "suppliers.csv"}:
        raise ValueError("checkpoint lacks the two source file digests")
    for name, expected in recorded.items():
        _, current = _read(workspace, name)
        if current["sha256"] != expected:
            raise ValueError(f"{name} changed since the checkpoint")


build_graph.resume_safe = True
build_graph.benchmark_safe = True
build_graph.graph_version = "1"
build_graph.validate_checkpoint = validate_checkpoint
