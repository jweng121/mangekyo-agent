"""A standard LangChain tool is captured without a graph tool_items update."""

import json
import uuid
from typing import TypedDict

from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph

from mangekyo.langgraph_api import LangGraphApi
from mangekyo.store import Store


@tool
def lookup_table(name: str) -> str:
    """Return a known table name."""
    return "bookings" if name == "booking-data" else "unknown"


class State(TypedDict, total=False):
    output: dict


def read_table(state: State, config) -> State:
    result = lookup_table.invoke({"name": "booking-data"}, config=config)
    return {"output": {"table": result}}


def build_graph(checkpointer):
    graph = StateGraph(State)
    graph.add_node("read_table", read_table)
    graph.add_edge(START, "read_table")
    graph.add_edge("read_table", END)
    return graph.compile(checkpointer=checkpointer)


def test_standard_tool_callback_is_captured(tmp_path, monkeypatch):
    monkeypatch.setenv("MANGEKYO_LANGGRAPH_GRAPHS", json.dumps({"callback": __name__ + ":build_graph"}))
    api = LangGraphApi(tmp_path)
    _, registration = api.post("/api/v1/langgraph/runs", {
        "graph": "callback", "task_id": "test", "thread_id": uuid.uuid4().hex,
        "label": "Lookup table", "input": {}})
    api.post(f"/api/v1/langgraph/runs/{registration['run_id']}/execute", {})
    with Store(tmp_path) as store:
        tools = [event for event in store.events(registration["run_id"])
                 if event["kind"] == "tool"]
        assert len(tools) == 1
        assert tools[0]["payload"]["name"] == "lookup_table"
        assert tools[0]["payload"]["result"] == "bookings"
