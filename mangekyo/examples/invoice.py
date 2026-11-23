"""Synthetic invoice workflow with fake or opt-in real model calls.

The graph proposes an account but never sends a payment. Its first node is
intentionally expensive so a fork after that node can demonstrate whether
skipping the node reduces the incremental rerun cost.
"""

from __future__ import annotations

import json
import operator
import os
import urllib.request
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph


class InvoiceState(TypedDict, total=False):
    invoice_id: str
    supplier_account: str
    read_text: str
    proposal_note: str
    output: dict[str, str]
    steps: Annotated[list[str], operator.add]
    usage_items: Annotated[list[dict[str, Any]], operator.add]


INVOICE_TEXT = ("Invoice INV-42 for a synthetic supplier. Account: WRONG-ACCOUNT. "
                "No payment may be sent. " * 90).strip()


def model_call(node: str, prompt: str) -> tuple[dict[str, Any], str]:
    model = os.environ.get("MANGEKYO_LANGGRAPH_MODEL")
    if not model:
        return ({"provider": "fake", "model": "fixture-v1", "node": node,
                 "input_tokens": 1000 if node == "read_invoice" else 400,
                 "cached_input_tokens": 0, "cache_write_tokens": 0,
                 "output_tokens": 50 if node == "read_invoice" else 20},
                "WRONG-ACCOUNT" if node == "read_invoice" else "PROPOSAL")

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for the live LangGraph model")
    body = {"model": model, "input": prompt, "max_output_tokens": 256}
    if model == "gpt-6-luna":
        body["reasoning"] = {"effort": "none"}
    request = urllib.request.Request(
        os.environ.get("MANGEKYO_LANGGRAPH_BASE_URL", "https://api.openai.com/v1/responses"),
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.load(response)
    usage = data.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    required = {"input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "cached_input_tokens": details.get("cached_tokens"),
                "cache_write_tokens": details.get("cache_write_tokens", 0)}
    if not all(isinstance(value, int) and value >= 0 for value in required.values()):
        raise RuntimeError("Provider did not report complete, nonnegative token usage")
    output_parts = [part.get("text", "") for item in data.get("output", [])
                    for part in item.get("content", []) if part.get("type") == "output_text"]
    text = "\n".join(output_parts).strip()
    if not text:
        raise RuntimeError("Provider returned no output text for the invoice task")
    return {"provider": "openai", "model": model, "node": node, **required}, text


def read_invoice(state: InvoiceState) -> InvoiceState:
    usage, text = model_call("read_invoice", "Extract the account identifier from this synthetic invoice. "
                             "Return only the identifier. " + INVOICE_TEXT)
    if "WRONG-ACCOUNT" not in text:
        raise RuntimeError("Model did not extract the expected synthetic invoice account")
    return {"read_text": text,
            "supplier_account": state.get("supplier_account", "WRONG-ACCOUNT"),
            "steps": ["read_invoice"], "usage_items": [usage]}


def propose_payment(state: InvoiceState) -> InvoiceState:
    account = state["supplier_account"]
    usage, note = model_call("propose_payment", "Confirm a proposal, without sending payment, for invoice "
                             + state["invoice_id"] + " to account " + account + ". Return one short sentence.")
    return {"output": {"invoice_id": state["invoice_id"], "supplier_account": account,
                       "action": "proposal-only"},
            "proposal_note": note, "steps": ["propose_payment"], "usage_items": [usage]}


def build_graph(checkpointer):
    """Return a compiled LangGraph graph; the caller owns the checkpointer."""
    graph = StateGraph(InvoiceState)
    graph.add_node("read_invoice", read_invoice)
    graph.add_node("propose_payment", propose_payment)
    graph.add_edge(START, "read_invoice")
    graph.add_edge("read_invoice", "propose_payment")
    graph.add_edge("propose_payment", END)
    return graph.compile(checkpointer=checkpointer)


build_graph.resume_safe = True
build_graph.benchmark_safe = True
build_graph.graph_version = "1"


def unapproved_graph(checkpointer):
    """Same contained graph without an operator's resume/benchmark approval."""
    return build_graph(checkpointer)


def resume_only_graph(checkpointer):
    """Allow a fork but refuse an automatic cold rerun."""
    return build_graph(checkpointer)


resume_only_graph.resume_safe = True
resume_only_graph.graph_version = "1"
