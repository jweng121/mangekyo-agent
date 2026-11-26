"""Drive the packaged sample from terminal chat through correction and rerun."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from prompt_toolkit.application import Application
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mangekyo.chat_service import save_model_config, verify_model
from mangekyo.sample_project import create_sample
from mangekyo.store import Store
from mangekyo.tui import run_tui


ROOT = Path(__file__).resolve().parents[1]


def test_chat_sample_run_to_future_fix(tmp_path, monkeypatch):
    model_requests = []

    class Model(BaseHTTPRequestHandler):
        def do_POST(self):
            model_requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            data = b'{"choices":[{"message":{"content":"The PDF asks for bookings. Check selected_table=bookings."}}]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    home = tmp_path / "history"
    project = create_sample(tmp_path / "chat-sample")
    monkeypatch.setenv("PYTHONPATH", str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    monkeypatch.setenv("MANGEKYO_SQL_STEP_DELAY", "0")
    save_model_config(home, provider="local", model="fixture",
                      base_url=f"http://127.0.0.1:{model.server_port}/v1")
    verify_model(home)
    ready = threading.Event()
    failures = []
    with create_pipe_input() as pipe:
        def make_app(**kwargs):
            app = Application(**kwargs, input=pipe, output=DummyOutput())
            ready.set()
            return app

        def worker():
            try:
                with patch("mangekyo.tui.Application", side_effect=make_app):
                    with Store(home) as store:
                        run_tui(store, start_view="home", chat_mode=True)
            except BaseException as exc:
                failures.append(exc)
                ready.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert ready.wait(10)

        def wait_for(predicate, label):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if failures:
                    raise failures[0]
                with Store(home) as store:
                    if predicate(store):
                        return
                time.sleep(.1)
            raise AssertionError(f"Timed out waiting for {label}")

        def send(value):
            pipe.send_text(value + "\r")
            time.sleep(.18)

        try:
            send(f"/add {project}")
            wait_for(lambda _store: (home / "tui-project.json").is_file(), "project connection")
            time.sleep(.2)
            send("/launch")
            wait_for(lambda store: bool(store.runs() and store.runs()[0]["status"] == "completed"),
                     "source run")
            with Store(home) as store:
                source = store.runs()[0]["id"]
                events = store.events(source)
                tool = next(event for event in events if event["kind"] == "tool" and
                            event["payload"].get("payload", {}).get("name") == "select_table")
                checkpoint = next(event for event in events if event["kind"] == "checkpoint" and
                                  event["payload"].get("name") == "after-choose")
            send("/home")
            send("/use 1")
            send("Why did this agent answer 1 instead of 3?")
            deadline = time.monotonic() + 5
            while len(model_requests) < 2 and time.monotonic() < deadline:
                time.sleep(.1)
            assert "Count Toronto bookings" in model_requests[-1]["messages"][0]["content"]
            send("/runs")
            send("/check expected.json")
            wait_for(lambda store: any(event["kind"] == "eval_result" and
                                       not event["payload"]["passed"]
                                       for event in store.events(source)), "failed output check")
            send(f"/event {tool['seq']}")
            send("/check tool-expected.json selected")
            wait_for(lambda store: any(event["kind"] == "eval_result" and
                                       event["payload"].get("source_event_seq") == tool["seq"] and
                                       not event["payload"]["passed"]
                                       for event in store.events(source)), "failed tool check")
            send("/mark Selected invoices for bookings")
            wait_for(lambda store: any(event["kind"] == "diagnosis" and
                                       event["payload"]["classification"] == "verified"
                                       for event in store.events(source)), "verified mark")
            send(f"/event {checkpoint['seq']}")
            send("/branch chat-bookings selected_table=bookings")
            wait_for(lambda store: any(branch["name"] == "chat-bookings"
                                       for branch in store.branches()), "branch")
            send("/resume chat-bookings")
            wait_for(lambda store: bool(store.one("branches", "chat-bookings")["result_run"]),
                     "resumed branch")
            with Store(home) as store:
                child = store.one("branches", "chat-bookings")["result_run"]
            send("/check expected.json")
            wait_for(lambda store: any(event["kind"] == "eval_result" and
                                       event["payload"]["passed"]
                                       for event in store.events(child)), "passing branch check")
            send("/commit chat-bookings")
            wait_for(lambda _store: bool(list((home / "commits").glob("*.json"))), "commit")
            (project / "active-sql-model.json").write_text(
                json.dumps({"version": "v2", "table_for_bookings": "bookings"}), encoding="utf-8")
            send("/launch")
            wait_for(lambda store: any(run["id"] not in {source, child} and
                                       run["status"] == "completed" for run in store.runs()),
                     "future run")
            with Store(home) as store:
                future = next(run["id"] for run in store.runs() if run["id"] not in {source, child})
            send("/run 1")
            send("/check expected.json")
            wait_for(lambda store: any(event["kind"] == "eval_result" and
                                       event["payload"]["passed"]
                                       for event in store.events(future)), "passing future check")
            send("/quit")
            thread.join(timeout=10)
            assert not thread.is_alive()
            assert not failures
        finally:
            if thread.is_alive():
                pipe.send_text("\x11")
                thread.join(timeout=3)
            model.shutdown()
            model.server_close()
