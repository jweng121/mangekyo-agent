"""Recovery must claim a branch and reconcile uncertain external state first."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mangekyo.demo import resume, run_demo
from mangekyo.store import Store
from conftest import execute_invoice_run


def _branch(store: Store, snapshot_id: str, name: str = "corrected") -> None:
    store.branch(snapshot_id, name, {"replacement": "safe"})


def test_interrupted_before_action_can_resume_from_unchanged_simulation(tmp_path):
    with Store(tmp_path / "history") as store:
        original = run_demo(store)
        target = Path(original["target"])
        target.write_text("original", encoding="utf-8")
        with store.db:
            store.db.execute("DELETE FROM actions WHERE run_id=?", (original["run_id"],))
        store.status(original["run_id"], "interrupted")
        _branch(store, original["snapshot_id"])
        result = resume(store, "corrected")
        assert target.read_text(encoding="utf-8") == "original"
        assert Path(result["target"]).read_text(encoding="utf-8") == "safe"
        assert store.one("runs", result["run_id"])["status"] == "completed"


@pytest.mark.parametrize("state", ["intent", "failed"])
def test_interrupted_during_action_requires_reconciliation(tmp_path, state):
    with Store(tmp_path / "history") as store:
        original = run_demo(store)
        store.action(original["run_id"], "write-target", state)
        store.status(original["run_id"], "interrupted")
        _branch(store, original["snapshot_id"])
        before = len(store.runs())
        with pytest.raises(ValueError, match="unresolved action write-target"):
            resume(store, "corrected")
        assert len(store.runs()) == before
        assert store.one("branches", "corrected")["result_run"] is None


def test_completed_action_after_checkpoint_is_restored_in_disposable_simulation(tmp_path):
    with Store(tmp_path / "history") as store:
        original = run_demo(store)
        _branch(store, original["snapshot_id"])
        result = resume(store, "corrected")
        assert result["duplicate_actions"] == 0
        assert Path(original["target"]).read_text(encoding="utf-8") == "unsafe"
        assert Path(result["target"]).read_text(encoding="utf-8") == "safe"


def test_changed_target_blocks_resume_before_branch_claim(tmp_path):
    with Store(tmp_path / "history") as store:
        original = run_demo(store)
        Path(original["target"]).write_text("changed externally", encoding="utf-8")
        _branch(store, original["snapshot_id"])
        with pytest.raises(ValueError, match="target changed since the recorded action"):
            resume(store, "corrected")
        assert store.one("branches", "corrected")["result_run"] is None


def test_independent_branches_do_not_overwrite_original_environment(tmp_path):
    with Store(tmp_path / "history") as store:
        original = run_demo(store)
        _branch(store, original["snapshot_id"], "first")
        _branch(store, original["snapshot_id"], "second")
        first = resume(store, "first")
        second = resume(store, "second")
        assert first["target"] != second["target"]
        assert Path(first["target"]).read_text(encoding="utf-8") == "safe"
        assert Path(second["target"]).read_text(encoding="utf-8") == "safe"
        assert Path(original["target"]).read_text(encoding="utf-8") == "unsafe"


def test_concurrent_branch_claim_creates_only_one_child(tmp_path):
    home = tmp_path / "history"
    with Store(home) as store:
        parent = store.create_run("agent", "task")
        snapshot = store.snapshot(parent, "checkpoint", {"state": 1})
        _branch(store, snapshot)

    def claim():
        with Store(home) as store:
            return store.claim_branch("corrected", "agent", "recovery", parent_run=parent,
                                      adapter="test", adapter_version="1")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim) for _ in range(2)]
        results = [future.result() for future in futures if future.exception() is None]
        failures = [future.exception() for future in futures if future.exception() is not None]
    assert len(failures) == 1 and isinstance(failures[0], ValueError)
    with Store(home) as store:
        assert len(results) == 1
        assert store.one("branches", "corrected")["result_run"] == results[0]
        assert len(store.runs()) == 2


def test_active_langgraph_source_cannot_be_resumed(langgraph_api):
    client, home = langgraph_api
    parent, _ = execute_invoice_run(client)
    detail = client.get(f"/api/v1/runs/{parent}")[1]
    checkpoint = next(item for item in detail["snapshots"] if item["name"] == "after-read")
    branch = client.post(f"/api/v1/runs/{parent}/branches", {
        "snapshot_id": checkpoint["id"], "name": "active-source",
        "correction": {"supplier_account": "SAFE-ACCOUNT"},
    })[1]
    with Store(home) as store:
        store.status(parent, "running")
    status, error = client.post(f"/api/v1/branches/{branch['branch_id']}/resume", {})
    assert status == 409
    assert "still active" in error["error"]
    with Store(home) as store:
        assert store.one("branches", branch["branch_id"])["result_run"] is None
