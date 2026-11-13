"""Read-only report widgets; formatting lives in the Qt-free report_content module."""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTabWidget
from ui_actions import action_button
from unknown_style import UnknownTextEdit
from report_content import installation_content, acquisition_content, metadata_content


def show_report(parent, title, content, *, technical=None, help_text=None):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(1000, 650)
    layout = QVBoxLayout(dialog)
    pages = [("Summary", content)]
    if technical is not None:
        pages.append(("Technical details", technical))
    if help_text is not None:
        pages.append(("Help", help_text))
    tabs = QTabWidget() if len(pages) > 1 else None
    for label, text in pages:
        output = UnknownTextEdit()
        output.setReadOnly(True)
        output.setPlainText(text)
        if tabs is not None:
            tabs.addTab(output, label)
        else:
            layout.addWidget(output)
    if tabs is not None:
        layout.addWidget(tabs)
    close = action_button("Close", "settings")
    close.clicked.connect(dialog.accept)
    layout.addWidget(close)
    dialog.exec()


def show_prepared_report(parent, data):
    options = {
        key: value for key, value in data.items() if key not in ("title", "content")
    }
    show_report(parent, data["title"], data["content"], **options)


def show_installation_report(parent, snapshot, options):
    show_prepared_report(parent, installation_content(snapshot))


def show_acquisition_report(parent, reports):
    show_prepared_report(parent, acquisition_content(reports))


def show_metadata_report(parent, results, rows):
    show_prepared_report(parent, metadata_content(results, rows))
