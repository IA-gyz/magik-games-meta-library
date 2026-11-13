"""Qt-free completion presentation and automatic follow-up policy."""

from contracts import Severity


def completion_message(result):
    if result.cancelled:
        return "Stopped"
    if result.failed:
        return "Finished with errors"
    if any(event.severity == Severity.WARNING for event in result.events):
        return "Finished with warnings"
    return "Finished"


def needs_installation_scan(mode, result, stop_requested=False):
    # Partial source failures still merit a scan of successfully saved libraries.
    return (
        mode == "sync"
        and result is not None
        and not result.cancelled
        and not stop_requested
    )
