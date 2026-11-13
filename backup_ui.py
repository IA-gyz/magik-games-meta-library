"""Backup picker; all snapshot and restore work runs in LocalTask."""
from datetime import datetime, timezone
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QDialogButtonBox, QFileDialog
from database_backups import list_backups
from date_display import friendly_date


def choose_action(db, parent=None):
    dialog = QDialog(parent)
    dialog.setWindowTitle('Library database backups')
    dialog.resize(650, 260)
    layout = QVBoxLayout(dialog)
    note = QLabel('Backups include games, metadata, favorites, personal tags, installation scan results and saved reports. Settings, API keys, account login files and downloaded artwork are not included. Restore replaces the whole database, rather than merging games.')
    note.setWordWrap(True)
    layout.addWidget(note)
    note = QLabel('Automatic snapshots: one per day before a background library operation, when the library is not empty. Keeps 7 daily, 5 manual and 3 pre-restore recovery copies. Older copies rotate only after a new backup is saved.')
    note.setWordWrap(True)
    layout.addWidget(note)
    picker = QComboBox()
    for path in list_backups(db):
        stamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        kind = path.name.split('-')[0].title()
        picker.addItem(f'{kind} · {friendly_date(stamp)} · {path.stat().st_size / 1048576:.1f} MiB', str(path))
    layout.addWidget(picker)
    if not picker.count():
        layout.addWidget(QLabel('No backups yet. Create one now, or restore a compatible database file.'))
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    create = buttons.addButton('Create backup now', QDialogButtonBox.ActionRole)
    restore = buttons.addButton('Restore selected…', QDialogButtonBox.ActionRole)
    restore.setEnabled(picker.count() > 0)
    browse = buttons.addButton('Restore from file…', QDialogButtonBox.ActionRole)
    action = []
    def choose(kind, path=None):
        action[:] = [kind, path]
        dialog.accept()
    def browse_file():
        path, _ = QFileDialog.getOpenFileName(dialog, 'Choose a library database backup', '', 'SQLite database (*.sqlite3 *.sqlite *.db);;All files (*)')
        if path:
            choose('restore', path)
    create.clicked.connect(lambda: choose('backup'))
    restore.clicked.connect(lambda: choose('restore', picker.currentData()))
    browse.clicked.connect(browse_file)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return tuple(action) if dialog.exec() == QDialog.Accepted and action else None
