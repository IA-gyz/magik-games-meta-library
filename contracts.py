"""Qt-free result contracts shared by providers, workers and presentation."""

from dataclasses import dataclass
from enum import Enum
from copy import deepcopy


class Severity(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class LogEntry:
    text: str
    severity: Severity = Severity.INFO
    source: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "severity", Severity(self.severity))


@dataclass(frozen=True)
class OperationResult:
    events: tuple[LogEntry, ...]
    cancelled: bool = False
    failed: bool = False

    @property
    def text(self):
        return "\n".join(event.text for event in self.events)


class SummaryMessages(list):
    """Retain the plain-text summary API for callers while carrying typed events."""

    def __init__(self, events):
        self.events = tuple(events)
        super().__init__(event.text for event in self.events)


class LibraryRows(list):
    """List-compatible provider data; diagnostics belong to the batch, not a game."""

    def __init__(self, rows, acquisition_report=None):
        super().__init__(rows)
        self.acquisition_report = acquisition_report


@dataclass(frozen=True)
class LibraryResult:
    store: str
    rows: list[dict]
    acquisition_report: dict | None = None

    @classmethod
    def from_provider(cls, store, payload):
        if isinstance(payload, cls):
            if payload.store != store:
                raise ValueError("Provider returned a different store")
            return cls.from_provider(
                store, LibraryRows(payload.rows, payload.acquisition_report)
            )
        if not isinstance(payload, list):
            raise ValueError("Provider returned an invalid library batch")
        report = getattr(payload, "acquisition_report", None)
        rows = []
        for original in payload:
            if (
                not isinstance(original, dict)
                or original.get("store") != store
                or not original.get("id")
            ):
                raise ValueError("Provider returned an invalid library record")
            row = dict(original)
            legacy = row.pop("_acquisition_report", None)
            if legacy is not None:
                if report is not None and legacy != report:
                    raise ValueError(
                        "Provider returned conflicting acquisition reports"
                    )
                report = legacy
            rows.append(row)
        if report is not None:
            if not isinstance(report, dict) or report.get("store", store) != store:
                raise ValueError("Provider returned an invalid acquisition report")
            report = deepcopy(report)
            report.setdefault("store", store)
        return cls(store, rows, report)
