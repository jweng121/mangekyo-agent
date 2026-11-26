"""Exercise authenticated team sharing over TLS from separate client processes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from mangekyo.bundle import export_bundle
from mangekyo.demo import run_demo
from mangekyo.store import Store
from mangekyo.team import create_team_server, token_hash


CLIENT = """
import json, os, ssl, sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
url, method, file, cert = sys.argv[1:]
body = open(file, 'rb').read() if file != '-' else None
request = Request(url, data=body, method=method,
                  headers={'Authorization': 'Bearer ' + os.environ['TEAM_TOKEN'],
                           'Content-Type': 'application/json'})
try:
    with urlopen(request, context=ssl.create_default_context(cafile=cert), timeout=10) as response:
        print(json.dumps({'status': response.status, 'body': json.load(response)}))
except HTTPError as exc:
    print(json.dumps({'status': exc.code, 'body': json.load(exc)}))
"""


def main() -> None:
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("OpenSSL is required to create a temporary TLS certificate")
    with tempfile.TemporaryDirectory(prefix="mangekyo-team-tls-") as directory:
        root = Path(directory)
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "1",
                        "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        tokens = {name: name * 32 for name in ("alice", "bob", "carol")}
        config = root / "users.json"
        config.write_text(json.dumps({"users": [
            {"name": name, "workspace": workspace, "role": role,
             "token_sha256": token_hash(tokens[name])}
            for name, workspace, role in (("alice", "shared", "editor"),
                                          ("bob", "shared", "reviewer"),
                                          ("carol", "private", "viewer"))
        ]}), encoding="utf-8")
        with Store(root / "source") as store:
            demo = run_demo(store)
            bundle = export_bundle(store, demo["run_id"])
        bundle_file = root / "bundle.json"
        bundle_file.write_text(json.dumps(bundle), encoding="utf-8")
        comment_file = root / "comment.json"
        review_file = root / "review.json"
        server = create_team_server(root / "team", config, host="0.0.0.0",
                                    port=0, cert=cert, key=key)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"https://127.0.0.1:{server.server_port}/v1/workspaces"

        def client(name: str, method: str, path: str, file: Path | None = None) -> dict:
            result = subprocess.run([sys.executable, "-c", CLIENT, base + path,
                                     method, str(file) if file else "-", str(cert)],
                                    cwd=root, env={**os.environ, "TEAM_TOKEN": tokens[name]},
                                    check=True, capture_output=True, text=True, timeout=20)
            return json.loads(result.stdout)

        try:
            run_path = f"/shared/runs/{demo['run_id']}"
            assert client("alice", "POST", "/shared/bundles", bundle_file)["status"] == 201
            bob = client("bob", "GET", run_path)
            assert bob["status"] == 200 and bob["body"]["run"]["id"] == demo["run_id"]
            assert bob["body"]["artifacts"]
            artifact_id = bob["body"]["artifacts"][0]["id"]
            comment_file.write_text(json.dumps({"artifact_id": artifact_id,
                                                "text": "Check the captured instruction"}),
                                    encoding="utf-8")
            assert client("alice", "POST", run_path + "/comments", comment_file)["status"] == 201
            comments = client("bob", "GET", run_path + "/comments")
            assert comments["status"] == 200
            assert len(comments["body"]["comments"]) == 1
            assert comments["body"]["comments"][0]["author"] == "alice"
            review_file.write_text(json.dumps({"artifact_id": artifact_id,
                                               "decision": "changes_requested",
                                               "note": "Correct the account before resuming"}),
                                   encoding="utf-8")
            assert client("bob", "POST", run_path + "/reviews", review_file)["status"] == 201
            reviews = client("alice", "GET", run_path + "/reviews")
            assert reviews["status"] == 200
            assert reviews["body"]["reviews"][0]["author"] == "bob"
            audit = client("bob", "GET", "/shared/audit")
            assert audit["status"] == 200
            assert {entry["action"] for entry in audit["body"]["audit"]} >= {
                "bundle_ingested", "comment_added", "review_changes_requested"}
            assert client("carol", "GET", run_path)["status"] == 403
            assert client("carol", "GET", "/private/runs")["body"]["runs"] == []
            print("TLS team smoke passed: two clients shared, commented, and reviewed; other workspace denied")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
