import os, sys, unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import report_dialogs as reports
except ImportError:
    reports = None


@unittest.skipIf(reports is None, "PySide6 required")
class ReportTextTests(unittest.TestCase):
    def test_date_report_tabs_keep_technical_data_available(self):
        from PySide6.QtWidgets import QApplication, QTabWidget

        app = QApplication.instance() or QApplication([])
        saved = [
            {
                "store": "Epic",
                "matched": 707,
                "unmatched_games": 0,
                "warnings": [],
                "source": "Exact source",
                "extra_diagnostic": "<literal>",
            }
        ]
        before = deepcopy(saved)

        def inspect(dialog):
            tabs = dialog.findChild(QTabWidget)
            self.assertEqual(
                [tabs.tabText(i) for i in range(tabs.count())],
                ["Summary", "Technical details", "Help"],
            )
            self.assertIn("707", tabs.widget(0).toPlainText())
            self.assertIn(
                '"extra_diagnostic": "<literal>"', tabs.widget(1).toPlainText()
            )
            self.assertNotIn("extra_diagnostic", tabs.widget(0).toPlainText())
            app.processEvents()
            dialog.close()
            return 0

        with patch.object(reports.QDialog, "exec", inspect):
            reports.show_acquisition_report(None, saved)
        self.assertEqual(saved, before)

    def test_date_report_explains_scope_and_empty_state(self):
        with patch.object(reports, "show_report") as show:
            reports.show_acquisition_report(None, [])
        text = show.call_args.args[2]
        self.assertIn("not the installation or release date", text)
        self.assertIn("do not fetch account history", text)
        self.assertIn("No date checks", text)

    def test_game_details_report_preserves_data_and_explains_retry(self):
        results = [
            {
                "store": "Steam",
                "id": "1",
                "title": "Old",
                "outcome": "failed",
                "reason": "HTTP 500",
                "time": "2026-01-01T00:00:00+00:00",
            }
        ]
        before = deepcopy(results)
        with patch.object(reports, "show_report") as show:
            reports.show_metadata_report(
                None, results, [{"store": "Steam", "id": "1", "title": "New"}]
            )
        self.assertIn("Steam", show.call_args.args[2])
        text = show.call_args.kwargs["technical"]
        self.assertIn("New", text)
        self.assertIn("Request failed", text)
        self.assertIn("Can retry after:", text)
        self.assertIn("HTTP 500", text)
        self.assertEqual(results, before)

    def test_game_report_includes_successes_in_technical_details(self):
        saved = [
            {
                "store": "Epic",
                "id": "1",
                "title": "A",
                "outcome": "enriched",
                "reason": "Saved",
                "time": "2026-01-01",
            }
        ]
        with patch.object(reports, "show_report") as show:
            reports.show_metadata_report(None, saved, [])
        self.assertIn("Details retrieved: 1", show.call_args.args[2])
        self.assertIn("Store: Epic", show.call_args.kwargs["technical"])
        self.assertIn(
            "Not needed for this saved successful result",
            show.call_args.kwargs["technical"],
        )
        self.assertIn("What should I do next?", show.call_args.kwargs["help_text"])

    def test_installation_report_explains_detection_limits(self):
        with patch.object(reports, "show_report") as show:
            reports.show_installation_report(None, {}, {})
        text = show.call_args.args[2]
        self.assertIn("not a full check", text)
        self.assertIn("may be installed elsewhere", text)
        self.assertIn("No installed-game records", text)
