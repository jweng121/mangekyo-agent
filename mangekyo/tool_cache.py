"""Opt-in cache for deterministic parsing of already-read local file bytes."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse(source: bytes, parser: str) -> Any:
    decoded = source.decode("utf-8")
    if parser == "json":
        return json.loads(decoded)
    if parser == "csv":
        return list(csv.DictReader(io.StringIO(decoded)))
    raise ValueError("Only JSON and CSV read parsers are cache eligible")


class ParsedReadCache:
    """Cache only JSON/CSV parses; callers still read bytes to verify freshness."""

    def __init__(self, directory: str | Path):
        if os.environ.get("MANGEKYO_REDACT", "").strip():
            raise ValueError("Parsed read caching is disabled when MANGEKYO_REDACT is configured")
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "parsed_reads.sqlite3", timeout=30)
        self.db.execute("""CREATE TABLE IF NOT EXISTS parsed_reads (
            identity TEXT PRIMARY KEY, source_digest TEXT NOT NULL,
            result_json TEXT NOT NULL, result_digest TEXT NOT NULL,
            expires_at REAL NOT NULL
        )""")

    def __enter__(self) -> "ParsedReadCache":
        return self

    def __exit__(self, *_args: object) -> None:
        self.db.close()

    def parse(self, *, workspace: str | Path, relative_path: str, source: bytes,
              parser: str, tool_version: str, context: dict[str, Any] | None = None,
              ttl_seconds: float = 3600) -> tuple[Any, str]:
        if parser not in {"json", "csv"}:
            raise ValueError("Only JSON and CSV read parsers are cache eligible")
        if not isinstance(tool_version, str) or not tool_version:
            raise ValueError("tool_version must be a nonempty string")
        if not math.isfinite(ttl_seconds) or ttl_seconds < 0:
            raise ValueError("ttl_seconds must be finite and nonnegative")
        scope = str(Path(workspace).resolve())
        name = Path(relative_path)
        if name.is_absolute() or name.drive or ".." in name.parts:
            raise ValueError("Cache input path must be workspace relative")
        identity_data = {"workspace": scope, "tool": "parsed_read",
                         "tool_version": tool_version, "inputs": {
                             "path": name.as_posix(), "parser": parser},
                         "context": context or {}}
        identity = _digest(json.dumps(identity_data, sort_keys=True,
                                      separators=(",", ":"), ensure_ascii=False).encode())
        source_digest = _digest(source)
        now = time.time()
        row = self.db.execute("SELECT source_digest,result_json,result_digest,expires_at "
                              "FROM parsed_reads WHERE identity=?", (identity,)).fetchone()
        reason = "miss"
        if row:
            if row[0] != source_digest:
                reason = "source_changed"
            elif row[3] <= now:
                reason = "expired"
            elif _digest(row[1].encode()) != row[2]:
                reason = "damaged"
            else:
                return json.loads(row[1]), "hit"
        result = _parse(source, parser)
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.db:
            self.db.execute("INSERT INTO parsed_reads VALUES (?,?,?,?,?) "
                            "ON CONFLICT(identity) DO UPDATE SET "
                            "source_digest=excluded.source_digest,result_json=excluded.result_json,"
                            "result_digest=excluded.result_digest,expires_at=excluded.expires_at",
                            (identity, source_digest, encoded, _digest(encoded.encode()),
                             now + ttl_seconds))
        return result, reason
