import os
import io
import json
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mangekyo.demo import benchmark, resume, resume_unavailable_reason, run_demo
from mangekyo.provider import probe_openai_cache
from mangekyo.store import Store


class ReferenceFlowTest(unittest.TestCase):
    def test_failure_branch_restores_and_resumes(self):
        with tempfile.TemporaryDirectory() as root, Store(root) as store:
            demo = run_demo(store)
            target = Path(demo["target"])
            self.assertEqual(target.read_text(), "unsafe")
            with self.assertRaisesRegex(ValueError, "Resume a corrected branch"):
                benchmark(store, demo["run_id"], create_baseline=True)
            self.assertEqual(len(store.runs()), 1)
            store.branch(demo["snapshot_id"], "fixed", {"replacement": "safe"})
            self.assertIsNone(resume_unavailable_reason(store, "fixed"))
            result = resume(store, "fixed")
            self.assertEqual(target.read_text(), "unsafe")
            self.assertEqual(Path(result["target"]).read_text(), "safe")
            self.assertEqual(result["duplicate_actions"], 0)
            self.assertEqual(store.one("runs", result["run_id"])["status"], "completed")
            report = benchmark(store, demo["run_id"], create_baseline=True)
            self.assertEqual(report["recovered"][0]["skipped_steps"], 2)
            self.assertEqual(report["recovered"][0]["provider_cached_tokens"], "not reported")
            self.assertTrue(report["cold_baselines"])
            self.assertEqual(len(benchmark(store, demo["run_id"], create_baseline=True)["cold_baselines"]), 1)
            with self.assertRaises(ValueError):
                resume(store, "fixed")
            self.assertIn("Already resumed", resume_unavailable_reason(store, "fixed"))

    def test_incompatible_checkpoint_does_not_change_simulation(self):
        with tempfile.TemporaryDirectory() as root, Store(root) as store:
            demo = run_demo(store)
            store.branch(demo["snapshot_id"], "wrong", {"replacement": "unsafe"})
            self.assertIn("requires correction", resume_unavailable_reason(store, "wrong"))
            with self.assertRaises(ValueError):
                resume(store, "wrong")
            self.assertEqual(Path(demo["target"]).read_text(), "unsafe")
            self.assertIsNone(store.one("branches", "wrong")["result_run"])

    def test_redaction_and_integrity(self):
        previous = os.environ.get("MANGEKYO_REDACT")
        os.environ["MANGEKYO_REDACT"] = "private-token"
        try:
            with tempfile.TemporaryDirectory() as root, Store(root) as store:
                digest = store.put({"secret": "private-token"})
                self.assertEqual(store.get(digest), {"secret": "[REDACTED]"})
                run = store.create_run("private-token", "run private-token")
                snap = store.snapshot(run, "before private-token", {"private-token": "private-token"})
                self.assertEqual(store.one("runs", run)["agent"], "[REDACTED]")
                self.assertEqual(store.one("snapshots", snap)["name"], "before [REDACTED]")
                self.assertEqual(store.context(snap), {"[REDACTED]": "[REDACTED]"})
                path = store.objects / digest[:2] / digest
                path.write_text("tampered")
                with self.assertRaises(ValueError):
                    store.get(digest)
        finally:
            if previous is None:
                os.environ.pop("MANGEKYO_REDACT", None)
            else:
                os.environ["MANGEKYO_REDACT"] = previous

    def test_provider_probe_uses_reported_cache_tokens(self):
        class Response(io.BytesIO):
            def __enter__(self):
                return self
            def __exit__(self, *_):
                self.close()

        def response(cached):
            return Response(json.dumps({"usage": {"input_tokens": 1200, "output_tokens": 10,
                "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": 0}}}).encode())

        with tempfile.TemporaryDirectory() as root, Store(root) as store:
            run = run_demo(store)
            with patch.dict(os.environ, {"TEST_OPENAI_KEY": "test-value"}), patch(
                    "mangekyo.provider.urllib.request.urlopen", side_effect=[response(0), response(1024)]) as request:
                result = probe_openai_cache(store, run["run_id"], "test-model", api_key_env="TEST_OPENAI_KEY",
                    prices={"input": 1.0, "cached": 0.1, "cache_write": 1.25, "output": 2.0})
            self.assertEqual(result["requests"][1]["cached_tokens"], 1024)
            self.assertEqual(request.call_count, 2)
            self.assertIn("estimated_usd", result["requests"][1])
            self.assertEqual(len(benchmark(store, run["run_id"])["provider_probes"]), 2)

    def test_schema_migrates_existing_store(self):
        with tempfile.TemporaryDirectory() as root:
            with Store(root) as store:
                run = store.create_run("agent", "before migration")
                store.db.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
                store.db.commit()
            with Store(root) as reopened:
                self.assertEqual(reopened.one("runs", run)["label"], "before migration")
                self.assertEqual(reopened.db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], "3")

    def test_evidence_bytes_and_annotations_survive_reopen(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WlM8qAAAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as root:
            with Store(root) as store:
                run = store.create_run("agent", "image inspection")
                event = store.event(run, "model", {"decision": "inspect"})
                artifact = store.artifact(run, "sample.png", png, "image/png", event_id=event,
                                          parsed_text="The agent read a square")
                store.annotate(artifact, 0, .1, .2, .3, .4, "Verify this region")
            with Store(root) as reopened:
                record = reopened.one("artifacts", artifact)
                self.assertEqual(record["event_id"], event)
                self.assertEqual(reopened.get_blob(record["blob_hash"]), png)
                self.assertEqual(reopened.get(record["parsed_hash"])["text"], "The agent read a square")
                self.assertEqual(reopened.annotations(artifact)[0]["note"], "Verify this region")
                with self.assertRaises(ValueError):
                    reopened.annotate(artifact, 0, .9, .9, .3, .3, "outside")

    def test_interrupted_object_write_does_not_change_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            with Store(root) as store:
                run = store.create_run("agent", "durability")
                snap = store.snapshot(run, "before", {"messages": ["original"]})
                (store.objects / "orphan" / ".pending-interrupted").parent.mkdir(exist_ok=True)
                (store.objects / "orphan" / ".pending-interrupted").write_text("partial")
            with Store(root) as reopened:
                self.assertEqual(reopened.context(snap)["messages"], ["original"])

    def test_cache_stats_measures_shared_snapshot_context(self):
        with tempfile.TemporaryDirectory() as root, Store(root) as store:
            run = store.create_run("agent", "reuse")
            first = store.snapshot(run, "first", {"shared": {"large": "same" * 100},
                                                   "changed": "old"})
            second = store.snapshot(run, "second", {"shared": {"large": "same" * 100},
                                                     "changed": "new"}, parent_id=first)
            stats = store.stats()
            self.assertEqual(stats["context_object_references"], 4)
            self.assertEqual(stats["context_unique_objects"], 3)
            self.assertGreater(stats["context_saved_bytes"], 0)
            self.assertEqual(stats["context_logical_bytes"] - stats["context_physical_bytes"],
                             stats["context_saved_bytes"])
            self.assertEqual(store.context(first)["changed"], "old")
            self.assertEqual(store.context(second)["changed"], "new")


if __name__ == "__main__":
    unittest.main()
