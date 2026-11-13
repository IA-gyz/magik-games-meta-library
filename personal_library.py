"""Personal annotations are separate from store-supplied metadata."""
import re


def normalize_tags(text):
    seen = set()
    result = []
    for part in re.split(r'[,;|\n]+', text if isinstance(text, str) else ''):
        tag = ' '.join(part.split())[:60]
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            result.append(tag)
        if len(result) == 40:
            break
    return ', '.join(result)


def annotations(row):
    raw = row.get('raw')
    value = raw.get('personal') if isinstance(raw, dict) else None
    value = value if isinstance(value, dict) else {}
    return {'favorite': value.get('favorite') is True,
            'personal_tags': normalize_tags(value.get('tags', ''))}


def save_personal(db, row, favorite, tags):
    db.save([{'store': row['store'], 'id': row['id'], 'title': row['title'],
              'raw': {'personal': {'favorite': favorite is True, 'tags': normalize_tags(tags)}}}])


def edit_personal(db, row, parent=None):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QCheckBox, QLineEdit, QDialogButtonBox
    dialog = QDialog(parent)
    dialog.setWindowTitle('Favorite and personal tags')
    form = QFormLayout(dialog)
    title = QLabel(row['title'])
    title.setTextFormat(Qt.PlainText)
    title.setWordWrap(True)
    form.addRow(title)
    values = annotations(row)
    favorite = QCheckBox('Favorite')
    favorite.setChecked(values['favorite'])
    form.addRow(favorite)
    tags = QLineEdit(values['personal_tags'])
    tags.setMaxLength(2500)
    tags.setPlaceholderText('For example: With kids, Try next, Finished')
    tags.setMinimumWidth(380)
    form.addRow('Personal tags', tags)
    help_text = QLabel('Separate tags with commas. These labels apply only to this store entry and survive library refreshes. Clear the field to remove all tags.')
    help_text.setWordWrap(True)
    form.addRow(help_text)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() == QDialog.Accepted:
        save_personal(db, row, favorite.isChecked(), tags.text())
        return True
    return False
