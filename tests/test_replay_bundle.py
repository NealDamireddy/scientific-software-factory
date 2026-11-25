import unittest
from factory.context import ROOT, read_json
from factory.assays.b12.replay_bundle import replay_package


class SavedRunTests(unittest.TestCase):
    def setUp(self):
        self.bundle = read_json(ROOT/"public/b12/completed.json")

    def test_committed_record_replays(self):
        direct, followup = replay_package(self.bundle)
        self.assertEqual(direct["result"]["status"], "review")
        self.assertEqual(followup["result"]["status"], "ok")
        self.assertEqual(followup["result"]["factor"], 2)

    def test_tampered_source_is_rejected(self):
        task = self.bundle["direct"]
        self.bundle["sources"][task["id"]]["files"]["analysis.py"] += "# changed"
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            replay_package(self.bundle)
