"""Capture a local browser page and the exact target used for a decision."""

from __future__ import annotations

import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mangekyo.evidence import capture_url
from mangekyo.store import Store


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=root / ".mangekyo-browser-demo")
    args = parser.parse_args()
    handler = functools.partial(QuietHandler, directory=str(root / "examples" / "browser-target"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with Store(args.home.resolve()) as store:
            run_id = store.create_run("browser-example", "Inspect invoice approval target")
            decision = store.event(run_id, "decision", {"next_step": "inspect approval button"})
            url = f"http://127.0.0.1:{server.server_port}/index.html"
            artifact_id = capture_url(store, run_id, url, event_id=decision,
                                      selector="#approve-invoice")
            store.status(run_id, "completed")
        print(json.dumps({"run_id": run_id, "decision_event": decision,
                          "screenshot_artifact": artifact_id,
                          "dashboard": f"python -m mangekyo --home \"{args.home.resolve()}\" dashboard"},
                         indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
