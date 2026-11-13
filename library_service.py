"""Provider-independent validation, report persistence and refresh summaries."""

from provider_registry import provider
from contracts import LibraryResult, LogEntry, Severity
from connectors import Cancelled


def refresh_store(db, store, options, cancel, progress, fetcher, reports=None):
    batch = LibraryResult.from_provider(store, fetcher(options, cancel, progress))
    if cancel.is_set():
        raise Cancelled()
    if reports is not None:
        reports[store] = batch.acquisition_report or {}
    report = batch.acquisition_report or {}
    warnings = list(report.get("warnings") or [])
    dated = sum(bool(row.get("date_added")) for row in batch.rows)
    message = f"{len(batch.rows)} library entries loaded; date added found for {dated}"
    if not dated:
        message += " (see Date added report for an explanation)"
    if warnings:
        message += "; date added warning: " + str(warnings[0])
    if store == "GOG":
        named = sum(row["title"] != f"GOG product {row['id']}" for row in batch.rows)
        message += f"; {named} titles identified from your GOG account"
        shelf = next(
            (
                row.get("raw", {}).get("account_shelf_warnings")
                for row in batch.rows
                if row.get("raw", {}).get("account_shelf_warnings")
            ),
            [],
        )
        if shelf:
            message += "; some account titles could not be read: " + str(shelf[0])
            warnings.extend(shelf)
    severity = Severity.WARNING if warnings else Severity.SUCCESS

    def check_cancel():
        if cancel.is_set():
            raise Cancelled()

    check_cancel()
    db.save_refresh(
        store,
        batch.rows,
        batch.acquisition_report,
        message,
        severity=severity.value,
        complete=provider(store).complete_library,
        before_commit=check_cancel,
    )
    return LogEntry(f"{store}: {message}", severity, store)
