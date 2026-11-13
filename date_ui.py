from PySide6.QtCore import QDate, Qt, QLocale
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QDateEdit,
    QCheckBox,
    QDialogButtonBox,
    QLabel,
)
from date_display import parse_date
from unknown_style import set_unknown_label


class DateAddedDialog(QDialog):
    def __init__(self, title, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Date added — " + title)
        self.value = None
        layout = QFormLayout(self)
        label = QLabel(
            "Choose the day this game was added to your store account, not the day it was installed. This manual value takes priority over dates found during refreshes. Uncheck Date known to keep it Unknown, even after a refresh."
        )
        set_unknown_label(label, label.text())
        label.setWordWrap(True)
        layout.addRow(label)
        self.known = QCheckBox("Date known")
        self.known.setChecked(bool(current))
        layout.addRow(self.known)
        self.date = QDateEdit()
        self.date.setLocale(QLocale(QLocale.English, QLocale.UnitedKingdom))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd MMM yyyy")
        self.date.setMinimumDate(QDate(1900, 1, 1))
        self.date.setMaximumDate(QDate.currentDate())
        parsed = parse_date(current)
        if parsed:
            when, precision = parsed
            if precision == "datetime":
                when = when.astimezone()
            selected = QDate(when.year, when.month, when.day)
        else:
            selected = QDate.currentDate()
        self.date.setDate(selected)
        self.date.setEnabled(self.known.isChecked())
        self.known.toggled.connect(self.date.setEnabled)
        layout.addRow("Date added to your account", self.date)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def save(self):
        self.value = (
            self.date.date().toString(Qt.ISODate) if self.known.isChecked() else None
        )
        self.accept()
