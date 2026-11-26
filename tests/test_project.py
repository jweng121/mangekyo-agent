import json
import sys

from mangekyo.project import add_project
from mangekyo.launch import launch
from mangekyo.store import Store
from mangekyo.langgraph_api import LangGraphApi


def test_add_detects_python_without_claiming_live_resume(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["langgraph"]\n')
    result = add_project(tmp_path)
    assert result["integration"] == "langgraph"
    assert result["capabilities"]["live_resume"] is False
    assert result["instrumentation"]["mode"] == "python-langchain-auto"
    assert json.loads((tmp_path / ".mangekyo-agent.json").read_text()) == {
        key: result[key] for key in ("schema_version", "language", "integration",
                                    "instrumentation", "capabilities")}
    assert add_project(tmp_path) == result


def test_added_integration_is_passed_to_launched_agent(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='agent'\n")
    config = add_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    with Store(tmp_path / "history") as store:
        assert launch(store, [sys.executable, "-c",
                              "import os; open('received.txt','w').write(os.environ['MANGEKYO_PROJECT_CONFIG'])"]) == 0
        run = store.runs()[0]
        assert store.events(run["id"])[0]["payload"]["project_integration"] == "python-boundary"
    assert (tmp_path / "received.txt").read_text() == config["config"]


def test_add_graph_factory_is_available_to_later_cli_processes(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["langgraph"]\n')
    graph = "sql=mangekyo.examples.sql_agent:build_graph"
    result = add_project(tmp_path, [graph])
    assert result["capabilities"]["checkpoint_inspection"] is True
    assert result["capabilities"]["live_resume"] is True
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MANGEKYO_LANGGRAPH_GRAPHS", raising=False)
    assert LangGraphApi(tmp_path / "history").graphs == {
        "sql": "mangekyo.examples.sql_agent:build_graph"}


def test_add_does_not_advertise_resume_without_environment_validator(tmp_path, monkeypatch):
    from mangekyo.examples import sql_agent

    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["langgraph"]\n')
    monkeypatch.delattr(sql_agent.build_graph, "validate_checkpoint")
    result = add_project(tmp_path, ["sql=mangekyo.examples.sql_agent:build_graph"])
    assert result["graph_capabilities"]["sql"]["live_resume"] is False
    assert result["capabilities"]["live_resume"] is False
