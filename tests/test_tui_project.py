"""TUI project registration discovers and remembers a simple Python agent."""

import json

from mangekyo.tui_project import active_project, launch_config, register_project, resolve_launch


def test_add_discovers_agent_entrypoint_and_remembers_project(tmp_path, monkeypatch):
    project = tmp_path / "my-agent"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='my-agent'\n", encoding="utf-8")
    (project / "agent.py").write_text("print('hello')\n", encoding="utf-8")
    store = tmp_path / "history"
    store.mkdir()
    monkeypatch.chdir(tmp_path)

    result = register_project(project, store)

    assert result["project"] == str(project)
    assert result["integration"] == "python-boundary"
    assert result["launch"] == ["{python}", "agent.py"]
    assert active_project(store) == project
    assert launch_config(project) == result["launch"]
    assert resolve_launch(project, result["launch"])[1] == "agent.py"
    config = json.loads((project / ".mangekyo-agent.json").read_text(encoding="utf-8"))
    assert config["tui_launch"] == result["launch"]


def test_add_registers_langgraph_factory_for_later_resume(tmp_path):
    project = tmp_path / "graph-agent"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\ndependencies = ["langgraph"]\n',
                                           encoding="utf-8")
    store = tmp_path / "history"
    store.mkdir()

    result = register_project(project, store,
                              ["sql=mangekyo.examples.sql_agent:build_graph"])

    config = json.loads((project / ".mangekyo-agent.json").read_text(encoding="utf-8"))
    assert result["capabilities"]["live_resume"] is True
    assert config["langgraph_graphs"]["sql"] == "mangekyo.examples.sql_agent:build_graph"
