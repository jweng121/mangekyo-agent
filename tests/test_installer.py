"""The Windows beta installer selects prereleases and verifies downloads."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell installer runs on Windows")
@pytest.mark.parametrize("valid_checksum", [False, True])
def test_installer_selects_beta_and_preserves_install_on_failure(tmp_path, valid_checksum):
    requests = []
    downloaded = b"deliberately not an executable"

    class ReleaseServer(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            base = f"http://127.0.0.1:{self.server.server_port}"
            if self.path == "/releases":
                def release(tag, published):
                    return {"tag_name": tag, "draft": False, "published_at": published,
                            "assets": [
                                {"name": "SHA256SUMS.txt", "browser_download_url":
                                 f"{base}/{tag}/SHA256SUMS.txt"},
                                {"name": "mangekyo-windows-x64.exe", "browser_download_url":
                                 f"{base}/{tag}/mangekyo-windows-x64.exe"},
                            ]}
                body = json.dumps([
                    release("v0.1.1", "2026-11-20T00:00:00Z"),
                    release("v0.2.0-beta.1", "2026-11-24T00:00:00Z"),
                ]).encode()
                content_type = "application/json"
            elif self.path.endswith("/SHA256SUMS.txt"):
                digest = hashlib.sha256(downloaded).hexdigest() if valid_checksum else "0" * 64
                body = (digest + "  mangekyo-windows-x64.exe\n").encode()
                content_type = "text/plain"
            elif self.path.endswith("/mangekyo-windows-x64.exe"):
                body = downloaded
                content_type = "application/octet-stream"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), ReleaseServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        root = Path(__file__).resolve().parents[1]
        destination = tmp_path / "install"
        if valid_checksum:
            destination.mkdir()
            (destination / "mangekyo.exe").write_bytes(b"existing install")
        completed = subprocess.run([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(root / "install.ps1"),
            "-ReleaseApiUrl", f"http://127.0.0.1:{server.server_port}/releases",
            "-InstallDir", str(destination), "-SkipPath", "-NoPrompt",
        ], capture_output=True, text=True, timeout=30)
        assert completed.returncode != 0
        assert "Selected Mangekyo release v0.2.0-beta.1" in completed.stdout
        if valid_checksum:
            assert "Quick start: initializing local history" in completed.stdout
            assert (destination / "mangekyo.exe").read_bytes() == b"existing install"
        else:
            assert "failed its SHA256 check" in completed.stderr
            assert not (destination / "mangekyo.exe").exists()
        assert "/v0.2.0-beta.1/SHA256SUMS.txt" in requests
        assert "/v0.2.0-beta.1/mangekyo-windows-x64.exe" in requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
