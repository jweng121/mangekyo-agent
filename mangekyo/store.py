"""Crash-safe local metadata and immutable content-addressed objects."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3


def default_path() -> Path:
    return Path(os.environ.get("MANGEKYO_HOME", ".mangekyo")).expanduser().resolve()


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser().resolve() if path else default_path()
        self.objects = self.path / "objects"
        self.blobs = self.path / "blobs"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path / "history.sqlite3", timeout=20)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self._schema()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _schema(self) -> None:
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, agent TEXT NOT NULL, label TEXT NOT NULL,
                    status TEXT NOT NULL, created REAL NOT NULL, parent_run TEXT,
                    adapter TEXT NOT NULL, adapter_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    seq INTEGER NOT NULL, kind TEXT NOT NULL, created REAL NOT NULL,
                    payload_hash TEXT NOT NULL, snapshot_id TEXT,
                    UNIQUE(run_id, seq)
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    parent_id TEXT, name TEXT NOT NULL, created REAL NOT NULL,
                    manifest_hash TEXT NOT NULL, adapter TEXT NOT NULL,
                    adapter_version TEXT NOT NULL, env_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS branches (
                    name TEXT PRIMARY KEY, source_snapshot TEXT NOT NULL REFERENCES snapshots(id),
                    correction_hash TEXT NOT NULL, created REAL NOT NULL, result_run TEXT
                );
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    action_key TEXT NOT NULL, state TEXT NOT NULL, result_hash TEXT,
                    created REAL NOT NULL, UNIQUE(run_id, action_key)
                );
                CREATE INDEX IF NOT EXISTS events_run_seq ON events(run_id, seq);
                CREATE INDEX IF NOT EXISTS snapshots_run ON snapshots(run_id);
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    event_id TEXT REFERENCES events(id), name TEXT NOT NULL, mime TEXT NOT NULL,
                    blob_hash TEXT NOT NULL, parsed_hash TEXT, source TEXT,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS annotations (
                    id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(id),
                    page INTEGER NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
                    width REAL NOT NULL, height REAL NOT NULL, note TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts(run_id);
                CREATE INDEX IF NOT EXISTS annotations_artifact ON annotations(artifact_id);
            """)
            row = self.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            version = int(row[0]) if row else 1
            if version < 1 or version > SCHEMA_VERSION:
                raise RuntimeError(f"Unsupported storage schema {version}; supported through {SCHEMA_VERSION}")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', '1')")
            if version == 1:
                self.db.execute("CREATE INDEX IF NOT EXISTS branches_source ON branches(source_snapshot)")
                self.db.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
                version = 2
            if version == 2:
                self.db.execute("UPDATE meta SET value='3' WHERE key='schema_version'")

    def _redact(self, value: Any) -> Any:
        secrets = [s for s in os.environ.get("MANGEKYO_REDACT", "").split(",") if s]
        def walk(item: Any) -> Any:
            if isinstance(item, str):
                for secret in secrets:
                    item = item.replace(secret, "[REDACTED]")
                return item
            if isinstance(item, dict):
                return {walk(str(k)): walk(v) for k, v in item.items()}
            if isinstance(item, (list, tuple)):
                return [walk(v) for v in item]
            return item
        return walk(value)

    def put(self, value: Any) -> str:
        raw = json.dumps(self._redact(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        target = self.objects / digest[:2] / digest
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".pending-")
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return digest

    def get(self, digest: str) -> Any:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid object hash")
        raw = (self.objects / digest[:2] / digest).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"Damaged object: {digest}")
        return json.loads(raw)

    def put_blob(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        target = self.blobs / digest[:2] / digest
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".pending-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        return digest

    def get_blob(self, digest: str) -> bytes:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid blob hash")
        data = (self.blobs / digest[:2] / digest).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"Damaged artifact: {digest}")
        return data

    def artifact(self, run_id: str, name: str, data: bytes, mime: str, *,
                 event_id: str | None = None, parsed_text: str | None = None,
                 source: str | None = None) -> str:
        self.one("runs", run_id)
        if event_id and self.one("events", event_id)["run_id"] != run_id:
            raise ValueError("Artifact event belongs to another run")
        if mime not in {"application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError("Supported evidence: PDF, PNG, JPEG, WebP, GIF")
        if len(data) > 50_000_000:
            raise ValueError("Evidence file exceeds 50 MB")
        signatures = {"application/pdf": data.startswith(b"%PDF-"),
                      "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
                      "image/jpeg": data.startswith(b"\xff\xd8\xff"),
                      "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
                      "image/gif": data.startswith((b"GIF87a", b"GIF89a"))}
        if not signatures[mime]:
            raise ValueError("Evidence content does not match its file type")
        blob_hash = self.put_blob(data)
        parsed_hash = self.put({"text": parsed_text}) if parsed_text is not None else None
        artifact_id = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?)",
                            (artifact_id, run_id, event_id, self._redact(name), mime,
                             blob_hash, parsed_hash, self._redact(source), time.time()))
        self.event(run_id, "artifact", {"artifact_id": artifact_id, "name": name,
                                        "mime": mime, "source_event": event_id})
        return artifact_id

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM artifacts WHERE run_id=? ORDER BY created", (run_id,))]

    def annotations(self, artifact_id: str) -> list[dict[str, Any]]:
        self.one("artifacts", artifact_id)
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM annotations WHERE artifact_id=? ORDER BY created", (artifact_id,))]

    def annotate(self, artifact_id: str, page: int, x: float, y: float,
                 width: float, height: float, note: str) -> str:
        self.one("artifacts", artifact_id)
        if page < 0 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in (x, y, width, height)):
            raise ValueError("Annotation coordinates must be normalized to 0..1")
        if width <= 0 or height <= 0 or x + width > 1.001 or y + height > 1.001:
            raise ValueError("Annotation rectangle is outside the page")
        if not note.strip() or len(note) > 2000:
            raise ValueError("Annotation note must be 1-2000 characters")
        ident = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute("INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?,?)",
                            (ident, artifact_id, page, x, y, width, height,
                             self._redact(note.strip()), time.time()))
        return ident

    def create_run(self, agent: str, label: str, *, parent_run: str | None = None,
                   adapter: str = "record-only", adapter_version: str = "1") -> str:
        run_id = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
                            (run_id, self._redact(agent), self._redact(label), "running", time.time(), parent_run, adapter, adapter_version))
        return run_id

    def status(self, run_id: str, status: str) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))

    def event(self, run_id: str, kind: str, payload: Any, snapshot_id: str | None = None) -> str:
        digest = self.put(payload)
        event_id = uuid.uuid4().hex[:12]
        with self.db:
            seq = self.db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE run_id=?", (run_id,)).fetchone()[0]
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                            (event_id, run_id, seq, self._redact(kind), time.time(), digest, snapshot_id))
        return event_id

    def snapshot(self, run_id: str, name: str, context: dict[str, Any], *,
                 parent_id: str | None = None, adapter: str = "record-only",
                 adapter_version: str = "1", environment: Any | None = None) -> str:
        manifest = {k: self.put(v) for k, v in context.items()}
        digest = self.put(manifest)
        env_hash = self.put(environment) if environment is not None else None
        snap_id = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?)",
                            (snap_id, run_id, parent_id, self._redact(name), time.time(), digest,
                             adapter, adapter_version, env_hash))
        self.event(run_id, "checkpoint", {"name": name, "snapshot_id": snap_id}, snap_id)
        return snap_id

    def context(self, snap_id: str) -> dict[str, Any]:
        row = self.one("snapshots", snap_id)
        return {k: self.get(v) for k, v in self.get(row["manifest_hash"]).items()}

    def one(self, table: str, key: str) -> dict[str, Any]:
        if table not in {"runs", "events", "snapshots", "branches", "actions", "artifacts", "annotations"}:
            raise ValueError("Invalid table")
        col = "name" if table == "branches" else "id"
        row = self.db.execute(f"SELECT * FROM {table} WHERE {col}=?", (key,)).fetchone()
        if not row:
            raise KeyError(f"No {table[:-1]} found: {key}")
        return dict(row)

    def runs(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM runs ORDER BY created DESC")]

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(r) | {"payload": self.get(r["payload_hash"])} for r in self.db.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY seq", (run_id,))]

    def snapshots(self, run_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM snapshots WHERE run_id=? ORDER BY created", (run_id,))]

    def branches(self) -> list[dict[str, Any]]:
        return [dict(r) | {"correction": self.get(r["correction_hash"])} for r in self.db.execute(
            "SELECT * FROM branches ORDER BY created DESC")]

    def branch(self, snap_id: str, name: str, correction: dict[str, Any]) -> None:
        self.one("snapshots", snap_id)
        digest = self.put(correction)
        with self.db:
            self.db.execute("INSERT INTO branches VALUES (?,?,?,?,NULL)", (name, snap_id, digest, time.time()))

    def action(self, run_id: str, key: str, state: str, result: Any | None = None) -> None:
        digest = self.put(result) if result is not None else None
        with self.db:
            self.db.execute("INSERT INTO actions VALUES (?,?,?,?,?,?) ON CONFLICT(run_id, action_key) "
                            "DO UPDATE SET state=excluded.state,result_hash=excluded.result_hash",
                            (uuid.uuid4().hex[:12], run_id, key, state, digest, time.time()))

    def stats(self) -> dict[str, Any]:
        objects = [p for p in self.objects.glob("*/*") if p.is_file() and re.fullmatch(r"[0-9a-f]{64}", p.name)]
        return {"objects": len(objects), "object_bytes": sum(p.stat().st_size for p in objects),
                "artifact_bytes": sum(p.stat().st_size for p in self.blobs.glob("*/*") if p.is_file()),
                "runs": len(self.runs()), "branches": len(self.branches())}


class RunRecorder:
    """Small framework-neutral synchronous and asynchronous instrumentation surface."""

    def __init__(self, store: Store, agent: str, label: str):
        self.store = store
        self.run_id = store.create_run(agent, label)
        self.last_snapshot: str | None = None

    def __enter__(self) -> "RunRecorder":
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 _tb: object) -> None:
        if exc is not None:
            self.record("error", message=str(exc), error_type=type(exc).__name__)
        self.finish("failed" if exc_type else "completed")

    async def __aenter__(self) -> "RunRecorder":
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                        tb: object) -> None:
        self.__exit__(exc_type, exc, tb)

    def record(self, kind: str, **payload: Any) -> str:
        return self.store.event(self.run_id, kind, payload, self.last_snapshot)

    async def arecord(self, kind: str, **payload: Any) -> str:
        return self.record(kind, **payload)

    def checkpoint(self, name: str, **context: Any) -> str:
        self.last_snapshot = self.store.snapshot(self.run_id, name, context, parent_id=self.last_snapshot)
        return self.last_snapshot

    def artifact(self, path: str | Path, *, parsed_text: str | None = None) -> str:
        from .evidence import add_file
        return add_file(self.store, self.run_id, Path(path), parsed_text=parsed_text)

    async def acheckpoint(self, name: str, **context: Any) -> str:
        return self.checkpoint(name, **context)

    def finish(self, status: str = "completed") -> None:
        self.store.status(self.run_id, status)
