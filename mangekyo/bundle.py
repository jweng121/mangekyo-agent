"""Portable, hash-verified local run history for later team ingestion."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
from typing import Any

from .store import Store


TABLES = {
    "runs": ("id", "agent", "label", "status", "created", "parent_run", "adapter", "adapter_version"),
    "snapshots": ("id", "run_id", "parent_id", "name", "created", "manifest_hash",
                  "adapter", "adapter_version", "env_hash"),
    "events": ("id", "run_id", "seq", "kind", "created", "payload_hash", "snapshot_id"),
    "branches": ("name", "source_snapshot", "correction_hash", "created", "result_run"),
    "actions": ("id", "run_id", "action_key", "state", "result_hash", "created"),
    "artifacts": ("id", "run_id", "event_id", "name", "mime", "blob_hash",
                  "parsed_hash", "source", "created"),
    "annotations": ("id", "artifact_id", "page", "x", "y", "width", "height",
                    "note", "created"),
}
NULLABLE = {
    "runs": {"parent_run"},
    "snapshots": {"parent_id", "env_hash"},
    "events": {"snapshot_id"},
    "branches": {"result_run"},
    "actions": {"result_hash"},
    "artifacts": {"event_id", "parsed_hash", "source"},
    "annotations": set(),
}
INTEGER_COLUMNS = {"seq", "page"}
NUMBER_COLUMNS = {"created", "x", "y", "width", "height"}


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _family(store: Store, run_id: str) -> tuple[str, set[str]]:
    current = store.one("runs", run_id)
    while current["parent_run"]:
        current = store.one("runs", current["parent_run"])
    root_id = current["id"]
    selected = {root_id}
    all_runs = store.runs()
    while True:
        descendants = {run["id"] for run in all_runs if run["parent_run"] in selected}
        if descendants <= selected:
            return root_id, selected
        selected |= descendants


def export_bundle(store: Store, run_id: str) -> dict[str, Any]:
    """Export the root run, descendants, branches, evidence, and referenced bytes."""
    root_id, selected = _family(store, run_id)
    records: dict[str, list[dict]] = {}
    records["runs"] = [run for run in store.runs() if run["id"] in selected]
    for table in ("snapshots", "events", "actions", "artifacts"):
        records[table] = [dict(row) for row in store.db.execute(f"SELECT * FROM {table}")
                          if row["run_id"] in selected]
    snapshots = {row["id"] for row in records["snapshots"]}
    records["branches"] = [dict(row) for row in store.db.execute("SELECT * FROM branches")
                           if row["source_snapshot"] in snapshots]
    artifacts = {row["id"] for row in records["artifacts"]}
    records["annotations"] = [dict(row) for row in store.db.execute("SELECT * FROM annotations")
                              if row["artifact_id"] in artifacts]

    objects = {row["payload_hash"] for row in records["events"]}
    objects.update(row["manifest_hash"] for row in records["snapshots"])
    objects.update(row["env_hash"] for row in records["snapshots"] if row["env_hash"])
    objects.update(row["correction_hash"] for row in records["branches"])
    objects.update(row["result_hash"] for row in records["actions"] if row["result_hash"])
    objects.update(row["parsed_hash"] for row in records["artifacts"] if row["parsed_hash"])
    for snapshot in records["snapshots"]:
        objects.update(store.get(snapshot["manifest_hash"]).values())
    encoded_objects = {digest: base64.b64encode(
        (store.objects / digest[:2] / digest).read_bytes()).decode("ascii")
        for digest in sorted(objects)}
    for digest, value in encoded_objects.items():
        if _digest(base64.b64decode(value)) != digest:
            raise ValueError(f"Damaged source object: {digest}")
    blobs = {row["blob_hash"] for row in records["artifacts"]}
    encoded_blobs = {digest: base64.b64encode(store.get_blob(digest)).decode("ascii")
                     for digest in sorted(blobs)}
    payload = {"format": "mangekyo-run-bundle", "version": 1,
               "root_run": root_id, "records": records,
               "objects": encoded_objects, "blobs": encoded_blobs}
    return {**payload, "sha256": _digest(_encoded(payload))}


def import_bundle(store: Store, bundle: dict[str, Any]) -> dict[str, Any]:
    """Verify a bundle and import it without rewriting its local event format."""
    if os.environ.get("MANGEKYO_REDACT", ""):
        raise ValueError("Import is disabled when MANGEKYO_REDACT is configured; redact at capture")
    if (not isinstance(bundle, dict) or bundle.get("format") != "mangekyo-run-bundle"
            or type(bundle.get("version")) is not int or bundle["version"] != 1):
        raise ValueError("Unsupported run bundle")
    payload = {key: value for key, value in bundle.items() if key != "sha256"}
    if _digest(_encoded(payload)) != bundle.get("sha256"):
        raise ValueError("Run bundle checksum does not match")
    records = bundle.get("records")
    if not isinstance(records, dict) or set(records) != set(TABLES):
        raise ValueError("Run bundle has invalid tables")
    for table, columns in TABLES.items():
        if not isinstance(records[table], list) or any(
            not isinstance(row, dict) or set(row) != set(columns) for row in records[table]
        ):
            raise ValueError(f"Run bundle has invalid {table} rows")
        for row in records[table]:
            for column, value in row.items():
                if value is None and column in NULLABLE[table]:
                    continue
                if column in INTEGER_COLUMNS:
                    valid = type(value) is int and value >= 0
                elif column in NUMBER_COLUMNS:
                    valid = type(value) in {int, float} and -1e18 <= value <= 1e18 and math.isfinite(value)
                else:
                    valid = isinstance(value, str) and (bool(value) or column in NULLABLE[table])
                if not valid:
                    raise ValueError(f"Run bundle has invalid {table}.{column}")
    root_id = bundle.get("root_run")
    if not isinstance(root_id, str):
        raise ValueError("Run bundle root is invalid")
    for table, rows in records.items():
        key = "name" if table == "branches" else "id"
        keys = [row[key] for row in rows]
        if any(not isinstance(value, str) or not value for value in keys) or len(set(keys)) != len(keys):
            raise ValueError(f"Run bundle has invalid or duplicate {table} identifiers")
    run_ids = {row["id"] for row in records["runs"]}
    snapshot_ids = {row["id"] for row in records["snapshots"]}
    event_ids = {row["id"] for row in records["events"]}
    artifact_ids = {row["id"] for row in records["artifacts"]}
    if root_id not in run_ids:
        raise ValueError("Run bundle root is missing")
    run_by_id = {row["id"]: row for row in records["runs"]}
    snapshot_by_id = {row["id"]: row for row in records["snapshots"]}
    event_by_id = {row["id"]: row for row in records["events"]}
    if run_by_id[root_id]["parent_run"] is not None:
        raise ValueError("Run bundle root has a parent")
    if any(row["parent_run"] and row["parent_run"] not in run_ids for row in records["runs"]):
        raise ValueError("Run bundle has an external parent run")
    for run_id in run_ids:
        seen = set()
        current = run_id
        while current != root_id:
            if current in seen or not run_by_id[current]["parent_run"]:
                raise ValueError("Run bundle has an unrelated or cyclic run")
            seen.add(current)
            current = run_by_id[current]["parent_run"]
    if any(row["run_id"] not in run_ids or
           (row["parent_id"] and row["parent_id"] not in snapshot_ids)
           for row in records["snapshots"]):
        raise ValueError("Run bundle has an external snapshot reference")
    if any(row["run_id"] not in run_ids or
           (row["snapshot_id"] and row["snapshot_id"] not in snapshot_ids)
           for row in records["events"]):
        raise ValueError("Run bundle has an external event reference")
    if any(row["snapshot_id"] and snapshot_by_id[row["snapshot_id"]]["run_id"] != row["run_id"]
           for row in records["events"]):
        raise ValueError("Run bundle event references another run's snapshot")
    if any(row["source_snapshot"] not in snapshot_ids or
           (row["result_run"] and row["result_run"] not in run_ids)
           for row in records["branches"]):
        raise ValueError("Run bundle has an external branch reference")
    if any(row["run_id"] not in run_ids for row in records["actions"]):
        raise ValueError("Run bundle has an external action reference")
    if any(row["run_id"] not in run_ids or
           (row["event_id"] and row["event_id"] not in event_ids)
           for row in records["artifacts"]):
        raise ValueError("Run bundle has an external artifact reference")
    if any(row["event_id"] and event_by_id[row["event_id"]]["run_id"] != row["run_id"]
           for row in records["artifacts"]):
        raise ValueError("Run bundle artifact references another run's event")
    if any(row["artifact_id"] not in artifact_ids for row in records["annotations"]):
        raise ValueError("Run bundle has an external annotation reference")
    objects = bundle.get("objects")
    blobs = bundle.get("blobs")
    if not isinstance(objects, dict) or not isinstance(blobs, dict):
        raise ValueError("Run bundle objects or blobs are invalid")
    decoded: dict[str, dict[str, bytes]] = {"objects": {}, "blobs": {}}
    for name, values in (("objects", objects), ("blobs", blobs)):
        for digest, value in values.items():
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Run bundle contains an invalid content hash")
            try:
                raw = base64.b64decode(value, validate=True)
            except (TypeError, ValueError, binascii.Error) as exc:
                raise ValueError("Run bundle contains invalid base64") from exc
            if _digest(raw) != digest:
                raise ValueError(f"Run bundle content hash does not match: {digest}")
            if name == "objects":
                json.loads(raw)
            decoded[name][digest] = raw

    required = {row["payload_hash"] for row in records["events"]}
    required.update(row["manifest_hash"] for row in records["snapshots"])
    required.update(row["env_hash"] for row in records["snapshots"] if row["env_hash"])
    required.update(row["correction_hash"] for row in records["branches"])
    required.update(row["result_hash"] for row in records["actions"] if row["result_hash"])
    required.update(row["parsed_hash"] for row in records["artifacts"] if row["parsed_hash"])
    for snapshot in records["snapshots"]:
        manifest_raw = decoded["objects"].get(snapshot["manifest_hash"])
        if manifest_raw is None:
            raise ValueError("Run bundle is missing a snapshot manifest")
        manifest = json.loads(manifest_raw)
        if not isinstance(manifest, dict):
            raise ValueError("Run bundle snapshot manifest is invalid")
        if not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                   for value in manifest.values()):
            raise ValueError("Run bundle snapshot references invalid objects")
        required.update(manifest.values())
    if required != decoded["objects"].keys():
        raise ValueError("Run bundle objects do not match its references")
    if {row["blob_hash"] for row in records["artifacts"]} != decoded["blobs"].keys():
        raise ValueError("Run bundle evidence blobs do not match its references")

    for digest, raw in decoded["objects"].items():
        target = store.objects / digest[:2] / digest
        if target.exists() and _digest(target.read_bytes()) != digest:
            raise ValueError(f"Destination has damaged content: {digest}")
        if store.put(json.loads(raw)) != digest:
            raise ValueError("Run bundle object changed on import")
    for digest, raw in decoded["blobs"].items():
        target = store.blobs / digest[:2] / digest
        if target.exists() and _digest(target.read_bytes()) != digest:
            raise ValueError(f"Destination has damaged evidence: {digest}")
        if store.put_blob(raw) != digest:
            raise ValueError("Run bundle evidence changed on import")
    imported = 0
    with store.db:
        for table, columns in TABLES.items():
            key = "name" if table == "branches" else "id"
            placeholders = ",".join("?" for _ in columns)
            sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
            for row in records[table]:
                existing = store.db.execute(f"SELECT * FROM {table} WHERE {key}=?", (row[key],)).fetchone()
                if existing:
                    if dict(existing) != row:
                        raise ValueError(f"Conflicting {table} record: {row[key]}")
                    continue
                store.db.execute(sql, tuple(row[column] for column in columns))
                imported += 1
    return {"root_run": root_id, "runs": len(records["runs"]), "records_added": imported}
