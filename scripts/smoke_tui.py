"""Drive the terminal UI through correction, resume, and benchmark commands."""

from __future__ import annotations

import threading
import time
import tempfile
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from prompt_toolkit.application import Application
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mangekyo.demo import run_demo
from mangekyo.store import Store
from mangekyo.tui import run_tui


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="mangekyo-tui-") as directory:
        home = Path(directory)
        with Store(home) as store:
            demo = run_demo(store)
            events = store.events(demo["run_id"])
            selected = next(i + 1 for i, event in enumerate(events)
                            if event["snapshot_id"] == demo["snapshot_id"])

        ready = threading.Event()
        failures: list[BaseException] = []
        created_app = None
        database = home / "history.sqlite3"

        def wait_for(query: str, parameters: tuple[str, ...] = ()) -> None:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                with closing(sqlite3.connect(database)) as connection:
                    if connection.execute(query, parameters).fetchone():
                        return
                time.sleep(.1)
            raise AssertionError(f"TUI state did not appear: {query}")

        with create_pipe_input() as pipe:
            def create_app(**kwargs):
                nonlocal created_app
                app = Application(**kwargs, input=pipe, output=DummyOutput())
                created_app = app
                ready.set()
                return app

            def worker() -> None:
                try:
                    with patch("mangekyo.tui.Application", side_effect=create_app):
                        with Store(home) as store:
                            run_tui(store)
                except BaseException as exc:
                    failures.append(exc)
                    ready.set()

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            assert ready.wait(10), "TUI did not start"
            if failures:
                raise failures[0]
            pipe.send_text("/help\r")
            time.sleep(.2)
            pipe.send_text("\x1b[A")
            time.sleep(.2)
            assert created_app.layout.current_buffer.text == "/help", "Up did not recall the last command"
            pipe.send_text("\x1b[B")
            time.sleep(.2)
            assert created_app.layout.current_buffer.text == "", "Down did not restore the empty draft"
            pipe.send_text("/runs\r")
            time.sleep(.2)
            pipe.send_text("\x1b[A\x1b[A")
            time.sleep(.2)
            assert created_app.layout.current_buffer.text == "/help", "Repeated Up did not traverse history"
            pipe.send_text("\x1b[B\x1b[B")
            time.sleep(.2)
            assert created_app.layout.current_buffer.text == "", "Repeated Down did not return to the draft"
            pipe.send_text(f"/event {selected}\r")
            time.sleep(.2)
            pipe.send_text("/branch tui-fixed\r")
            wait_for("SELECT 1 FROM branches WHERE name='tui-fixed'")
            pipe.send_text("/resume tui-fixed\r")
            wait_for("SELECT 1 FROM branches WHERE name='tui-fixed' AND result_run IS NOT NULL")
            pipe.send_text("/benchmark\r")
            wait_for("SELECT 1 FROM runs WHERE label='Cold corrected baseline'")
            pipe.send_text("/quit\r")
            thread.join(timeout=15)
            if thread.is_alive():
                pipe.send_text("\x11")
                thread.join(timeout=3)
                raise AssertionError("TUI did not exit after the workflow")
            if failures:
                raise failures[0]

        with Store(home) as store:
            branch = store.one("branches", "tui-fixed")
            assert branch["result_run"], "TUI did not resume the correction"
            assert store.one("runs", branch["result_run"])["status"] == "completed"
            assert any(run["label"] == "Cold corrected baseline" for run in store.runs()), \
                "TUI did not run the cold benchmark"
        print("TUI smoke passed: checkpoint, branch, resume, and benchmark")


if __name__ == "__main__":
    main()
