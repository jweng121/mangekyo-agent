"""Measure local event ingestion and inspection in a fresh throwaway store."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from mangekyo.capture import capture_report
from mangekyo.store import Store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--events", type=int, default=5000)
    args = parser.parse_args()
    if not 1 <= args.events <= 100000:
        parser.error("--events must be between 1 and 100000")
    home = args.home.expanduser().resolve()
    if home.exists():
        parser.error("--home must be a new path; this probe never reuses a store")
    started = time.perf_counter()
    with Store(home) as store:
        run_id = store.create_run("scale-probe", "Event ingestion probe")
        for index in range(args.events):
            store.event(run_id, "observation", {"index": index, "text": "x" * 300})
        store.status(run_id, "completed")
    written = time.perf_counter()
    with Store(home) as store:
        events = store.events(run_id)
        report = capture_report(store, run_id, events=events)
        stats = store.stats()
        integrity = store.db.execute("PRAGMA integrity_check").fetchone()[0]
    read = time.perf_counter()
    print(json.dumps({"events": len(events), "write_seconds": round(written - started, 3),
                      "read_and_report_seconds": round(read - written, 3),
                      "integrity": integrity, "object_bytes": stats["object_bytes"],
                      "capture_status": report["context"]["status"]}, indent=2))


if __name__ == "__main__":
    main()
