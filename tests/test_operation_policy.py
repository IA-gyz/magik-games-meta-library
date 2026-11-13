import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts import LogEntry, OperationResult, Severity
from operation_policy import completion_message, needs_installation_scan


class OperationPolicyTests(unittest.TestCase):
    def test_completion_precedence(self):
        warning = (LogEntry("warning", Severity.WARNING),)
        for result, expected in [
            (OperationResult(()), "Finished"),
            (OperationResult(warning), "Finished with warnings"),
            (OperationResult(warning, failed=True), "Finished with errors"),
            (OperationResult(warning, cancelled=True, failed=True), "Stopped"),
        ]:
            self.assertEqual(completion_message(result), expected)

    def test_sync_only_and_requires_result(self):
        for mode in ["scan", "enrich", "retry"]:
            self.assertFalse(needs_installation_scan(mode, OperationResult(())))
        self.assertFalse(needs_installation_scan("sync", None))
        self.assertTrue(needs_installation_scan("sync", OperationResult(())))

    def test_partial_failures_scan_but_cancellation_never_does(self):
        self.assertTrue(
            needs_installation_scan("sync", OperationResult((), failed=True))
        )
        self.assertFalse(
            needs_installation_scan("sync", OperationResult((), cancelled=True))
        )
        self.assertFalse(
            needs_installation_scan("sync", OperationResult(()), stop_requested=True)
        )
