"""Install the built Windows executable from a loopback release feed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path,
                        help="Serve the exact release assets prepared for publication")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise RuntimeError("The PowerShell installer smoke runs on Windows")
    project = Path(__file__).resolve().parent.parent
    executable = (args.release_dir / "mangekyo-windows-x64.exe" if args.release_dir
                  else project / "dist" / "mangekyo.exe")
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    checksum = ((args.release_dir / "SHA256SUMS.txt").read_bytes() if args.release_dir
                else f"{digest}  mangekyo-windows-x64.exe\n".encode("ascii"))
    requests = []

    class ReleaseServer(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path == "/releases":
                base = f"http://127.0.0.1:{self.server.server_port}"
                def release(tag, published):
                    return {"tag_name": tag, "draft": False, "published_at": published,
                            "assets": [{"name": name, "browser_download_url": f"{base}/{tag}/{name}"}
                                       for name in ("SHA256SUMS.txt", "mangekyo-windows-x64.exe")]}
                body = json.dumps([release("v0.1.1", "2026-11-20T00:00:00Z"),
                                   release("v0.2.0-beta.1", "2026-11-24T00:00:00Z")]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/v0.2.0-beta.1/SHA256SUMS.txt":
                body = checksum
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/v0.2.0-beta.1/mangekyo-windows-x64.exe":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(executable.stat().st_size))
                self.end_headers()
                with executable.open("rb") as stream:
                    shutil.copyfileobj(stream, self.wfile)
            else:
                self.send_error(404)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ReleaseServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="mangekyo-installer-") as directory:
            root = Path(directory)
            install = root / "bin"
            home = root / "history"
            base = f"http://127.0.0.1:{server.server_port}"
            env = {**os.environ, "MANGEKYO_HOME": str(home)}
            result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy",
                                     "Bypass", "-File", str(project / "install.ps1"),
                                     "-ReleaseApiUrl", base + "/releases", "-InstallDir", str(install),
                                     "-SkipPath", "-NoPrompt"], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise AssertionError(f"Installer failed:\n{result.stdout}\n{result.stderr}")
            assert "Selected Mangekyo release v0.2.0-beta.1" in result.stdout
            assert "/v0.2.0-beta.1/SHA256SUMS.txt" in requests
            assert "/v0.2.0-beta.1/mangekyo-windows-x64.exe" in requests
            installed = install / "mangekyo.exe"
            assert hashlib.sha256(installed.read_bytes()).hexdigest() == digest
            assert (home / "history.sqlite3").is_file()
            demo = subprocess.run([str(installed), "--home", str(home), "demo"],
                                  cwd=root, env=env, capture_output=True,
                                  text=True, check=True, timeout=120)
            run = json.JSONDecoder().raw_decode(demo.stdout)[0]
            assert run["run_id"] and run["snapshot_id"]
            print(f"Installer smoke passed: beta selection, checksum, setup, and demo {run['run_id']}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
