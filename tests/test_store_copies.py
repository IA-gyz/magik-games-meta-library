import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store_copies import find_copies, title_key


def row(store, ident, title, release=None, kind='game'):
    return {'store': store, 'id': ident, 'title': title, 'release': release, 'type': kind}


class StoreCopyTests(unittest.TestCase):
    def test_cross_store_titles_and_editions(self):
        rows = [row('Steam', '1', 'Portal 2™', '2011-01-01'), row('GOG', '2', 'PORTAL 2', '2012-01-01'), row('Epic', '3', 'Portal 2 Deluxe'), row('Steam', '4', 'Unrelated')]
        groups = find_copies(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual({r['id'] for r in groups[0]['entries']}, {'1', '2'})
        self.assertEqual(rows[0]['title'], 'Portal 2™')

    def test_same_store_and_conflicting_years_never_group(self):
        self.assertFalse(find_copies([row('Steam', '1', 'Game'), row('Steam', '2', 'Game')]))
        self.assertFalse(find_copies([row('Steam', '1', 'Game', '2000-01-01'), row('GOG', '2', 'Game', '2020-01-01'), row('Epic', '3', 'Game')]))
        self.assertFalse(find_copies([row('Steam', '1', 'Game'), row('GOG', '2', 'Game', kind='dlc')]))

    def test_missing_year_is_only_a_suggestion_and_unicode_preserved(self):
        self.assertEqual(len(find_copies([row('GOG', '1', 'Game'), row('Epic', '2', 'Game')])), 1)
        self.assertNotEqual(title_key('日本語 A'), title_key('日本語 B'))
        self.assertFalse(find_copies([row('Steam', '1', ''), row('GOG', '2', '')]))

    def test_dialog_uses_store_identity(self):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import QApplication, QTreeWidget, QDialogButtonBox
        from store_copies import choose_copy
        app = QApplication.instance() or QApplication([])
        def choose():
            dialog = app.activeModalWidget()
            tree = dialog.findChild(QTreeWidget)
            item = tree.topLevelItem(0).child(1)
            tree.setCurrentItem(item)
            self.assertEqual(item.data(0, Qt.UserRole), ('Steam', '1'))
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Open).click()
        QTimer.singleShot(0, choose)
        result = choose_copy(find_copies([row('Steam', '1', 'Game'), row('GOG', '2', 'Game')]))
        self.assertEqual(tuple(result), ('Steam', '1'))
