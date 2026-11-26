import sys
import tempfile
import unittest

from mangekyo.launch import launch
from mangekyo.store import Store


class LaunchTest(unittest.TestCase):
    def test_process_identity_and_failure_are_recorded(self):
        with tempfile.TemporaryDirectory() as root, Store(root) as store:
            code = launch(store, [sys.executable, "-c", "raise SystemExit(3)"], "Test task")
            self.assertEqual(code, 3)
            run = store.runs()[0]
            self.assertEqual(run["label"], "Test task")
            self.assertEqual(run["status"], "failed")
            self.assertEqual(run["adapter"], "process")
            events = store.events(run["id"])
            self.assertEqual([event["kind"] for event in events], ["launch", "process", "exit"])
            self.assertEqual(events[0]["payload"]["argv"][0], sys.executable)
            self.assertEqual(events[-1]["payload"]["exit_code"], 3)

    def test_recorder_attaches_to_launcher_run(self):
        script = ("from mangekyo import RunRecorder, Store; "
                  "s=Store(); r=RunRecorder(s, 'agent', 'task'); "
                  "r.record('tool', name='lookup', result='found'); r.finish(); s.close()")
        with tempfile.TemporaryDirectory() as root, Store(root) as store:
            self.assertEqual(launch(store, [sys.executable, "-c", script], "Linked task"), 0)
            runs = store.runs()
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "completed")
            self.assertEqual([event["kind"] for event in store.events(runs[0]["id"])],
                             ["launch", "process", "tool", "exit"])


if __name__ == "__main__":
    unittest.main()
