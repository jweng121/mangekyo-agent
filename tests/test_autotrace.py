"""An added LangGraph project is traced through its normal process launch."""

import sys

from mangekyo.launch import launch
from mangekyo.checks import check_run
from mangekyo.project import add_project
from mangekyo.store import Store


def test_add_then_run_captures_real_langchain_calls(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["langgraph"]\n')
    add_project(tmp_path)
    (tmp_path / "agent.py").write_text('''\
from typing import TypedDict
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END

class State(TypedDict):
    question: str
    answer: str

@tool
def find_table(question: str) -> str:
    """Find a table for a question."""
    return "bookings"

model = FakeListChatModel(responses=["bookings"])

def decide(state: State) -> dict:
    selected = model.invoke(state["question"]).content
    observed = find_table.invoke({"question": state["question"]})
    return {"answer": selected + ":" + observed}

builder = StateGraph(State)
builder.add_node("decide", decide)
builder.add_edge(START, "decide")
builder.add_edge("decide", END)
graph = builder.compile()
assert graph.invoke({"question": "How many bookings?", "answer": ""})["answer"] == "bookings:bookings"
''', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with Store(tmp_path / "history") as store:
        assert launch(store, [sys.executable, "agent.py"]) == 0
        runs = store.runs()
        assert len(runs) == 1
        events = store.events(runs[0]["id"])
        auto = [event for event in events if event["payload"].get("capture") == "python-langchain-auto"]
        assert [event["kind"] for event in auto] == ["model", "tool", "output"]
        assert auto[1]["payload"]["name"] == "find_table"
        assert auto[1]["payload"]["result"] == "bookings"
        assert auto[2]["payload"]["result"]["answer"] == "bookings:bookings"
        assert check_run(store, runs[0]["id"], {"expected": {"output": {
            "answer": "bookings:bookings"}}})["outcome"] == "passed"
