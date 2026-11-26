"""Portable run bundles retain history and reject damaged content."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import sys

import pytest

from mangekyo.bundle import export_bundle, import_bundle
from mangekyo.demo import benchmark, resume, run_demo
from mangekyo.store import Store


def test_run_family_bundle_roundtrip_preserves_events_and_evidence(tmp_path):
    with Store(tmp_path / "source") as source:
        demo = run_demo(source)
        source.branch(demo["snapshot_id"], "fixed", {"replacement": "safe"})
        corrected = resume(source, "fixed")
        benchmark(source, demo["run_id"], create_baseline=True)
        bundle = export_bundle(source, corrected["run_id"])
        original_events = source.events(demo["run_id"])
        artifacts = source.artifacts(demo["run_id"])
        assert len(bundle["records"]["runs"]) == 3
        assert bundle["root_run"] == demo["run_id"]

    with Store(tmp_path / "destination") as destination:
        imported = import_bundle(destination, bundle)
        assert imported["runs"] == 3
        assert imported["records_added"] > 0
        assert destination.events(demo["run_id"]) == original_events
        assert destination.one("branches", "fixed")["result_run"] == corrected["run_id"]
        assert destination.artifacts(demo["run_id"]) == artifacts
        for artifact in artifacts:
            assert destination.get_blob(artifact["blob_hash"])
            assert destination.annotations(artifact["id"])
        assert import_bundle(destination, bundle)["records_added"] == 0


def test_bundle_rejects_tampered_object_before_import(tmp_path):
    with Store(tmp_path / "source") as source:
        run = run_demo(source)
        bundle = export_bundle(source, run["run_id"])
    tampered = copy.deepcopy(bundle)
    digest = next(iter(tampered["objects"]))
    tampered["objects"][digest] = base64.b64encode(b"{}").decode()
    payload = {key: value for key, value in tampered.items() if key != "sha256"}
    tampered["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    with Store(tmp_path / "destination") as destination:
        with pytest.raises(ValueError, match="content hash"):
            import_bundle(destination, tampered)
        assert destination.runs() == []


def test_cli_bundle_export_import(tmp_path):
    source_home = tmp_path / "source"
    destination_home = tmp_path / "destination"
    with Store(source_home) as source:
        run = run_demo(source)
    bundle_file = tmp_path / "run.json"
    export = subprocess.run([
        sys.executable, "-m", "mangekyo", "--home", str(source_home),
        "bundle", "export", run["run_id"], str(bundle_file),
    ], capture_output=True, text=True, check=True)
    assert json.loads(export.stdout)["root_run"] == run["run_id"]
    imported = subprocess.run([
        sys.executable, "-m", "mangekyo", "--home", str(destination_home),
        "bundle", "import", str(bundle_file),
    ], capture_output=True, text=True, check=True)
    assert json.loads(imported.stdout)["runs"] == 1
    with Store(destination_home) as destination:
        assert destination.one("runs", run["run_id"])["status"] == "failed"


def test_bundle_rejects_external_references(tmp_path):
    with Store(tmp_path / "source") as source:
        run = run_demo(source)
        bundle = export_bundle(source, run["run_id"])
    bundle["records"]["artifacts"][0]["run_id"] = "another-workspace-run"
    payload = {key: value for key, value in bundle.items() if key != "sha256"}
    bundle["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    with Store(tmp_path / "destination") as destination:
        with pytest.raises(ValueError, match="external artifact reference"):
            import_bundle(destination, bundle)
        assert destination.runs() == []


def test_bundle_rejects_cross_run_evidence_link(tmp_path):
    with Store(tmp_path / "source") as source:
        demo = run_demo(source)
        source.branch(demo["snapshot_id"], "fixed", {"replacement": "safe"})
        corrected = resume(source, "fixed")
        bundle = export_bundle(source, corrected["run_id"])
    tampered = copy.deepcopy(bundle)
    tampered["records"]["artifacts"][0]["event_id"] = next(
        row["id"] for row in tampered["records"]["events"]
        if row["run_id"] == corrected["run_id"])
    payload = {key: value for key, value in tampered.items() if key != "sha256"}
    tampered["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    with Store(tmp_path / "destination") as destination:
        with pytest.raises(ValueError, match="another run's event"):
            import_bundle(destination, tampered)
        assert destination.runs() == []


def test_bundle_rejects_nonscalar_metadata_before_writing(tmp_path):
    with Store(tmp_path / "source") as source:
        demo = run_demo(source)
        bundle = export_bundle(source, demo["run_id"])
    bundle["records"]["runs"][0]["parent_run"] = ["other-run"]
    payload = {key: value for key, value in bundle.items() if key != "sha256"}
    bundle["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    with Store(tmp_path / "destination") as destination:
        with pytest.raises(ValueError, match="invalid runs.parent_run"):
            import_bundle(destination, bundle)
        assert destination.runs() == []
        assert destination.stats()["objects"] == 0
