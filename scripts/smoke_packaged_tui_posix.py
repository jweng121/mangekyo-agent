"""Drive a packaged POSIX TUI through a real pseudo terminal."""

from __future__ import annotations

import fcntl
import json
import os
import pty
import sqlite3
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
from contextlib import closing
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2 or sys.platform not in {"linux", "darwin"}:
        raise SystemExit("Usage on Linux or macOS: smoke_packaged_tui_posix.py PATH_TO_MANGEKYO")
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="mangekyo-packaged-tui-") as directory:
        home = Path(directory) / "history"

        def invoke(*args: str) -> str:
            result = subprocess.run([str(executable), "--home", str(home), *args],
                                    text=True, capture_output=True, check=True, timeout=120)
            return result.stdout

        invoke("setup")
        demo = json.JSONDecoder().raw_decode(invoke("demo"))[0]
        with closing(sqlite3.connect(home / "history.sqlite3")) as connection:
            row = connection.execute(
                "SELECT seq FROM events WHERE run_id=? AND snapshot_id=? ORDER BY seq LIMIT 1",
                (demo["run_id"], demo["snapshot_id"])).fetchone()
            assert row, "Demo checkpoint is missing from event history"
            event_number = row[0]

        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 120, 0, 0))
        output = bytearray()

        def read_output() -> None:
            while True:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    return
                if not chunk:
                    return
                output.extend(chunk)

        env = {**os.environ, "TERM": "xterm-256color", "MANGEKYO_BANNER": "unicode"}
        process = subprocess.Popen([str(executable), "--home", str(home), "--tui"],
                                   stdin=slave, stdout=slave, stderr=slave, env=env)
        os.close(slave)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()

        def wait_for(check, description: str) -> None:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(f"TUI exited while waiting for {description}: {output[-700:]!r}")
                if check():
                    return
                time.sleep(.1)
            raise AssertionError(f"TUI did not show {description}: {output[-700:]!r}")

        def has_row(query: str) -> bool:
            with closing(sqlite3.connect(home / "history.sqlite3")) as connection:
                return connection.execute(query).fetchone() is not None

        def send(command: str) -> None:
            os.write(master, (command + "\r").encode())

        try:
            wait_for(lambda: b"Available commands" in output, "the command panel")
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
            wait_for(lambda: b"Cold comparison:" in output, "the measured comparison")
            send("quit")
            assert process.wait(timeout=10) == 0
            print("Packaged TUI smoke passed: visible recovery comparison and terminal exit")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            os.close(master)
            reader.join(timeout=2)


if __name__ == "__main__":
    main()
