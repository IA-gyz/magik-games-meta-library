import sys, unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acquisition_report_text import acquisition_summary


class AcquisitionSummaryTests(unittest.TestCase):
    def test_complete_check_has_readable_counts_and_snapshot_caveat(self):
        text = acquisition_summary(
            [{"store": "Epic", "matched": 707, "unmatched_games": 0}]
        )
        self.assertIn("Entries matched to a date: 707", text)
        self.assertIn("Every entry in this check", text)
        self.assertIn("not a live check", text)
        self.assertIn("Manual dates", text)

    def test_missing_counts_are_not_assumed_zero(self):
        for value in [None, "707", True, -1]:
            text = acquisition_summary([{"store": "GOG", "matched": value}])
            self.assertIn("Entries matched to a date: Not reported", text)
            self.assertIn("not include enough counts", text)
            self.assertNotIn("Every entry", text)

    def test_warnings_and_partial_history_are_prominent(self):
        text = acquisition_summary(
            [
                {
                    "store": "Steam",
                    "matched": 100,
                    "unmatched_games": 0,
                    "warnings": ["HTTP 401"],
                    "license_history_complete": False,
                }
            ]
        )
        self.assertIn("Counts may be incomplete", text)
        self.assertIn("Only part of the Steam license history", text)
        self.assertNotIn("Every entry", text)

    def test_empty_and_unmatched_checks_are_distinct(self):
        self.assertIn("No date checks", acquisition_summary([]))
        self.assertIn(
            "no library entries",
            acquisition_summary([{"matched": 0, "unmatched_games": 0}]),
        )
        self.assertIn(
            "No account dates",
            acquisition_summary(
                [{"matched": 0, "unmatched_games": 145, "store": "EA"}]
            ),
        )
        self.assertIn(
            "even when your game library loads",
            acquisition_summary(
                [{"matched": 0, "unmatched_games": 145, "store": "EA"}]
            ),
        )

    def test_inputs_are_unchanged_and_partial_coverage_is_clear(self):
        reports = [
            {"store": "GOG", "matched": 218, "unmatched_games": 128, "warnings": []}
        ]
        before = deepcopy(reports)
        text = acquisition_summary(reports)
        self.assertEqual(reports, before)
        self.assertIn("Library entries in this check: 346", text)
        self.assertIn("Others are still unmatched", text)
