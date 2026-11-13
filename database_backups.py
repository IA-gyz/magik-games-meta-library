"""Consistent SQLite snapshots and transactional, data-only restore."""
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

TABLES = {
    'games': ('store', 'id', 'payload'),
    'status': ('store', 'payload'),
    'metadata_results': ('store', 'id', 'payload'),
    'local_state': ('name', 'payload'),
}
LIMITS = {'daily': 7, 'manual': 5, 'recovery': 3}
PATTERN = re.compile(r'^(daily|manual|recovery)-\d{8}-\d{12}\.sqlite3$')


def directory(db):
    return db.path.parent / 'backups'


def list_backups(db):
    folder = directory(db)
    if not folder.exists():
        return []
    return sorted((p for p in folder.iterdir() if PATTERN.fullmatch(p.name) and p.is_file() and not p.is_symlink()), key=lambda p: p.name.split('-', 1)[1], reverse=True)


def backup(db, kind='manual', check=lambda: None):
    if kind not in LIMITS:
        raise ValueError('Unknown backup type.')
    check()
    folder = directory(db)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    stamp = datetime.now().astimezone().strftime('%Y%m%d-%H%M%S%f')
    target = folder / f'{kind}-{stamp}.sqlite3'
    handle, name = tempfile.mkstemp(prefix='.snapshot-', suffix='.sqlite3', dir=folder)
    os.close(handle)
    temporary = Path(name)
    try:
        with db.connect() as source, sqlite3.connect(temporary) as destination:
            source.backup(destination, pages=256, progress=lambda *args: check(), sleep=0.05)
            if destination.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('The backup did not pass its integrity check.')
        check()
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        temporary.replace(target)
        # Only prune recognized snapshots of this category, after publishing a new one.
        previous = [p for p in list_backups(db) if p.name.startswith(kind + '-')]
        for old in previous[LIMITS[kind]:]:
            try:
                old.unlink()
            except OSError:
                pass  # Keep extra older snapshots if cleanup is not writable.
        return target
    finally:
        temporary.unlink(missing_ok=True)


def ensure_daily(db, check=lambda: None):
    today = datetime.now().astimezone().strftime('%Y%m%d')
    if any(p.name.startswith('daily-' + today + '-') for p in list_backups(db)):
        return None
    with db.connect() as connection:
        if not connection.execute('SELECT 1 FROM games LIMIT 1').fetchone():
            return None
    return backup(db, 'daily', check)


def read_snapshot(path, check=lambda: None):
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError('The selected backup exceeds the 512 MiB restore limit.')
    try:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as source:
            source.execute('PRAGMA query_only=ON')
            source.execute('BEGIN')
            source.set_progress_handler(lambda: 1 if _cancelled(check) else 0, 10000)
            if source.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('The selected backup is damaged.')
            values = {}
            for table, columns in TABLES.items():
                check()
                schema = source.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
                names = tuple(r[1] for r in source.execute(f'PRAGMA table_info({table})'))
                if schema != ('table',) or names != columns:
                    raise ValueError('This file is not a compatible Magik Games Library database.')
                records = source.execute(f'SELECT {",".join(columns)} FROM {table}').fetchall()
                for record in records:
                    check()
                    payload = json.loads(record[-1])
                    if table != 'local_state' and not isinstance(payload, dict):
                        raise ValueError('The backup contains an invalid record.')
                    if table == 'games':
                        from catalog_import import validate_import_row
                        from catalog_data import STORES
                        try:
                            validate_import_row(payload, 1)
                            if payload.get('store') not in STORES:
                                raise ValueError()
                        except ValueError as exc:
                            raise ValueError('The selected backup contains invalid game data.') from exc
                    if table == 'games' and (str(payload.get('id')) != record[1] or payload.get('store') != record[0] or not isinstance(payload.get('title'), str) or not isinstance(payload.get('raw'), dict)):
                        raise ValueError('The backup contains an invalid game identity.')
                values[table] = records
            return values
    except (sqlite3.Error, json.JSONDecodeError, TypeError) as exc:
        check()
        raise ValueError('The file is damaged or is not a compatible Magik Games Library backup.') from exc


def _cancelled(check):
    try:
        check()
        return False
    except Exception:
        return True


def restore(db, path, check=lambda: None):
    # Validate everything before writing or creating a recovery snapshot.
    values = read_snapshot(path, check)
    check()
    with db.connect() as destination:
        destination.execute('BEGIN IMMEDIATE')
        # Holding the writer lock prevents intervening edits between recovery and restore.
        recovery = backup(db, 'recovery', check)
        for table, columns in TABLES.items():
            check()
            destination.execute(f'DELETE FROM {table}')
            destination.executemany(f'INSERT INTO {table} VALUES ({",".join("?" for _ in columns)})', values[table])
        check()
    return recovery
