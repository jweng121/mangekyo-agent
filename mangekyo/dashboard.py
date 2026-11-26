"""Loopback dashboard over the same local store as the CLI and TUI."""

from __future__ import annotations

import json
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .demo import benchmark, resume, resume_unavailable_reason
from .checks import outcome_from_events
from .checks import check_run
from .capture import capture_report
from .chat_service import (ask as ask_model, exchange_openrouter_code, model_config,
                           save_model_config, sessions as chat_sessions, verify_model)
from .evidence import pdf_page_count, render_pdf_page
from .commits import commit_branch
from .diagnosis import mark_divergence
from .langgraph_api import ApiError, LangGraphApi
from .project import CONFIG
from .store import Store
from .tui_project import active_project, launch_config, register_project, resolve_launch

STATIC = Path(__file__).parent / "static"
ASSETS = Path(__file__).parent / "assets"


def serve(store_path: Path, *, port: int = 8765, open_browser: bool = True) -> None:
    langgraph_api = LangGraphApi(store_path)
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
                if path.startswith("/api/v1/"):
                    status, data = langgraph_api.get(path)
                    self._json(status, data)
                elif path in {"/", "/index.html"}:
                    self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                elif path == "/logo.png":
                    self._send(200, (ASSETS / "logo.png").read_bytes(), "image/png")
                elif path == "/crow-tui-image.png":
                    self._send(200, (ASSETS / "crow-tui-image.png").read_bytes(), "image/png")
                elif path == "/crow-dashboard-eye.png":
                    self._send(200, (ASSETS / "crow-dashboard-eye.png").read_bytes(), "image/png")
                elif path == "/terminal-banner.png":
                    self._send(200, (ASSETS / "terminal-banner.png").read_bytes(), "image/png")
                elif path == "/app.js":
                    self._send(200, (STATIC / "app.js").read_bytes(), "text/javascript; charset=utf-8")
                elif path == "/api/runs":
                    with Store(store_path) as store:
                        branches = store.branches()
                        for branch in branches:
                            branch["source_run"] = store.one("snapshots", branch["source_snapshot"])["run_id"]
                        runs = store.runs()
                        for run in runs:
                            run["outcome"] = outcome_from_events(store.events(run["id"]))
                        self._json(200, {"runs": runs, "branches": branches, "store": str(store.path)})
                elif path == "/api/chat/model":
                    self._json(200, {"model": model_config(store_path)})
                elif path == "/api/chat/sessions":
                    self._json(200, {"sessions": chat_sessions(store_path)})
                elif path == "/api/project":
                    project = active_project(store_path)
                    self._json(200, {"project": str(project) if project else None,
                                     "launch": launch_config(project) if project else None})
                elif path.startswith("/api/run/"):
                    ident = unquote(path.removeprefix("/api/run/"))
                    with Store(store_path) as store:
                        run = store.one("runs", ident)
                        events = store.events(ident)
                        run["outcome"] = outcome_from_events(events)
                        snapshots = store.snapshots(ident)
                        artifacts = store.artifacts(ident)
                        self._json(200, {"run": run, "events": events,
                                         "snapshots": snapshots, "artifacts": artifacts,
                                         "capture": capture_report(store, ident, events=events,
                                                                   snapshots=snapshots, artifacts=artifacts),
                                         "benchmark": benchmark(store, run["parent_run"] or ident) if run["adapter"] == "mangekyo.simulation"
                                         else langgraph_api.benchmarks_for_run(store, ident) if run["adapter"] == "langgraph" else None})
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
                                         "resume_unavailable_reason": (None if not branch["result_run"] else
                                                                       f"Already resumed as {branch['result_run']}")
                                         if store.one("snapshots", branch["source_snapshot"])["adapter"] == "langgraph"
                                         else resume_unavailable_reason(store, name),
                                         "changed": [k for k in before.keys() | (after or {}).keys()
                                                     if after is not None and before.get(k) != after.get(k)]})
                else:
                    self._json(404, {"error": "Not found"})
            except ApiError as exc:
                self._json(exc.status, {"error": str(exc)})
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
                if self.path.startswith("/api/v1/"):
                    status, data = langgraph_api.post(urlparse(self.path).path, body)
                    self._json(status, data)
                    return
                with Store(store_path) as store:
                    if self.path == "/api/branch":
                        name = body["name"].strip()
                        if not name or len(name) > 80:
                            raise ValueError("Branch name must be 1–80 characters")
                        snapshot = store.one("snapshots", body["snapshot"])
                        correction = body.get("correction")
                        if correction is None:
                            correction = {"replacement": body.get("replacement", "safe")}
                        if snapshot["adapter"] == "langgraph" and (not correction or
                            not isinstance(correction, dict)):
                            raise ValueError("LangGraph branches need a correction field")
                        store.branch(body["snapshot"], name, correction)
                        self._json(201, {"name": name})
                    elif self.path == "/api/resume":
                        branch = store.one("branches", body["branch"])
                        snapshot = store.one("snapshots", branch["source_snapshot"])
                        if snapshot["adapter"] == "langgraph":
                            project = active_project(store_path)
                            result = LangGraphApi(store_path, project_config=(project / CONFIG)
                                                  if project else None)._resume(store, body["branch"])
                        else:
                            result = resume(store, body["branch"])
                        self._json(200, result)
                    elif self.path == "/api/check":
                        project = active_project(store_path)
                        case_path = Path(body["file"])
                        if not case_path.is_absolute() and project:
                            case_path = project / case_path
                        case = json.loads(case_path.read_text(encoding="utf-8"))
                        if body.get("event_id"):
                            case["event_id"] = body["event_id"]
                        self._json(200, check_run(store, body["run_id"], case))
                    elif self.path == "/api/mark":
                        self._json(200, mark_divergence(store, body["run_id"],
                                                        body["event_id"], body["reason"]))
                    elif self.path == "/api/commit":
                        self._json(200, commit_branch(store, body["branch"]))
                    elif self.path == "/api/benchmark":
                        source = store.one("runs", body["run"])
                        if source["parent_run"] or source["adapter"] != "mangekyo.simulation":
                            raise ValueError("Select a reference source run to benchmark")
                        if not any(b["result_run"] and store.one("snapshots", b["source_snapshot"])["run_id"] == source["id"]
                                   for b in store.branches()):
                            raise ValueError("Resume a corrected branch before benchmarking")
                        self._json(200, benchmark(store, source["id"], create_baseline=True))
                    elif self.path == "/api/annotation":
                        ident = store.annotate(body["artifact"], int(body["page"]),
                                               float(body["x"]), float(body["y"]),
                                               float(body["width"]), float(body["height"]),
                                               body["note"])
                        self._json(201, {"id": ident})
                    elif self.path == "/api/chat/model":
                        config = save_model_config(store_path, provider=body["provider"],
                                                   model=body["model"],
                                                   base_url=body.get("base_url"),
                                                   api_key=body.get("api_key"),
                                                   key_env=body.get("key_env"))
                        reply = verify_model(store_path)
                        self._json(200, {"model": config, "test_reply": reply})
                    elif self.path == "/api/chat/oauth/exchange":
                        config = exchange_openrouter_code(store_path, code=body["code"],
                                                          verifier=body["verifier"],
                                                          model=body["model"])
                        reply = verify_model(store_path)
                        self._json(200, {"model": config, "test_reply": reply})
                    elif self.path == "/api/chat":
                        self._json(200, ask_model(store_path, body["prompt"],
                                                  session_id=body.get("session"),
                                                  run_id=body.get("run_id")))
                    elif self.path == "/api/project":
                        project_path = Path(body["path"]).expanduser().resolve()
                        self._json(200, register_project(project_path, store_path))
                    elif self.path == "/api/project/launch":
                        project = active_project(store_path)
                        if not project:
                            raise ValueError("Connect an agent project first")
                        configured = launch_config(project)
                        if not configured:
                            raise ValueError("No launch command found in the project")
                        command = resolve_launch(project, configured)
                        launcher = ([sys.executable] if getattr(sys, "frozen", False)
                                    else [sys.executable, "-m", "mangekyo"])
                        process = subprocess.Popen(
                            [*launcher, "--home", str(store_path), "run", "--capture-output",
                             "--", *command], cwd=project, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
                        self._json(202, {"pid": process.pid})
                    else:
                        self._json(404, {"error": "Not found"})
            except ApiError as exc:
                self._json(exc.status, {"error": str(exc)})
            except (KeyError, ValueError, OSError, TypeError) as exc:
                self._json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self._json(409, {"error": str(exc)})

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
