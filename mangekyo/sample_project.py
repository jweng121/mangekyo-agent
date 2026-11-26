"""Create an isolated PDF-backed agent for the first-user workflow."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path


def create_sample(destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Sample destination is not empty: {destination}")
    pdf_bytes = (files("mangekyo") / "assets" / "sql-booking-request.pdf").read_bytes()
    destination.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": 1,
        "language": "python",
        "integration": "langgraph",
        "langgraph_graphs": {"sql": "mangekyo.examples.sql_agent:build_graph"},
        "current_model": {"version": "v1", "artifact": "active-sql-model.json"},
        "tui_launch": ["{python}", "agent.py"],
    }
    (destination / ".mangekyo-agent.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (destination / "agent.py").write_text(
        "from mangekyo.examples.sql_cli_agent import main\n\nmain()\n", encoding="utf-8")
    (destination / "active-sql-model.json").write_text(
        json.dumps({"version": "v1", "table_for_bookings": "invoices"}, indent=2) + "\n",
        encoding="utf-8")
    (destination / "expected.json").write_text(
        json.dumps({"expected": {"output": {"table": "bookings", "count": 3}}}, indent=2) + "\n",
        encoding="utf-8")
    (destination / "tool-expected.json").write_text(
        json.dumps({"expected": {"payload": {"result": {"table": "bookings"}}}}, indent=2) + "\n",
        encoding="utf-8")
    (destination / "booking-request.pdf").write_bytes(pdf_bytes)
    (destination / "README.md").write_text(
        "# Mangekyo sample agent\n\nThis agent parses `booking-request.pdf` and initially selects "
        "the wrong SQL table. Use Mangekyo to diagnose, branch, and verify the fix.\n",
        encoding="utf-8")
    return destination
