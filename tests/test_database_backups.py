import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import game
from storage import Database
from database_backups import backup, restore, read_snapshot, list_backups, ensure_daily
from connector_io import Cancelled
from personal_library import save_personal


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / 'library.sqlite3')
        self.row = game('GOG', '1', 'Game', {})
        self.db.save([self.row])

    def test_restore_and_recovery_can_undo_restore(self):
        save_personal(self.db, self.row, True, 'With kids')
        saved = backup(self.db)
        self.db.save([game('GOG', '2', 'Later game', {})])
        recovery = restore(self.db, saved)
        self.assertEqual([r['id'] for r in self.db.rows()], ['1'])
        self.assertTrue(self.db.rows()[0]['favorite'])
        self.assertEqual(self.db.rows()[0]['personal_tags'], 'With kids')
        restore(self.db, recovery)
        self.assertEqual({r['id'] for r in self.db.rows()}, {'1', '2'})
        self.assertEqual(os.stat(saved).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(saved.parent).st_mode & 0o777, 0o700)

    def test_wal_data_is_in_snapshot(self):
        with self.db.connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            self.db.save([game('Steam', '620', 'Portal 2', {})])
            saved = backup(self.db)
            values = read_snapshot(saved)
        self.assertEqual(len(values['games']), 2)

    def test_rotation_and_daily_skip(self):
        for _ in range(8):
            backup(self.db, 'daily')
        self.assertEqual(len(list_backups(self.db)), 7)
        self.assertIsNone(ensure_daily(self.db))
        unrelated = self.db.path.parent / 'backups' / 'notes.txt'
        unrelated.write_text('keep')
        backup(self.db, 'daily')
        self.assertTrue(unrelated.exists())
        self.assertEqual(len(list_backups(self.db)), 7)

    def test_invalid_source_keeps_current_and_no_recovery(self):
        invalid = Path(self.tmp.name) / 'invalid.db'
        with sqlite3.connect(invalid) as connection:
            connection.execute('CREATE TABLE games (payload TEXT)')
        before = self.db.rows()
        with self.assertRaises(ValueError):
            restore(self.db, invalid)
        self.assertEqual(self.db.rows(), before)
        self.assertFalse(list_backups(self.db))

    def test_cancel_after_deletes_rolls_back_and_keeps_recovery(self):
        saved = backup(self.db)
        self.db.save([game('GOG', '2', 'Later', {})])
        before = self.db.rows()
        real_backup = backup
        restoring = False
        calls = 0
        def checked_backup(*args, **kwargs):
            nonlocal restoring
            result = real_backup(*args, **kwargs)
            restoring = True
            return result
        def check():
            nonlocal calls
            if restoring:
                calls += 1
                if calls == 3:
                    raise Cancelled()
        with patch('database_backups.backup', checked_backup):
            with self.assertRaises(Cancelled):
                restore(self.db, saved, check)
        self.assertEqual(self.db.rows(), before)
        self.assertTrue(any(p.name.startswith('recovery-') for p in list_backups(self.db)))

    def test_cancel_snapshot_leaves_no_partial_file(self):
        def check():
            raise Cancelled()
        with self.assertRaises(Cancelled):
            backup(self.db, check=check)
        self.assertFalse(list_backups(self.db))

    def test_background_task_outcomes_and_daily_baseline(self):
        import threading
        from local_tasks import LocalTask
        daily = ensure_daily(self.db)
        self.assertTrue(daily.exists())
        self.assertIsNone(ensure_daily(self.db))
        worker = LocalTask('backup', self.db, threading.Event())
        worker.run()
        self.assertEqual(worker.outcome, 'backup')
        saved = worker.value
        self.db.save([game('GOG', '2', 'Later', {})])
        worker = LocalTask('restore', self.db, threading.Event(), path=saved)
        worker.run()
        self.assertEqual(worker.outcome, 'restore')
        self.assertEqual(len(self.db.rows()), 1)
