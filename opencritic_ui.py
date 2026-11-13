"""Saved quota and queue inspector; opening it never sends an API request."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox
from unknown_style import UnknownTextEdit
from opencritic_quota import Quota, QuotaPaused, describe


def show_quota(options, parent=None):
    dialog = QDialog(parent)
    dialog.setWindowTitle('OpenCritic quota and queued games')
    dialog.resize(740, 550)
    layout = QVBoxLayout(dialog)
    text = UnknownTextEdit()
    text.setReadOnly(True)
    layout.addWidget(text)
    note = QLabel('Balances come from normal API responses, not a separate billing lookup. Automatic continuation works while Magik is open, idle, and OpenCritic is enabled. With known quota, the per-fetch cap limits each batch, not the total automatic usage. The Sources tab has an automatic-resume switch and the per-fetch cap. Fetch selected details for a game to learn the quota headers.')
    note.setWordWrap(True)
    layout.addWidget(note)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    refresh = buttons.addButton('Refresh saved display', QDialogButtonBox.ActionRole)
    clear = buttons.addButton('Cancel queued games', QDialogButtonBox.ActionRole)
    def update():
        if not options.get('opencritic_api_key'):
            text.setPlainText('Add your RapidAPI key in Sources first.')
            clear.setEnabled(False)
            return
        try:
            state = Quota(options).snapshot()
            text.setPlainText(describe(state))
            clear.setEnabled(bool(state.get('queue')))
        except (QuotaPaused, OSError) as exc:
            text.setPlainText(str(exc))
            clear.setEnabled(False)
    def cancel():
        try:
            Quota(options).clear_queue()
        except (QuotaPaused, OSError):
            pass
        update()
    refresh.clicked.connect(update)
    clear.clicked.connect(cancel)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    update()
    timer = QTimer(dialog)
    timer.setInterval(2000)
    timer.timeout.connect(update)
    timer.start()
    dialog.exec()
    timer.stop()
