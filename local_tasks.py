"""Background export and saved-report preparation. Never creates Qt widgets."""

from PySide6.QtCore import QThread
from connectors import Cancelled
from catalog_export import export_catalog
from report_content import installation_content, acquisition_content, metadata_content


class LocalTask(QThread):
    def __init__(
        self,
        kind,
        db,
        cancel,
        *,
        rows=None,
        path=None,
        file_format="json",
        scope="all",
        parent=None,
    ):
        super().__init__(parent)
        self.kind, self.db, self.cancel = kind, db, cancel
        self.rows, self.path, self.file_format = rows, path, file_format
        self.scope = scope
        self.outcome, self.value = None, None

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()

    def run(self):
        try:
            self.check_cancel()
            if self.kind in ("backup", "restore"):
                from database_backups import backup, restore
                value = backup(self.db, check=self.check_cancel) if self.kind == "backup" else restore(self.db, self.path, self.check_cancel)
                self.outcome, self.value = self.kind, str(value)
                return
            if self.kind == "export":
                export_catalog(
                    self.path,
                    self.rows,
                    self.file_format,
                    scope=self.scope,
                    check_cancel=self.check_cancel,
                )
                # A published file is a success even if Stop arrives immediately afterward.
                self.outcome, self.value = "saved", len(self.rows)
                return
            snapshot = self.db.report_snapshot(self.kind)
            self.check_cancel()
            builders = {
                "installations": installation_content,
                "acquisition": acquisition_content,
            }
            value = (
                metadata_content(*snapshot)
                if self.kind == "metadata"
                else builders[self.kind](snapshot)
            )
            self.check_cancel()
            self.outcome, self.value = "report", value
        except Cancelled:
            self.outcome = "cancelled"
        except (OSError, ValueError, TypeError) as exc:
            self.outcome, self.value = "error", str(exc)
        except Exception as exc:
            self.outcome, self.value = (
                "error",
                "The task could not finish. Technical error: " + type(exc).__name__,
            )
