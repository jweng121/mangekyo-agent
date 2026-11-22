"""Loopback dashboard over the same local store as the CLI and TUI."""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .demo import benchmark, resume, resume_unavailable_reason
from .evidence import pdf_page_count, render_pdf_page
from .store import Store

STATIC = Path(__file__).parent / "static"


def serve(store_path: Path, *, port: int = 8765, open_browser: bool = True) -> None:
    class Handler(BaseHTTPRequestHandler):
        def _local_host(self) -> bool:
            if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                self._json(403, {"error": "Dashboard is local only"})
                return False
            return True

        def _send(self, status: int, payload: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'")
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status: int, data: object) -> None:
            self._send(status, json.dumps(data, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            if not self._local_host():
                return
            path = urlparse(self.path).path
            try:
                if path in {"/", "/index.html"}:
                    self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                elif path == "/logo.png":
                    self._send(200, (STATIC / "logo.png").read_bytes(), "image/png")
                elif path == "/app.js":
                    self._send(200, (STATIC / "app.js").read_bytes(), "text/javascript; charset=utf-8")
                elif path == "/api/runs":
                    with Store(store_path) as store:
                        branches = store.branches()
                        for branch in branches:
                            branch["source_run"] = store.one("snapshots", branch["source_snapshot"])["run_id"]
                        self._json(200, {"runs": store.runs(), "branches": branches, "store": str(store.path)})
                elif path.startswith("/api/run/"):
                    ident = unquote(path.removeprefix("/api/run/"))
                    with Store(store_path) as store:
                        run = store.one("runs", ident)
                        self._json(200, {"run": run, "events": store.events(ident),
                                         "snapshots": store.snapshots(ident), "artifacts": store.artifacts(ident),
                                         "benchmark": benchmark(store, run["parent_run"] or ident) if run["adapter"] == "mangekyo.simulation" else None})
                elif path.startswith("/api/artifact/"):
                    parts = path.split("/")
                    if len(parts) < 4:
                        raise ValueError("Artifact ID is missing")
                    ident = unquote(parts[3])
                    with Store(store_path) as store:
                        artifact = store.one("artifacts", ident)
                        if len(parts) == 4:
                            count = pdf_page_count(store.get_blob(artifact["blob_hash"])) if artifact["mime"] == "application/pdf" else 1
                            self._json(200, {"artifact": artifact, "page_count": count,
                                             "parsed_text": store.get(artifact["parsed_hash"])["text"] if artifact["parsed_hash"] else None,
                                             "annotations": store.annotations(ident)})
                        elif len(parts) == 5 and parts[4] == "raw":
                            self._send(200, store.get_blob(artifact["blob_hash"]), artifact["mime"])
                        elif len(parts) == 6 and parts[4] == "page":
                            page = int(parts[5])
                            data = store.get_blob(artifact["blob_hash"])
                            if artifact["mime"] == "application/pdf":
                                data, _ = render_pdf_page(data, page)
                                self._send(200, data, "image/png")
                            elif page == 0:
                                self._send(200, data, artifact["mime"])
                            else:
                                raise ValueError("Image has one page")
                        else:
                            raise ValueError("Invalid artifact path")
                elif path.startswith("/api/snapshot/"):
                    ident = unquote(path.removeprefix("/api/snapshot/"))
                    with Store(store_path) as store:
                        snap = store.one("snapshots", ident)
                        self._json(200, {"snapshot": snap, "context": store.context(ident),
                                         "environment_restorable": bool(snap["env_hash"] and snap["adapter"] == "mangekyo.simulation")})
                elif path.startswith("/api/branch/"):
                    name = unquote(path.removeprefix("/api/branch/"))
                    with Store(store_path) as store:
                        branch = store.one("branches", name)
                        before = store.context(branch["source_snapshot"])
                        after = None
                        if branch["result_run"]:
                            snaps = store.snapshots(branch["result_run"])
                            after = store.context(snaps[0]["id"]) if snaps else None
                        self._json(200, {"branch": branch, "correction": store.get(branch["correction_hash"]),
                                         "before": before, "after": after,
                                         "resume_unavailable_reason": resume_unavailable_reason(store, name),
                                         "changed": [k for k in before.keys() | (after or {}).keys()
                                                     if after is not None and before.get(k) != after.get(k)]})
                else:
                    self._json(404, {"error": "Not found"})
            except (KeyError, ValueError, OSError) as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self) -> None:
            if not self._local_host():
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                self._json(403, {"error": "Invalid origin"})
                return
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 100_000:
                self._json(413, {"error": "Invalid request size"})
                return
            try:
                body = json.loads(self.rfile.read(size))
                with Store(store_path) as store:
                    if self.path == "/api/branch":
                        name = body["name"].strip()
                        if not name or len(name) > 80:
                            raise ValueError("Branch name must be 1–80 characters")
                        store.branch(body["snapshot"], name, {"replacement": body.get("replacement", "safe")})
                        self._json(201, {"name": name})
                    elif self.path == "/api/resume":
                        self._json(200, resume(store, body["branch"]))
                    elif self.path == "/api/annotation":
                        ident = store.annotate(body["artifact"], int(body["page"]),
                                               float(body["x"]), float(body["y"]),
                                               float(body["width"]), float(body["height"]),
                                               body["note"])
                        self._json(201, {"id": ident})
                    else:
                        self._json(404, {"error": "Not found"})
            except (KeyError, ValueError, OSError, TypeError) as exc:
                self._json(400, {"error": str(exc)})

        def log_message(self, _format: str, *args: object) -> None:
            pass

    address = f"http://127.0.0.1:{port}"
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Mangekyo dashboard: {address}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
