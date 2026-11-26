"""Contained SQL agent with a deliberately wrong local model decision."""

from __future__ import annotations

import json
import hashlib
import operator
import os
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph


class SqlState(TypedDict, total=False):
    question: str
    parsed_document_text: str
    source_document: str
    source_document_sha256: str
    selected_table: str
    schema: list[str]
    output: dict[str, Any]
    steps: Annotated[list[str], operator.add]
    usage_items: Annotated[list[dict[str, Any]], operator.add]
    tool_items: Annotated[list[dict[str, Any]], operator.add]


def _usage(node: str, input_tokens: int) -> dict[str, Any]:
    return {"provider": "fake", "model": "sql-fixture-v1", "node": node,
            "input_tokens": input_tokens, "cached_input_tokens": 0,
            "cache_write_tokens": 0, "output_tokens": 12}


def _database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE bookings (id INTEGER PRIMARY KEY, city TEXT);
        CREATE TABLE invoices (id INTEGER PRIMARY KEY, city TEXT);
        INSERT INTO bookings(city) VALUES ('Toronto'), ('Toronto'), ('Toronto');
        INSERT INTO invoices(city) VALUES ('Toronto');
    """)
    return db


def _demo_pause() -> None:
    delay = float(os.environ.get("MANGEKYO_SQL_STEP_DELAY", "0"))
    if delay > 0:
        time.sleep(min(delay, 10))


def read_schema(state: SqlState) -> SqlState:
    _demo_pause()
    with _database() as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {"schema": tables, "steps": ["read_schema"],
            "usage_items": [_usage("read_schema", 1200)],
            "tool_items": [{"name": "read_schema", "input": {}, "result": tables}]}


def choose_table(state: SqlState) -> SqlState:
    _demo_pause()
    model_path = os.environ.get("MANGEKYO_SQL_MODEL")
    if model_path:
        model = json.loads(Path(model_path).read_text(encoding="utf-8"))
        proposed = model.get("table_for_bookings", "invoices")
    else:
        proposed = "invoices"
    selected = state.get("selected_table") or ("invoices" if "invoices" in state["question"].lower()
                                                 else proposed)
    if selected not in state["schema"]:
        raise ValueError("Selected table is not in the observed schema")
    return {"selected_table": selected, "steps": ["choose_table"],
            "usage_items": [_usage("choose_table", 90)],
            "tool_items": [{"name": "select_table", "input": {"question": state["question"]},
                            "result": {"table": selected}}]}


def run_sql(state: SqlState) -> SqlState:
    _demo_pause()
    table = state["selected_table"]
    if table not in {"bookings", "invoices"}:
        raise ValueError("Unapproved table")
    query = f"SELECT COUNT(*) FROM {table} WHERE city = ?"
    with _database() as db:
        count = db.execute(query, ("Toronto",)).fetchone()[0]
    return {"output": {"table": table, "count": count}, "steps": ["run_sql"],
            "usage_items": [_usage("run_sql", 60)],
            "tool_items": [{"name": "execute_sql", "input": {"query": query,
                            "parameters": ["Toronto"]}, "result": {"count": count}}]}


def build_graph(checkpointer):
    graph = StateGraph(SqlState)
    graph.add_node("read_schema", read_schema)
    graph.add_node("choose_table", choose_table)
    graph.add_node("run_sql", run_sql)
    graph.add_edge(START, "read_schema")
    graph.add_edge("read_schema", "choose_table")
    graph.add_edge("choose_table", "run_sql")
    graph.add_edge("run_sql", END)
    return graph.compile(checkpointer=checkpointer)


build_graph.resume_safe = True
build_graph.benchmark_safe = True
build_graph.graph_version = "1"


def validate_checkpoint(context: dict) -> None:
    """The fixture recreates its read-only database from constant local data."""
    state = context.get("state")
    if not isinstance(state, dict) or state.get("schema") != ["bookings", "invoices"]:
        raise ValueError("synthetic SQL schema is missing or unexpected")
    with _database() as db:
        current = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    if current != state["schema"]:
        raise ValueError("synthetic SQL schema changed")
    source = state.get("source_document")
    if source:
        path = Path(source)
        if (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()
                != state.get("source_document_sha256")):
            raise ValueError("source PDF changed since the checkpoint")


build_graph.validate_checkpoint = validate_checkpoint
