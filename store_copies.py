"""Conservative cross-store suggestions. Never merges or changes game records."""
import re
import unicodedata


def title_key(value):
    value = str(value or '').replace('®', '').replace('™', '')
    value = unicodedata.normalize('NFKC', value).casefold()
    return ' '.join(re.findall(r'[^\W_]+', value, flags=re.UNICODE))


def find_copies(rows):
    buckets = {}
    for row in rows:
        key = title_key(row.get('title'))
        if key:
            buckets.setdefault(key, []).append(row)
    groups = []
    for key, entries in buckets.items():
        if len({row['store'] for row in entries}) < 2:
            continue
        kinds = {str(row.get('type') or '').casefold() for row in entries}
        kinds.discard('')
        if len(kinds) > 1:
            continue
        years = [int(str(row['release'])[:4]) for row in entries if re.match(r'^\d{4}(?:-|$)', str(row.get('release') or ''))]
        # Missing dates must not bridge a known original/remake conflict.
        if years and max(years) - min(years) > 1:
            continue
        groups.append({'title': entries[0]['title'], 'reason': 'Same normalized title; no conflicting known release years or content types. Verify editions before choosing.',
                       'entries': sorted(entries, key=lambda row: (row['store'], str(row['id'])))})
    return sorted(groups, key=lambda group: title_key(group['title']))


def choose_copy(groups, parent=None):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QDialogButtonBox
    from date_display import friendly_date
    dialog = QDialog(parent)
    dialog.setWindowTitle('Copies across stores')
    dialog.resize(1040, 620)
    layout = QVBoxLayout(dialog)
    note = QLabel('Possible copies from your whole saved library. Matching titles are suggestions; editions are not merged. Select a store entry to return to its install and launch actions. Showing a copy clears browsing filters so it can be found.')
    note.setWordWrap(True)
    layout.addWidget(note)
    layout.addWidget(QLabel(f'{len(groups):,} matching title groups across stores. No library records are changed.'))
    search = QLineEdit()
    search.setPlaceholderText('Find a title, store, or personal tag…')
    layout.addWidget(search)
    tree = QTreeWidget()
    tree.setHeaderLabels(['Title / store', 'Installed', 'Added to account', 'Favorite', 'Personal tags', 'In latest refresh', 'Store ID'])
    layout.addWidget(tree)
    for group in groups:
        root = QTreeWidgetItem([group['title']])
        root.setToolTip(0, group['reason'])
        tree.addTopLevelItem(root)
        for row in group['entries']:
            item = QTreeWidgetItem([row['store'], row.get('installation_status') or '—', friendly_date(row.get('date_added')), 'Yes' if row.get('favorite') else 'No', row.get('personal_tags') or '—', 'Yes' if row.get('active') else 'No', str(row['id'])])
            item.setData(0, Qt.UserRole, (row['store'], str(row['id'])))
            item.setToolTip(0, str(row['title']))
            root.addChild(item)
        root.setExpanded(True)
    tree.setColumnWidth(0, 300)
    for col in (1, 2, 3, 5):
        tree.resizeColumnToContents(col)
    buttons = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Close)
    show = buttons.button(QDialogButtonBox.Open)
    show.setText('Show selected copy (clears filters)')
    show.setEnabled(False)
    buttons.rejected.connect(dialog.reject)
    show.clicked.connect(dialog.accept)
    tree.currentItemChanged.connect(lambda item, previous: show.setEnabled(bool(item and item.data(0, Qt.UserRole))))
    tree.itemDoubleClicked.connect(lambda item, column: dialog.accept() if item.data(0, Qt.UserRole) else None)
    def filter_groups(text):
        words = text.casefold().split()
        for i in range(tree.topLevelItemCount()):
            root = tree.topLevelItem(i)
            terms = ' '.join([root.text(0)] + [root.child(j).text(c) for j in range(root.childCount()) for c in (0, 4)]).casefold()
            root.setHidden(not all(word in terms for word in words))
        current = tree.currentItem()
        show.setEnabled(bool(current and current.data(0, Qt.UserRole) and not current.parent().isHidden()))
    search.textChanged.connect(filter_groups)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.Accepted and tree.currentItem():
        return tree.currentItem().data(0, Qt.UserRole)
    return None
