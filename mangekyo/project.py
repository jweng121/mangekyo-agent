"""Project registration and capability discovery for the Git-like CLI."""

from __future__ import annotations

import json
import importlib
from pathlib import Path
from typing import Any

CONFIG = ".mangekyo-agent.json"


def add_project(path: Path, graph_specs: list[str] | None = None) -> dict[str, Any]:
    project = path.expanduser().resolve()
    if not project.is_dir():
        raise ValueError(f"Project directory does not exist: {project}")
    pyproject = project / "pyproject.toml"
    package = project / "package.json"
    if pyproject.is_file():
        language = "python"
        source = pyproject.read_text(encoding="utf-8")
        integration = "langgraph" if "langgraph" in source.lower() else "python-boundary"
    elif package.is_file():
        language = "javascript"
        source = package.read_text(encoding="utf-8")
        integration = "langgraph-js" if "@langchain/langgraph" in source else "json-trace"
    else:
        language = "any"
        integration = "json-trace"
    graphs: dict[str, str] = {}
    graph_capabilities: dict[str, dict[str, Any]] = {}
    if graph_specs:
        if integration != "langgraph":
            raise ValueError("--graph requires a Python LangGraph project")
        for item in graph_specs:
            alias, separator, factory_spec = item.partition("=")
            module, colon, attribute = factory_spec.partition(":")
            if not separator or not colon or not alias or not module or not attribute:
                raise ValueError("--graph must be NAME=module:factory")
            graphs[alias] = factory_spec
            try:
                factory = getattr(importlib.import_module(module), attribute)
                if not callable(factory):
                    raise TypeError("factory is not callable")
                graph_capabilities[alias] = {"live_resume": bool(
                    getattr(factory, "resume_safe", False)
                    and callable(getattr(factory, "validate_checkpoint", None)))}
            except (ImportError, AttributeError, TypeError) as exc:
                graph_capabilities[alias] = {"live_resume": False, "reason": str(exc)}
    automatic = integration == "langgraph"
    manual_captures = (["RunRecorder events and Python boundary calls"]
                       if integration == "python-boundary" else ["imported JSON trace events"])
    config = {"schema_version": 1, "language": language, "integration": integration,
              "instrumentation": {"mode": "python-langchain-auto" if automatic else "manual",
                                  "captures": ["LangChain model calls", "LangChain tool calls",
                                               "LangGraph invoke output"] if automatic else manual_captures},
              "capabilities": {"trace": True, "checkpoint_inspection": not automatic or bool(graphs),
                               "live_resume": any(value["live_resume"] for value in graph_capabilities.values())}}
    if graphs:
        config["langgraph_graphs"] = graphs
        config["graph_capabilities"] = graph_capabilities
    target = project / CONFIG
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or existing.get("schema_version") != 1:
            raise ValueError(f"Unsupported existing {CONFIG}")
        changed = False
        if "instrumentation" not in existing:
            existing["instrumentation"] = config["instrumentation"]
            existing["capabilities"] = config["capabilities"]
            changed = True
        if graphs:
            existing.setdefault("langgraph_graphs", {}).update(graphs)
            existing.setdefault("graph_capabilities", {}).update(graph_capabilities)
            existing["capabilities"]["checkpoint_inspection"] = True
            existing["capabilities"]["live_resume"] = any(
                value["live_resume"] for value in existing["graph_capabilities"].values())
            changed = True
        if changed:
            target.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        return {"project": str(project), "config": str(target), **existing}
    target.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return {"project": str(project), "config": str(target), **config}
