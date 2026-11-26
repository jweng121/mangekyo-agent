from mangekyo.checks import check_run
from mangekyo.commits import commit_branch, read_commit
from mangekyo.demo import resume, run_demo
from mangekyo.diffs import diff_branch
from mangekyo.project import add_project
from mangekyo.push import push_commit
from mangekyo.store import Store
import json
import sys
from pathlib import Path
import pytest


def test_commit_preserves_corrected_snapshot_and_eval(tmp_path, monkeypatch):
    with Store(tmp_path) as store:
        original = run_demo(store)
        store.branch(original["snapshot_id"], "fixed", {"replacement": "safe"})
        corrected = resume(store, "fixed")
        case = {"kind": "tool", "expected": {"input": "safe"}}
        assert check_run(store, original["run_id"], case)["passed"] is False
        check_run(store, corrected["run_id"], case)
        saved = commit_branch(store, "fixed")
        compared = diff_branch(store, original["run_id"], "fixed")
        assert compared["corrected_run"] == corrected["run_id"]
        assert compared["corrected_check"]["passed"] is True
        assert saved["source_snapshot"] == original["snapshot_id"]
        assert saved["corrected_run"] == corrected["run_id"]
        assert saved["corrected_snapshot"] != original["snapshot_id"]
        assert read_commit(store, saved["commit_id"])["regression_case"] == case

        project = tmp_path / "agent-project"
        project.mkdir()
        add_project(project)
        config_path = project / ".mangekyo-agent.json"
        config = json.loads(config_path.read_text())
        fixture = Path(__file__).parent / "model_pipeline_fixture.py"
        config["push"] = {stage: [sys.executable, str(fixture), stage]
                          for stage in ("trainer", "evaluator", "activator")}
        config_path.write_text(json.dumps(config))
        with pytest.raises(ValueError, match="Configure current_model"):
            push_commit(store, saved["commit_id"], project)
        config["current_model"] = {"version": "v1", "artifact": "active-model.json"}
        config_path.write_text(json.dumps(config))
        (project / "active-model.json").write_text('{"version":"v1","mapping":{}}')
        pushed = push_commit(store, saved["commit_id"], project)
        assert pushed["model_version"] == "v2"
        assert json.loads((project / "active-model.json").read_text())["mapping"]["unsafe"] == "safe"
        assert json.loads(config_path.read_text())["current_model"]["version"] == "v2"
        config["current_model"] = {"version": "v1", "artifact": "active-model.json"}
        config_path.write_text(json.dumps(config))
        (project / "active-model.json").write_text('{"version":"v1","mapping":{}}')
        monkeypatch.setenv("MANGEKYO_TEST_EVAL_FAIL", "1")
        with pytest.raises(ValueError, match="held-out evals"):
            push_commit(store, saved["commit_id"], project)
        assert json.loads((project / "active-model.json").read_text())["version"] == "v1"
        assert json.loads(config_path.read_text())["current_model"]["version"] == "v1"
        monkeypatch.delenv("MANGEKYO_TEST_EVAL_FAIL")
        monkeypatch.setenv("MANGEKYO_TEST_UNCHANGED_MODEL", "1")
        with pytest.raises(ValueError, match="unchanged model contents"):
            push_commit(store, saved["commit_id"], project)
        assert json.loads((project / "active-model.json").read_text())["version"] == "v1"
