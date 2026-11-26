"""Check the packaged Windows command through its complete local recovery flow."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main() -> None:
    executable = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="mangekyo-release-") as directory:
        home = Path(directory) / "history"

        def invoke(*args: str) -> str:
            completed = subprocess.run(
                [str(executable), "--home", str(home), *args],
                text=True, capture_output=True, check=True, timeout=120,
            )
            return completed.stdout

        invoke("setup")
        original = json.JSONDecoder().raw_decode(invoke("demo"))[0]
        run_id, snapshot_id = original["run_id"], original["snapshot_id"]
        failed = json.loads(invoke("show", run_id))
        assert failed["status"] == "failed", failed
        pdf = next(item for item in failed["artifacts"] if item["name"].endswith(".pdf"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen(
            [str(executable), "--home", str(home), "dashboard",
             "--port", str(port), "--no-open"],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        try:
            preview_url = f"http://127.0.0.1:{port}/api/artifact/{pdf['id']}/page/0"
            for _ in range(150):
                if process.poll() is not None:
                    raise AssertionError("Packaged dashboard exited before serving")
                try:
                    with urllib.request.urlopen(preview_url, timeout=2) as response:
                        preview = response.read()
                    break
                except urllib.error.URLError:
                    time.sleep(.1)
            else:
                raise AssertionError("Packaged PDF preview did not respond")
            assert preview.startswith(b"\x89PNG\r\n\x1a\n"), "Packaged PDF preview is not PNG"
        finally:
            if sys.platform == "win32":
                # PyInstaller one-file mode launches a child that owns the SQLite handle.
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, text=True, timeout=10)
            elif process.poll() is None:
                process.terminate()
            process.wait(timeout=10)

        invoke("branch", snapshot_id, "-m", "release-smoke", "--replacement", "safe")
        corrected = json.loads(invoke("resume", "release-smoke"))
        assert corrected["skipped_steps"] > 0, corrected
        child = json.loads(invoke("show", corrected["run_id"]))
        assert child["status"] == "completed", child

        report = json.loads(invoke("benchmark", run_id))
        assert report["source_run"] == run_id, report
        assert report["recovered"], report
        stats = json.loads(invoke("cache", "stats"))
        assert stats["context_object_references"] > stats["context_unique_objects"], stats
        assert stats["context_saved_bytes"] > 0, stats
        print(f"Packaged recovery passed: {run_id} -> {corrected['run_id']}")


if __name__ == "__main__":
    main()
