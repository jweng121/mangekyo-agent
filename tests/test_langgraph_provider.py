"""Exercise real-provider response parsing against a local test transport."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mangekyo.examples.invoice import model_call
from conftest import execute_invoice_run
from live_langgraph import _load_local_config


def test_live_config_loads_key_from_local_file_without_overriding_environment(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text("ANTHROPIC_API_KEY=test-only-local\n"
                    "MANGEKYO_LANGGRAPH_MODEL=claude-haiku-5-5\n"
                    "UNRELATED_SETTING=ignored\n", encoding="utf-8")
    environment = {}
    _load_local_config(path, environment)
    assert environment["ANTHROPIC_API_KEY"] == "test-only-local"
    assert environment["MANGEKYO_LANGGRAPH_MODEL"] == "claude-haiku-5-5"
    assert "UNRELATED_SETTING" not in environment
    environment["ANTHROPIC_API_KEY"] = "existing-key"
    _load_local_config(path, environment)
    assert environment["ANTHROPIC_API_KEY"] == "existing-key"


def test_provider_usage_is_taken_from_response(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/v1/responses"
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert request["model"] == "test-model"
            body = json.dumps({"usage": {"input_tokens": 1200, "output_tokens": 32,
                "input_tokens_details": {"cached_tokens": 256, "cache_write_tokens": 0}},
                "output": [{"content": [{"type": "output_text", "text": "WRONG-ACCOUNT"}]}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("MANGEKYO_LANGGRAPH_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("MANGEKYO_LANGGRAPH_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1/responses")
    try:
        usage, output = model_call("read_invoice", "Synthetic invoice")
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert usage == {"provider": "openai", "model": "test-model", "node": "read_invoice",
                     "input_tokens": 1200, "output_tokens": 32,
                     "cached_input_tokens": 256, "cache_write_tokens": 0}
    assert output == "WRONG-ACCOUNT"


def test_anthropic_usage_normalizes_cache_read_and_write(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/v1/messages"
            assert self.headers["anthropic-version"] == "2026-10-21"
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert request["model"] == "claude-haiku-5-5"
            assert request["thinking"] == {"type": "disabled"}
            body = json.dumps({"usage": {"input_tokens": 900, "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 100, "output_tokens": 32},
                "content": [{"type": "text", "text": "WRONG-ACCOUNT"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("MANGEKYO_LANGGRAPH_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    monkeypatch.setenv("MANGEKYO_ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1/messages")
    try:
        usage, output = model_call("read_invoice", "Synthetic invoice")
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert usage == {"provider": "anthropic", "model": "claude-haiku-5-5", "node": "read_invoice",
                     "input_tokens": 1200, "cached_input_tokens": 200,
                     "cache_write_tokens": 100, "output_tokens": 32}
    assert output == "WRONG-ACCOUNT"


@pytest.fixture
def provider_transport(monkeypatch):
    calls = {"read": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            read = "Extract the account identifier" in request["input"]
            if read:
                calls["read"] += 1
            cached = 256 if read and calls["read"] == 2 else 0
            answer = "WRONG-ACCOUNT" if read else "PROPOSAL"
            body = json.dumps({"usage": {
                "input_tokens": 1200 if read else 300,
                "output_tokens": 32 if read else 20,
                "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": 0},
            }, "output": [{"content": [{"type": "output_text", "text": answer}]}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("MANGEKYO_LANGGRAPH_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("MANGEKYO_LANGGRAPH_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1/responses")
    try:
        yield calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_branch_benchmark_uses_reported_cache_tokens(provider_transport, langgraph_api):
    client, _ = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    client.post(f"/api/v1/runs/{parent_id}/flags", {
        "reason": "Wrong account", "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })
    detail = client.get(f"/api/v1/runs/{parent_id}")[1]
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "provider-cache-test",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })[1]
    assert client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})[0] == 200
    status, report = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": {"input": 1.0, "cached_input": .1,
                                  "cache_write": 1.25, "output": 2.0},
    })
    assert status == 200, report
    assert provider_transport["read"] == 2  # Parent and cold; branch skipped the read.
    assert report["cold"]["provider_usage"]["cached_input_tokens"] == 256
    assert report["branch"]["provider_usage"]["cached_input_tokens"] == 0
    assert report["provider_cache_saving_usd"] == pytest.approx(-.0002304)
    assert report["net_model_saving_usd"] == pytest.approx(.0010336)
    assert report["saving_demonstrated"] is True


@pytest.fixture
def anthropic_transport(monkeypatch):
    calls = {"read": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            read = "Extract the account identifier" in request["messages"][0]["content"]
            if read:
                calls["read"] += 1
            cached = 200 if read and calls["read"] == 2 else 0
            answer = "WRONG-ACCOUNT" if read else "PROPOSAL"
            body = json.dumps({"usage": {
                "input_tokens": 1000 if read else 300,
                "cache_read_input_tokens": cached,
                "cache_creation_input_tokens": 0,
                "output_tokens": 32 if read else 20,
            }, "content": [{"type": "text", "text": answer}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("MANGEKYO_LANGGRAPH_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    monkeypatch.setenv("MANGEKYO_ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1/messages")
    try:
        yield calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def test_anthropic_branch_saves_reported_model_cost(anthropic_transport, langgraph_api):
    client, _ = langgraph_api
    parent_id, _ = execute_invoice_run(client)
    client.post(f"/api/v1/runs/{parent_id}/flags", {
        "reason": "Wrong account", "expected": {"supplier_account": "SAFE-ACCOUNT"},
    })
    detail = client.get(f"/api/v1/runs/{parent_id}")[1]
    checkpoint = next(s for s in detail["snapshots"] if s["name"] == "after-read")
    branch = client.post(f"/api/v1/runs/{parent_id}/branches", {
        "snapshot_id": checkpoint["id"], "name": "anthropic-cost-test",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })[1]
    assert client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})[0] == 200
    status, report = client.post(f"/api/v1/branches/{branch['branch_id']}/benchmark", {
        "price_per_million_usd": {"input": .10, "cached_input": .01,
                                  "cache_write": .125, "output": .50},
    })
    assert status == 200, report
    assert anthropic_transport["read"] == 2
    assert report["cold"]["provider_usage"]["provider"] == "anthropic"
    assert report["cold"]["provider_usage"]["cached_input_tokens"] == 200
    assert report["branch"]["provider_usage"]["cached_input_tokens"] == 0
    assert report["provider_cache_saving_usd"] == pytest.approx(-.000018)
    assert report["saving_demonstrated"] is True
