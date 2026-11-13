"""Background orchestration; providers and UI share Qt-free result contracts."""

import threading
from PySide6.QtCore import QThread, Signal
from core import STORES
from provider_registry import selected_providers
from contracts import LogEntry, OperationResult, Severity
from connectors import FETCHERS, Cancelled, FetchError
from enrichment import run_enrichment, select_candidates
from installations import scan as scan_installations, ScanCancelled, scan_summary
from library_service import refresh_store
from error_messages import explain_store_error


class Worker(QThread):
    progress = Signal(str)
    changed = Signal()
    result = Signal(object)

    def __init__(self, db, options, mode, enrich, selected=None, sources=None, force=False):
        super().__init__()
        self.db = db
        self.options = options.copy()
        self.mode = mode
        self.enrich = enrich
        self.selected = frozenset(selected or ())
        self.sources = sources or []
        self.force = force
        self.cancel = threading.Event()

    def complete(self, events, cancelled=False):
        self.result.emit(
            OperationResult(
                tuple(events),
                cancelled,
                any(event.severity == Severity.ERROR for event in events),
            )
        )

    def run(self):
        events = []
        dates_pending = []
        try:
            from database_backups import ensure_daily
            def check_backup_cancel():
                if self.cancel.is_set():
                    raise Cancelled()
            ensure_daily(self.db, check_backup_cancel)
            if self.mode == "selected":
                def rows():
                    return [r for r in self.db.rows() if (r["store"], str(r["id"])) in self.selected]
                if "Store details" in self.sources:
                    candidates, _ = select_candidates(rows(), self.db.metadata_results(), None, force=self.force)
                    summary = run_enrichment(self.db, candidates, self.cancel, self.progress.emit, self.changed.emit, self.options)
                    events.extend(getattr(summary, "events", tuple(LogEntry(str(t)) for t in summary)))
                if "Metacritic" in self.sources:
                    from metacritic import run_metacritic
                    events.extend(run_metacritic(self.db, self.cancel, self.progress.emit, self.changed.emit, rows=rows(), force=self.force))
                extras = [s for s in self.sources if s not in ("Store details", "Metacritic")]
                if extras:
                    from extra_metadata import run_extra
                    from extra_schema import SOURCES
                    options = {**self.options, **{"metadata_" + s: s in extras for s in SOURCES}}
                    events.extend(run_extra(self.db, options, self.cancel, self.progress.emit, self.changed.emit, rows=rows(), force=self.force))
                self.changed.emit()
                self.complete(events or [LogEntry("No metadata sources were selected.")])
                return
            if self.mode == "extra":
                from extra_metadata import run_extra
                self.complete(run_extra(self.db, self.options, self.cancel, self.progress.emit, self.changed.emit))
                return
            if self.mode == "metacritic":
                from metacritic import run_metacritic
                self.complete(run_metacritic(self.db, self.cancel, self.progress.emit, self.changed.emit))
                return
            if self.mode == "scan":
                snapshot = scan_installations(
                    self.options,
                    self.db.installations(),
                    self.cancel,
                    self.progress.emit,
                )
                if self.cancel.is_set():
                    raise Cancelled()
                self.db.save_installations(snapshot)
                self.changed.emit()
                warning = bool(snapshot.get("notes")) or any(
                    entry["state"] != "Installed"
                    for entry in snapshot.get("entries", [])
                )
                self.complete(
                    [
                        LogEntry(
                            scan_summary(snapshot),
                            Severity.WARNING if warning else Severity.SUCCESS,
                            "Installations",
                        )
                    ]
                )
                return
            if self.mode == "sync":
                selected = [spec.name for spec in selected_providers(self.options)]
                if not selected:
                    self.complete(
                        [
                            LogEntry(
                                "No stores are enabled. Open Sources and enable at least one store, then refresh again.",
                                Severity.WARNING,
                            )
                        ]
                    )
                    return
                store_reports = {}
                for store in selected:
                    if self.cancel.is_set():
                        raise Cancelled()
                    self.progress.emit(f"{store}: reading your library…")
                    try:
                        events.append(
                            refresh_store(
                                self.db,
                                store,
                                self.options,
                                self.cancel,
                                self.progress.emit,
                                FETCHERS[store],
                                reports=store_reports,
                            )
                        )
                        self.changed.emit()
                    except Cancelled:
                        raise
                    except Exception as exc:
                        message = (
                            explain_store_error(exc, store)
                            if isinstance(exc, FetchError)
                            else str(exc)
                            if isinstance(exc, (ValueError, FileNotFoundError))
                            else type(exc).__name__ + " while reading the library"
                        )
                        self.db.status(
                            store, "Failed: " + message, severity=Severity.ERROR.value
                        )
                        events.append(
                            LogEntry(
                                f"{store}: failed — {message}", Severity.ERROR, store
                            )
                        )
                        self.changed.emit()
                # Missing date-added lookups outrank every other download: while a store
                # postponed package mappings (rate limited), no details are requested so
                # the next refresh can spend its request budget on the dates first.
                dates_pending = sorted(
                    store
                    for store, report in store_reports.items()
                    if report.get("date_fetch_incomplete")
                )
            if self.enrich or self.mode in ["enrich", "retry"]:
                if self.mode == "sync" and dates_pending:
                    events.append(
                        LogEntry(
                            "Date added: "
                            + ", ".join(dates_pending)
                            + " still has package lookups waiting after rate limiting. Game details were not requested so the date lookups can finish first. Refresh libraries again, or choose Get missing game details.",
                            Severity.WARNING,
                            "Metadata",
                        )
                    )
                else:
                    enabled = (
                        None
                        if self.mode in ["enrich", "retry"]
                        else [
                            store
                            for store in STORES
                            if self.options.get("enabled_" + store)
                        ]
                    )
                    candidates, postponed = select_candidates(
                        self.db.rows(),
                        self.db.metadata_results(),
                        enabled,
                        force=self.mode == "retry",
                    )
                    if postponed:
                        events.append(
                            LogEntry(
                                f"Game details: {postponed} entries are waiting before another attempt. Choose Retry missing details to try them now.",
                                Severity.WARNING,
                                "Metadata",
                            )
                        )
                    summary = run_enrichment(
                        self.db,
                        candidates,
                        self.cancel,
                        self.progress.emit,
                        self.changed.emit,
                        self.options,
                    )
                    events.extend(
                        getattr(
                            summary,
                            "events",
                            tuple(LogEntry(str(text)) for text in summary),
                        )
                    )
            self.changed.emit()
            self.complete(
                events or [LogEntry("There are no missing game details to request.")]
            )
        except (Cancelled, ScanCancelled):
            self.changed.emit()
            events.append(
                LogEntry(
                    "Installation scan stopped. The results of the previous scan were kept."
                    if self.mode == "scan"
                    else "Stopped. Libraries and game details already received have been saved.",
                    Severity.INFO,
                )
            )
            self.complete(events, cancelled=True)
        except Exception as exc:
            events.append(
                LogEntry(
                    "The operation could not finish. Technical error: "
                    + type(exc).__name__,
                    Severity.ERROR,
                )
            )
            self.complete(events)

        finally:
            if self.cancel.is_set() and self.mode in ("extra", "selected") and self.options.get("opencritic_api_key"):
                from opencritic_quota import Quota, QuotaPaused
                try:
                    quota = Quota(self.options)
                    if quota.path.exists():
                        quota.clear_queue()
                except (QuotaPaused, OSError):
                    pass
