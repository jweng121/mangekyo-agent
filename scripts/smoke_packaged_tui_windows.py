"""Drive a packaged Windows TUI through a real ConPTY terminal."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2 or sys.platform != "win32":
        raise SystemExit("Usage on Windows: smoke_packaged_tui_windows.py PATH_TO_MANGEKYO")
    from winpty import PtyProcess

    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="mangekyo-packaged-tui-") as directory:
        home = Path(directory) / "history"

        def invoke(*args: str) -> str:
            result = subprocess.run([str(executable), "--home", str(home), *args],
                                    text=True, capture_output=True, check=True, timeout=120)
            return result.stdout

        invoke("setup")
        demo = json.JSONDecoder().raw_decode(invoke("demo"))[0]
        database = home / "history.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            row = connection.execute(
                "SELECT seq FROM events WHERE run_id=? AND snapshot_id=? ORDER BY seq LIMIT 1",
                (demo["run_id"], demo["snapshot_id"])).fetchone()
            assert row, "Demo checkpoint is missing from event history"
            event_number = row[0]

        env = {**os.environ, "MANGEKYO_BANNER": "unicode"}
        process = PtyProcess.spawn([str(executable), "--home", str(home), "--tui"],
                                   dimensions=(45, 120), env=env)
        output: list[str] = []

        def read_output() -> None:
            while True:
                try:
                    output.append(process.read(65536))
                except EOFError:
                    return

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()

        def recent_output() -> str:
            return "".join(output)[-700:]

        def wait_for(check, description: str) -> None:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if check():
                    return
                if not process.isalive():
                    raise AssertionError(f"TUI exited while waiting for {description}: {recent_output()!r}")
                time.sleep(.1)
            raise AssertionError(f"TUI did not show {description}: {recent_output()!r}")

        def has_row(query: str) -> bool:
            with closing(sqlite3.connect(database)) as connection:
                return connection.execute(query).fetchone() is not None

        def send(command: str) -> None:
            process.write(command + "\r")

        try:
            wait_for(lambda: "Select a run" in "".join(output), "the command panel")
            send(f"event {event_number}")
            time.sleep(.2)
            send("branch packaged-fix")
            wait_for(lambda: has_row("SELECT 1 FROM branches WHERE name='packaged-fix'"), "the branch")
            send("resume packaged-fix")
            wait_for(lambda: has_row("SELECT 1 FROM branches WHERE name='packaged-fix' AND result_run IS NOT NULL"),
                     "the resumed run")
            send("benchmark")
            wait_for(lambda: has_row("SELECT 1 FROM runs WHERE label='Cold corrected baseline'"),
                     "the cold baseline")
            wait_for(lambda: "Cold comparison:" in "".join(output), "the measured comparison")
            send("quit")
            wait_for(lambda: not process.isalive(), "terminal exit")
            assert process.exitstatus == 0, process.exitstatus
            print("Packaged Windows TUI smoke passed: visible recovery comparison and terminal exit")
        finally:
            process.close(force=True)
            reader.join(timeout=2)


if __name__ == "__main__":
    main()
