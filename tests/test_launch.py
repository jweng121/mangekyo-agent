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


if __name__ == "__main__":
    unittest.main()
