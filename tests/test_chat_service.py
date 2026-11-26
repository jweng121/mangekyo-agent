"""A local model exercises shared chat, run grounding, and connection failures."""

import json
import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

from mangekyo.chat_service import (ask, exchange_openrouter_code, model_config,
                                   openrouter_auth_url, save_model_config, sessions,
                                   verify_model as probe_model)
from mangekyo.store import Store


def test_local_model_chat_uses_pdf_and_keeps_conversation(tmp_path):
    requests = []

    class Model(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            response = {"choices": [{"message": {"content": "The PDF says bookings; check selected_table=bookings."}}]}
            data = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        home = tmp_path / "history"
        with Store(home) as store:
            run = store.create_run("sample", "Count bookings")
            store.event(run, "tool", {"name": "select_table", "selected_table": "invoices"})
            store.snapshot(run, "after-choose", {"selected_table": "invoices"})
            store.artifact(run, "booking-request.pdf", b"%PDF-1.4\n", "application/pdf",
                           parsed_text="Question: Count Toronto bookings")
            store.status(run, "completed")
        save_model_config(home, provider="local", model="fixture",
                          base_url=f"http://127.0.0.1:{server.server_port}/v1")
        assert model_config(home)["model"] == "fixture"
        assert probe_model(home).startswith("The PDF")
        first = ask(home, "What went wrong?", run_id=run)
        second = ask(home, "Suggest an eval", session_id=first["session"])
        assert first["session"] == second["session"]
        assert len(sessions(home)[0]["messages"]) == 4
        assert "Count Toronto bookings" in requests[1]["messages"][0]["content"]
        assert "selected_table" in requests[1]["messages"][0]["content"]
        assert "What went wrong?" in requests[2]["messages"][-3]["content"]
        assert "api_key" not in (home / "debug-model.json").read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()


def test_connection_failure_is_clear_and_does_not_save_a_turn(tmp_path):
    home = tmp_path / "history"
    save_model_config(home, provider="local", model="fixture",
                      base_url="http://127.0.0.1:1/v1")
    with pytest.raises(RuntimeError, match="Cannot connect"):
        probe_model(home)
    with pytest.raises(RuntimeError, match="not passed"):
        ask(home, "hello")
    assert sessions(home) == []


def test_no_auth_setup_does_not_reuse_previous_credential(tmp_path):
    home = tmp_path / "history"
    url = "http://127.0.0.1:1234/v1"
    save_model_config(home, provider="local", model="fixture", base_url=url)
    config = model_config(home)
    config["key_source"] = "keyring"
    (home / "debug-model.json").write_text(json.dumps(config), encoding="utf-8")
    updated = save_model_config(home, provider="local", model="fixture",
                                base_url=url, no_auth=True)
    assert updated["key_source"] == "none"
    assert updated["key_env"] is None


def test_openrouter_sign_in_uses_pkce_and_saves_only_keyring_reference(tmp_path):
    url = openrouter_auth_url("verifier", callback_url="http://127.0.0.1:8765/", state="state1")
    assert "code_challenge_method=S256" in url
    assert "callback_url=http%3A%2F%2F127.0.0.1%3A8765%2F" in url
    assert "state=state1" in url
    response = io.BytesIO(b'{"key":"sk-or-secret"}')
    with patch("mangekyo.chat_service.urlopen", return_value=response) as request, \
         patch("keyring.set_password") as save_secret:
        config = exchange_openrouter_code(tmp_path, code="auth-code", verifier="verifier",
                                          model="provider/model")
    body = json.loads(request.call_args.args[0].data)
    assert body == {"code": "auth-code", "code_verifier": "verifier",
                    "code_challenge_method": "S256"}
    assert save_secret.call_args.args[-1] == "sk-or-secret"
    assert config["key_source"] == "keyring"
    assert "sk-or-secret" not in (tmp_path / "debug-model.json").read_text(encoding="utf-8")


def test_api_key_provider_reads_environment_without_saving_secret(tmp_path, monkeypatch):
    received = []

    class Model(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.headers.get("Authorization"))
            self.rfile.read(int(self.headers["Content-Length"]))
            data = b'{"choices":[{"message":{"content":"OK"}}]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("MANGEKYO_TEST_KEY", "test-secret")
        save_model_config(tmp_path, provider="custom", model="fixture",
                          base_url=f"http://127.0.0.1:{server.server_port}/v1",
                          key_env="MANGEKYO_TEST_KEY")
        assert probe_model(tmp_path) == "OK"
        assert ask(tmp_path, "hello")["reply"] == "OK"
        assert received == ["Bearer test-secret", "Bearer test-secret"]
        assert "test-secret" not in (tmp_path / "debug-model.json").read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()


def test_named_provider_key_cannot_be_sent_to_alternate_host(tmp_path):
    with pytest.raises(ValueError, match="Choose custom"):
        save_model_config(tmp_path, provider="openai", model="fixture",
                          base_url="https://another.example/v1")
