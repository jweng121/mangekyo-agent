"""Two authenticated clients can share a run without crossing workspace boundaries."""

from __future__ import annotations

import json
import hashlib
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from mangekyo.bundle import export_bundle
from mangekyo.demo import run_demo
from mangekyo.store import Store
from mangekyo.team import create_team_server, token_hash


def test_team_sharing_roles_audit_and_isolation(tmp_path):
    tokens = {name: name * 32 for name in ("alice", "bob", "carol")}
    config = tmp_path / "users.json"
    config.write_text(json.dumps({"users": [
        {"name": "alice", "workspace": "shared", "role": "editor",
         "token_sha256": token_hash(tokens["alice"])},
        {"name": "bob", "workspace": "shared", "role": "reviewer",
         "token_sha256": token_hash(tokens["bob"])},
        {"name": "carol", "workspace": "private", "role": "admin",
         "token_sha256": token_hash(tokens["carol"])},
    ]}), encoding="utf-8")
    with Store(tmp_path / "source") as source:
        demo = run_demo(source)
        bundle = export_bundle(source, demo["run_id"])
        artifact_id = source.artifacts(demo["run_id"])[0]["id"]

    server = create_team_server(tmp_path / "team", config, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/v1/workspaces"

    def call(name, path, data=None):
        request = Request(base + path,
                          data=json.dumps(data).encode() if data is not None else None,
                          headers={"Authorization": f"Bearer {tokens[name]}",
                                   "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=5) as response:
                body = response.read()
                return response.status, json.loads(body) if "json" in response.headers["Content-Type"] else body
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        run_path = f"/shared/runs/{demo['run_id']}"
        assert call("alice", "/shared/bundles", bundle)[0] == 201
        assert call("alice", run_path)[1]["run"]["id"] == demo["run_id"]
        assert call("bob", run_path)[1]["artifacts"][0]["id"] == artifact_id
        detail_path = run_path + f"/artifacts/{artifact_id}/detail"
        detail = call("bob", detail_path)
        assert detail[0] == 200
        assert detail[1]["artifact"]["id"] == artifact_id
        assert detail[1]["parsed_text"]
        assert detail[1]["annotations"]
        assert call("bob", run_path + f"/artifacts/{artifact_id}")[1].startswith(b"%PDF-")
        assert call("carol", run_path)[0] == 403
        assert call("carol", detail_path)[0] == 403
        assert call("alice", "/private/runs")[0] == 403
        assert call("bob", "/shared/bundles", bundle)[0] == 201
        malformed = json.loads(json.dumps(bundle))
        malformed["records"]["runs"][0]["parent_run"] = ["invalid"]
        payload = {key: value for key, value in malformed.items() if key != "sha256"}
        malformed["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True,
            separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        assert call("alice", "/shared/bundles", malformed)[0] == 400
        assert call("bob", run_path)[0] == 200

        comment = call("alice", run_path + "/comments",
                       {"artifact_id": artifact_id, "text": "Inspect this evidence"})
        assert comment[0] == 201
        assert call("bob", run_path + "/comments")[1]["comments"][0]["id"] == comment[1]["id"]
        assert call("alice", run_path + "/reviews",
                    {"artifact_id": artifact_id, "decision": "approved", "note": "Looks right"})[0] == 403
        assert call("bob", run_path + "/reviews",
                    {"artifact_id": artifact_id, "decision": "approved", "note": "Looks right"})[0] == 201
        assert call("alice", "/shared/audit")[0] == 403
        actions = [item["action"] for item in call("bob", "/shared/audit")[1]["audit"]]
        assert "bundle_ingested" in actions
        assert "comment_added" in actions
        assert "review_approved" in actions
        assert call("alice", run_path + "/corrections",
                    {"snapshot_id": demo["snapshot_id"], "name": "team_fix",
                     "correction": {"replacement": "safe"}})[0] == 201
        assert call("bob", "/shared/audit")[1]["audit"][-1]["action"] == "correction_proposed"
        assert call("carol", "/private/runs")[1]["runs"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_remote_listener_requires_tls(tmp_path):
    config = tmp_path / "users.json"
    config.write_text(json.dumps({"users": [{"name": "alice", "workspace": "shared",
        "role": "admin", "token_sha256": token_hash("a" * 32)}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="TLS"):
        create_team_server(tmp_path / "team", config, host="0.0.0.0", port=0)
