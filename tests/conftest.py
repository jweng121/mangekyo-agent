"""Loopback API fixture for the LangGraph integration contract."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


class ApiClient:
    def __init__(self, base: str):
        self.base = base

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            response = urllib.request.urlopen(request, timeout=300)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        return self.request("POST", path, body)

    def get(self, path: str) -> tuple[int, dict]:
        return self.request("GET", path)


@pytest.fixture
def langgraph_api(tmp_path: Path):
    """Start the real local API with one explicitly configured test graph."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    home = tmp_path / "history"
    log_path = tmp_path / "dashboard.log"
    env = os.environ.copy()
    env["MANGEKYO_FILE_INVOICE_ROOT"] = str(tmp_path)
    env["MANGEKYO_TOOL_CACHE_HOME"] = str(tmp_path / "tool-cache")
    env["MANGEKYO_LANGGRAPH_GRAPHS"] = json.dumps(
        {"invoice": "mangekyo.examples.invoice:build_graph",
         "file_invoice": "mangekyo.examples.file_invoice:build_graph",
         "unapproved": "mangekyo.examples.invoice:unapproved_graph",
         "resume_only": "mangekyo.examples.invoice:resume_only_graph"}
    )
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "mangekyo", "--home", str(home),
             "dashboard", "--port", str(port), "--no-open"],
            env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        client = ApiClient(f"http://127.0.0.1:{port}")
        try:
            for _ in range(100):
                if process.poll() is not None:
                    pytest.fail(f"Dashboard exited before serving: {log_path.read_text(errors='replace')}")
                try:
                    if client.get("/api/runs")[0] == 200:
                        break
                except (OSError, TimeoutError):
                    time.sleep(.05)
            else:
                pytest.fail("Dashboard did not start")
            yield client, home
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def register_invoice_run(client: ApiClient, task_id: str = "invoice-42") -> str:
    status, data = client.post("/api/v1/langgraph/runs", {
        "graph": "invoice", "task_id": task_id, "thread_id": task_id,
        "label": "Review invoice 42", "input": {"invoice_id": "INV-42"},
    })
    assert status == 201, data
    assert data["adapter"] == "langgraph"
    return data["run_id"]


def execute_invoice_run(client: ApiClient) -> tuple[str, dict]:
    run_id = register_invoice_run(client)
    status, data = client.post(f"/api/v1/langgraph/runs/{run_id}/execute", {})
    assert status == 200, data
    return run_id, data
