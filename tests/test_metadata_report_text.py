import sys, unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metadata_report_text import metadata_summary


class MetadataSummaryTests(unittest.TestCase):
    def test_counts_are_per_store_and_input_is_unchanged(self):
        results = [
            {"store": "Steam", "outcome": "enriched"},
            {"store": "Steam", "outcome": "partial"},
            {"store": "GOG", "outcome": "deferred"},
            {"store": "Epic", "outcome": "failed"},
            {"store": "Epic", "outcome": "unavailable"},
        ]
        before = deepcopy(results)
        text = metadata_summary(results)
        self.assertEqual(results, before)
        self.assertIn("saved result: 5", text)
        self.assertIn("Details retrieved: 1", text)
        self.assertIn("Some details retrieved: 1", text)
        self.assertIn("Waiting: store requests were paused: 1", text)
        self.assertIn("Request failed: 1", text)

    def test_empty_report_explains_how_to_begin(self):
        text = metadata_summary([])
        self.assertIn("No game-detail requests", text)
        self.assertIn("Choose Get missing game details", text)

    def test_unknown_outcomes_are_not_counted_as_success(self):
        text = metadata_summary([{"store": "Steam", "outcome": "future_status"}])
        self.assertIn("Other or unrecognized results: 1", text)
        self.assertIn("Details retrieved: 0", text)

    def test_success_does_not_claim_complete_fields(self):
        text = metadata_summary([{"store": "Epic", "outcome": "enriched"}])
        self.assertIn("does not mean every field is known", text)
        self.assertIn("not a live check", text)
        self.assertIn("Games with no saved result are not counted", text)
