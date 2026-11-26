"""Optional authenticated team server over the unchanged local run store."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import ssl
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .bundle import import_bundle
from .store import Store


WORKSPACE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
ROLES = {"viewer": 1, "editor": 2, "reviewer": 3, "admin": 4}
MAX_BUNDLE = 100_000_000
MAX_BODY = 64_000


class TeamError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def token_hash(token: str) -> str:
    if len(token) < 32:
        raise ValueError("Team tokens must have at least 32 characters")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _config(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    users = data.get("users") if isinstance(data, dict) else None
    if not isinstance(users, list) or not users:
        raise ValueError("Team config needs a nonempty users list")
    seen = set()
    for user in users:
        if not isinstance(user, dict) or set(user) != {"name", "workspace", "role", "token_sha256"}:
            raise ValueError("Each team user needs name, workspace, role, and token_sha256")
        if (not isinstance(user["name"], str) or not user["name"].strip()
                or not WORKSPACE.fullmatch(user["workspace"])
                or user["role"] not in ROLES
                or not re.fullmatch(r"[0-9a-f]{64}", user["token_sha256"])):
            raise ValueError("Team config contains an invalid user")
        if user["token_sha256"] in seen:
            raise ValueError("Team tokens must be unique")
        seen.add(user["token_sha256"])
    return users


@contextmanager
def _metadata(path: Path):
    connection = sqlite3.connect(path, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    try:
        with connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS comments (
                id TEXT PRIMARY KEY, workspace TEXT NOT NULL, run_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL, author TEXT NOT NULL,
                text TEXT NOT NULL, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY, workspace TEXT NOT NULL, run_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL, author TEXT NOT NULL,
                decision TEXT NOT NULL, note TEXT NOT NULL, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                id TEXT PRIMARY KEY, workspace TEXT NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, run_id TEXT, details TEXT NOT NULL,
                created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS comments_scope ON comments(workspace, run_id);
            CREATE INDEX IF NOT EXISTS reviews_scope ON reviews(workspace, run_id);
            CREATE INDEX IF NOT EXISTS audit_scope ON audit(workspace, created);
            """)
        with connection:
            yield connection
    finally:
        connection.close()


def _audit(connection: sqlite3.Connection, workspace: str, actor: str,
           action: str, run_id: str | None, details: dict) -> None:
    connection.execute("INSERT INTO audit VALUES (?,?,?,?,?,?,?)",
                       (uuid.uuid4().hex[:12], workspace, actor, action, run_id,
                        json.dumps(details, sort_keys=True), time.time()))


def _text(body: dict, name: str, *, max_length: int = 2000) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise TeamError(400, f"{name} must be 1-{max_length} characters")
    return value.strip()


def create_team_server(root: str | Path, config: str | Path, *, host: str = "127.0.0.1",
                       port: int = 8780, cert: str | Path | None = None,
                       key: str | Path | None = None) -> ThreadingHTTPServer:
    """Create a server; non-loopback listeners require a TLS certificate and key."""
    if host not in {"127.0.0.1", "localhost", "::1"} and not (cert and key):
        raise ValueError("Remote team listeners require --cert and --key for TLS")
    if bool(cert) != bool(key):
        raise ValueError("Provide both a TLS certificate and key")
    users = _config(Path(config))
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    metadata_path = root / "team.sqlite3"
    with _metadata(metadata_path):
        pass

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, data: bytes, mime: str = "application/json; charset=utf-8") -> None:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, value: Any) -> None:
            self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"))

        def _scope(self, minimum_role: str) -> tuple[str, dict, list[str]]:
            parts = [unquote(part) for part in urlparse(self.path).path.strip("/").split("/")]
            if len(parts) < 3 or parts[:2] != ["v1", "workspaces"] or not WORKSPACE.fullmatch(parts[2]):
                raise TeamError(404, "Not found")
            workspace = parts[2]
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                raise TeamError(401, "Bearer token required")
            digest = hashlib.sha256(auth[7:].encode("utf-8")).hexdigest()
            user = next((candidate for candidate in users
                         if hmac.compare_digest(candidate["token_sha256"], digest)), None)
            if user is None:
                raise TeamError(401, "Invalid team token")
            if user["workspace"] != workspace or ROLES[user["role"]] < ROLES[minimum_role]:
                raise TeamError(403, "Workspace access denied")
            return workspace, user, parts[3:]

        def _body(self, limit: int) -> dict:
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise TeamError(400, "Invalid Content-Length") from exc
            if size < 1 or size > limit:
                raise TeamError(413, "Request body is empty or too large")
            try:
                body = json.loads(self.rfile.read(size))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TeamError(400, "Invalid JSON body") from exc
            if not isinstance(body, dict):
                raise TeamError(400, "JSON body must be an object")
            return body

        def do_GET(self) -> None:
            try:
                workspace, user, rest = self._scope("viewer")
                with Store(root / "workspaces" / workspace) as store:
                    if rest == ["runs"]:
                        self._json(200, {"runs": store.runs()})
                    elif len(rest) == 2 and rest[0] == "runs":
                        run_id = rest[1]
                        run = store.one("runs", run_id)
                        self._json(200, {"run": run, "events": store.events(run_id),
                                         "snapshots": store.snapshots(run_id),
                                         "artifacts": store.artifacts(run_id)})
                    elif len(rest) == 4 and rest[0] == "runs" and rest[2] == "artifacts":
                        run_id, artifact_id = rest[1], rest[3]
                        store.one("runs", run_id)
                        artifact = store.one("artifacts", artifact_id)
                        if artifact["run_id"] != run_id:
                            raise TeamError(404, "Artifact not found in this run")
                        self._send(200, store.get_blob(artifact["blob_hash"]), artifact["mime"])
                    elif len(rest) == 5 and rest[0] == "runs" and rest[2] == "artifacts" and rest[4] == "detail":
                        run_id, artifact_id = rest[1], rest[3]
                        store.one("runs", run_id)
                        artifact = store.one("artifacts", artifact_id)
                        if artifact["run_id"] != run_id:
                            raise TeamError(404, "Artifact not found in this run")
                        parsed = store.get(artifact["parsed_hash"])["text"] if artifact["parsed_hash"] else None
                        self._json(200, {"artifact": artifact, "parsed_text": parsed,
                                         "annotations": store.annotations(artifact_id)})
                    elif len(rest) == 3 and rest[0] == "runs" and rest[2] in {"comments", "reviews"}:
                        run_id = rest[1]
                        store.one("runs", run_id)
                        with _metadata(metadata_path) as connection:
                            rows = [dict(row) for row in connection.execute(
                                f"SELECT * FROM {rest[2]} WHERE workspace=? AND run_id=? ORDER BY created",
                                (workspace, run_id))]
                        self._json(200, {rest[2]: rows})
                    elif rest == ["audit"]:
                        if ROLES[user["role"]] < ROLES["reviewer"]:
                            raise TeamError(403, "Workspace access denied")
                        with _metadata(metadata_path) as connection:
                            rows = [dict(row) for row in connection.execute(
                                "SELECT * FROM audit WHERE workspace=? ORDER BY created", (workspace,))]
                        self._json(200, {"audit": rows})
                    else:
                        raise TeamError(404, "Not found")
            except TeamError as exc:
                self._json(exc.status, {"error": str(exc)})
            except KeyError:
                self._json(404, {"error": "Not found"})
            except (ValueError, OSError, sqlite3.Error) as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self) -> None:
            try:
                workspace, user, rest = self._scope("editor")
                with Store(root / "workspaces" / workspace) as store:
                    if rest == ["bundles"]:
                        result = import_bundle(store, self._body(MAX_BUNDLE))
                        with _metadata(metadata_path) as connection:
                            _audit(connection, workspace, user["name"], "bundle_ingested",
                                   result["root_run"], result)
                        self._json(201, result)
                    elif len(rest) == 3 and rest[0] == "runs" and rest[2] == "comments":
                        run_id = rest[1]
                        body = self._body(MAX_BODY)
                        store.one("runs", run_id)
                        artifact_id = _text(body, "artifact_id", max_length=64)
                        artifact = store.one("artifacts", artifact_id)
                        if artifact["run_id"] != run_id:
                            raise TeamError(400, "Artifact does not belong to this run")
                        comment_id = uuid.uuid4().hex[:12]
                        with _metadata(metadata_path) as connection:
                            connection.execute("INSERT INTO comments VALUES (?,?,?,?,?,?,?)",
                                               (comment_id, workspace, run_id, artifact_id,
                                                user["name"], _text(body, "text"), time.time()))
                            _audit(connection, workspace, user["name"], "comment_added",
                                   run_id, {"comment_id": comment_id, "artifact_id": artifact_id})
                        self._json(201, {"id": comment_id})
                    elif len(rest) == 3 and rest[0] == "runs" and rest[2] == "reviews":
                        if ROLES[user["role"]] < ROLES["reviewer"]:
                            raise TeamError(403, "Workspace access denied")
                        run_id = rest[1]
                        body = self._body(MAX_BODY)
                        store.one("runs", run_id)
                        artifact_id = _text(body, "artifact_id", max_length=64)
                        artifact = store.one("artifacts", artifact_id)
                        if artifact["run_id"] != run_id:
                            raise TeamError(400, "Artifact does not belong to this run")
                        decision = body.get("decision")
                        if decision not in {"approved", "changes_requested"}:
                            raise TeamError(400, "decision must be approved or changes_requested")
                        review_id = uuid.uuid4().hex[:12]
                        with _metadata(metadata_path) as connection:
                            connection.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?)",
                                               (review_id, workspace, run_id, artifact_id,
                                                user["name"], decision, _text(body, "note"), time.time()))
                            _audit(connection, workspace, user["name"], "review_" + decision,
                                   run_id, {"review_id": review_id, "artifact_id": artifact_id})
                        self._json(201, {"id": review_id, "decision": decision})
                    elif len(rest) == 3 and rest[0] == "runs" and rest[2] == "corrections":
                        run_id = rest[1]
                        body = self._body(MAX_BODY)
                        store.one("runs", run_id)
                        snapshot_id = _text(body, "snapshot_id", max_length=64)
                        snapshot = store.one("snapshots", snapshot_id)
                        if snapshot["run_id"] != run_id:
                            raise TeamError(400, "Snapshot does not belong to this run")
                        name = _text(body, "name", max_length=80)
                        correction = body.get("correction")
                        if not isinstance(correction, dict) or not correction:
                            raise TeamError(400, "correction must be a nonempty object")
                        store.branch(snapshot_id, name, correction)
                        with _metadata(metadata_path) as connection:
                            _audit(connection, workspace, user["name"], "correction_proposed",
                                   run_id, {"branch": name, "snapshot_id": snapshot_id})
                        self._json(201, {"branch": name, "source_snapshot": snapshot_id})
                    else:
                        raise TeamError(404, "Not found")
            except TeamError as exc:
                self._json(exc.status, {"error": str(exc)})
            except KeyError:
                self._json(404, {"error": "Not found"})
            except sqlite3.IntegrityError as exc:
                self._json(409, {"error": str(exc)})
            except (ValueError, OSError, sqlite3.Error) as exc:
                self._json(400, {"error": str(exc)})

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    if cert and key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert), str(key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


def serve_team(root: str | Path, config: str | Path, *, host: str = "127.0.0.1",
               port: int = 8780, cert: str | Path | None = None,
               key: str | Path | None = None) -> None:
    server = create_team_server(root, config, host=host, port=port, cert=cert, key=key)
    scheme = "https" if cert else "http"
    print(f"Mangekyo team server: {scheme}://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
