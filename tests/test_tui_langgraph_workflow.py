"""Exercise a PDF-backed agent correction entirely through TUI commands."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

from prompt_toolkit.application import Application
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mangekyo.store import Store
from mangekyo.tui import run_tui


ROOT = Path(__file__).resolve().parents[1]


def test_tui_launches_configured_agent_without_leaving_the_ui(tmp_path, monkeypatch):
    project = ROOT / "examples" / "sql-user-demo"
    home = tmp_path / "history"
    monkeypatch.chdir(tmp_path)
    ready = threading.Event()
    failures = []
    with create_pipe_input() as pipe:
        def create_app(**kwargs):
            app = Application(**kwargs, input=pipe, output=DummyOutput())
            ready.set()
            return app

        def worker():
            try:
                with patch("mangekyo.tui.Application", side_effect=create_app):
                    with Store(home) as store:
                        run_tui(store)
            except BaseException as exc:
                failures.append(exc)
                ready.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert ready.wait(10)
        pipe.send_text(f"add {project}\r")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (home / "tui-project.json").is_file():
            time.sleep(.1)
        assert (home / "tui-project.json").is_file()
        time.sleep(.2)
        pipe.send_text("launch --capture-output\r")
        deadline = time.monotonic() + 15
        source = None
        while time.monotonic() < deadline:
            if failures:
                raise failures[0]
            with Store(home) as store:
                runs = store.runs()
                if (runs and runs[0]["status"] == "completed" and
                        any(event["kind"] == "process_output"
                            for event in store.events(runs[0]["id"]))):
                    source = runs[0]["id"]
                    assert store.artifacts(source)[0]["name"] == "booking-request.pdf"
                    break
            time.sleep(.1)
        assert source is not None
        pipe.send_text("refresh\r")
        pipe.send_text("check expected.json\r")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with Store(home) as store:
                if any(event["kind"] == "eval_result" and not event["payload"]["passed"]
                       for event in store.events(source)):
                    break
            time.sleep(.1)
        else:
            raise AssertionError("TUI did not inspect the launched run")
        pipe.send_text("quit\r")
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert not failures


def test_pdf_agent_check_branch_resume_commit_in_tui(tmp_path, monkeypatch):
    project = tmp_path / "agent"
    project.mkdir()
    fixture = ROOT / "examples" / "sql-user-demo"
    for name in (".mangekyo-agent.json", "active-sql-model.json", "booking-request.pdf",
                 "expected.json", "tool-expected.json"):
        shutil.copy2(fixture / name, project / name)
    home = tmp_path / "history"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT) + os.pathsep + environment.get("PYTHONPATH", "")
    environment["MANGEKYO_SQL_STEP_DELAY"] = "0"
    subprocess.run([sys.executable, "-m", "mangekyo", "--home", str(home), "run", "--",
                    sys.executable, str(ROOT / "scripts" / "sql_cli_agent.py")],
                   cwd=project, env=environment, capture_output=True, text=True,
                   check=True, timeout=30)
    with Store(home) as store:
        source = store.runs()[0]["id"]
        events = store.events(source)
        tool_number = next(i + 1 for i, event in enumerate(events)
                           if event["kind"] == "tool" and
                           event["payload"].get("payload", {}).get("name") == "select_table")
        checkpoint_number = next(i + 1 for i, event in enumerate(events)
                                 if event["kind"] == "checkpoint" and
                                 event["payload"].get("name") == "after-choose")
        assert store.artifacts(source)[0]["name"] == "booking-request.pdf"
        snapshot_id = events[checkpoint_number - 1]["snapshot_id"]
        assert "Question: Count Toronto bookings" in store.context(snapshot_id)["state"]["parsed_document_text"]

    monkeypatch.chdir(tmp_path)
    ready = threading.Event()
    failures = []
    with create_pipe_input() as pipe:
        def create_app(**kwargs):
            app = Application(**kwargs, input=pipe, output=DummyOutput())
            ready.set()
            return app

        def worker():
            try:
                with patch("mangekyo.tui.Application", side_effect=create_app):
                    with Store(home) as store:
                        run_tui(store)
            except BaseException as exc:
                failures.append(exc)
                ready.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert ready.wait(10)
        pipe.send_text(f"add {project}\r")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (home / "tui-project.json").is_file():
            time.sleep(.1)
        assert (home / "tui-project.json").is_file()
        time.sleep(.2)

        def send(command, predicate):
            pipe.send_text(command + "\r")
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if failures:
                    raise failures[0]
                with Store(home) as store:
                    if predicate(store):
                        return
                time.sleep(.1)
            raise AssertionError(f"TUI command did not finish: {command}")

        send("check expected.json", lambda store: any(
            event["kind"] == "eval_result" and not event["payload"]["passed"]
            for event in store.events(source)))
        pipe.send_text(f"event {tool_number}\r")
        send("check tool-expected.json selected", lambda store: any(
            event["kind"] == "eval_result" and
            event["payload"].get("source_event_seq") == tool_number and
            not event["payload"]["passed"] for event in store.events(source)))
        send("mark Selected invoices for bookings", lambda store: any(
            event["kind"] == "diagnosis" and event["payload"]["classification"] == "verified"
            for event in store.events(source)))
        pipe.send_text(f"event {checkpoint_number}\r")
        send("branch tui-bookings selected_table=bookings", lambda store: any(
            branch["name"] == "tui-bookings" for branch in store.branches()))
        send("resume tui-bookings", lambda store: bool(
            (child_id := store.one("branches", "tui-bookings")["result_run"])
            and store.one("runs", child_id)["status"] == "completed"))
        time.sleep(.2)
        with Store(home) as store:
            child = store.one("branches", "tui-bookings")["result_run"]
            assert store.one("runs", child)["status"] == "completed"
        send("check expected.json", lambda store: any(
            event["kind"] == "eval_result" and event["payload"]["passed"]
            for event in store.events(child)))
        send("commit tui-bookings", lambda store: bool(list((home / "commits").glob("*.json"))))
        pipe.send_text("quit\r")
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert not failures
