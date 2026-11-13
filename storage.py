"""SQLite persistence and transactions; catalog normalization lives separately."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from catalog_data import clean, account_added
from personal_library import annotations


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS games (store TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(store,id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS status (store TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS metadata_results (store TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(store,id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS local_state (name TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
        os.chmod(self.path, 0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def installations(self):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM local_state WHERE name='installations'"
            ).fetchone()
            return json.loads(row[0]) if row else {}

    def save_installations(self, snapshot):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO local_state VALUES (?,?)",
                ("installations", json.dumps(snapshot, ensure_ascii=False)),
            )

    def save_acquisition_report(self, store, report):
        with self.connect() as db:
            self._write_acquisition_report(db, store, report)

    def _write_acquisition_report(self, db, store, report, timestamp=None):
        payload = {
            **report,
            "time": timestamp
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        db.execute(
            "INSERT OR REPLACE INTO local_state VALUES (?,?)",
            ("acquisition|" + store, json.dumps(payload)),
        )

    def acquisition_reports(self):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM local_state WHERE name LIKE 'acquisition|%'"
                )
            ]

    def rows(self):
        with self.connect() as db:
            return self.decode_rows(db.execute("SELECT payload FROM games").fetchall())

    @staticmethod
    def decode_rows(payloads):
        rows = [json.loads(r[0]) for r in payloads]
        for row in rows:
            row.update(annotations(row))
            if not row.get("date_added") and row.get("date_added_source") != "Manual":
                row["date_added"], row["date_added_source"] = account_added(
                    row["store"], row.get("raw") or {}
                )
        return rows

    def view_snapshot(self):
        # One read transaction keeps games, installations and status from the same snapshot.
        with self.connect() as db:
            db.execute("BEGIN")
            payloads = db.execute("SELECT payload FROM games").fetchall()
            record = db.execute(
                "SELECT payload FROM local_state WHERE name='installations'"
            ).fetchone()
            statuses = dict(
                (key, json.loads(value))
                for key, value in db.execute("SELECT store,payload FROM status")
            )
            snapshot = json.loads(record[0]) if record else {}
        return self.decode_rows(payloads), snapshot, statuses

    def report_snapshot(self, kind):
        with self.connect() as db:
            db.execute("BEGIN")
            if kind == "installations":
                records = db.execute(
                    "SELECT payload FROM local_state WHERE name='installations'"
                ).fetchall()
            elif kind == "acquisition":
                records = db.execute(
                    "SELECT payload FROM local_state WHERE name LIKE 'acquisition|%'"
                ).fetchall()
            elif kind == "metadata":
                records = db.execute(
                    "SELECT payload FROM metadata_results ORDER BY store,id"
                ).fetchall()
                games = db.execute("SELECT payload FROM games").fetchall()
            else:
                raise ValueError("Unknown report type")
        # Decode after releasing the read transaction so manual edits do not wait on formatting.
        values = [json.loads(row[0]) for row in records]
        if kind == "installations":
            return values[0] if values else {}
        if kind == "acquisition":
            return values
        titles = []
        for row in games:
            game = json.loads(row[0])
            titles.append({key: game[key] for key in ("store", "id", "title")})
        return values, titles

    def save(self, rows, store=None, complete=False, before_commit=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._write_rows(db, rows, store, complete)
            if before_commit:
                before_commit()

    def _write_rows(self, db, rows, store=None, complete=False):
        # Reconcile only after a complete successful account response; keep cached rows.
        if complete and store:
            for ident, payload in db.execute(
                "SELECT id,payload FROM games WHERE store=?", (store,)
            ).fetchall():
                old = json.loads(payload)
                old["active"] = False
                db.execute(
                    "UPDATE games SET payload=? WHERE store=? AND id=?",
                    (json.dumps(old), store, ident),
                )
        for row in rows:
            previous = db.execute(
                "SELECT payload FROM games WHERE store=? AND id=?",
                (row["store"], row["id"]),
            ).fetchone()
            if previous:
                old = json.loads(previous[0])
                # Preserve rich metadata on routine library refreshes.
                incoming = {k: v for k, v in row.items() if v is not None and v != ""}
                incoming["raw"] = {**old.get("raw", {}), **row.get("raw", {})}
                if (
                    row["store"] == "GOG"
                    and row["title"] == f"GOG product {row['id']}"
                    and old.get("title")
                ):
                    incoming.pop("title", None)
                if (
                    row["store"] == "GOG"
                    and old.get("raw", {}).get("product")
                    and not row.get("raw", {}).get("product")
                ):
                    for key in [
                        "type",
                        "genres",
                        "release",
                        "platforms",
                        "languages",
                        "cover",
                        "url",
                        "source",
                    ]:
                        if old.get(key):
                            incoming.pop(key, None)
                if (
                    row["store"] == "Steam"
                    and old.get("raw", {}).get("store_details")
                    and "store_details" not in row.get("raw", {})
                ):
                    incoming.pop("type", None)
                if (
                    row["store"] == "Epic"
                    and old.get("raw", {}).get("epic_enrichment")
                    and not row.get("raw", {}).get("epic_enrichment")
                ):
                    for key in [
                        "genres",
                        "developers",
                        "publishers",
                        "release",
                        "platforms",
                        "languages",
                        "description",
                        "cover",
                        "url",
                        "source",
                    ]:
                        if old.get(key):
                            incoming.pop(key, None)
                if old.get("date_added_source") == "Manual":
                    incoming.pop("date_added", None)
                    incoming.pop("date_added_source", None)
                direct = incoming["raw"].get("metacritic", {}).get("data", {})
                if direct.get("score") is not None:
                    incoming["score"] = direct["score"]
                old.update(incoming)
                row = old
            db.execute(
                "INSERT OR REPLACE INTO games VALUES (?,?,?)",
                (row["store"], row["id"], json.dumps(clean(row), ensure_ascii=False)),
            )

    def set_manual_date(self, store, ident, value):
        """Update a date explicitly, including clearing it, against the latest record."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute(
                "SELECT payload FROM games WHERE store=? AND id=?", (store, ident)
            ).fetchone()
            if not result:
                return False
            record = json.loads(result[0])
            record.update(date_added=value, date_added_source="Manual")
            db.execute(
                "UPDATE games SET payload=? WHERE store=? AND id=?",
                (json.dumps(record, ensure_ascii=False), store, ident),
            )
        return True

    def metadata_result(self, row, outcome, reason, retry_after=None):
        payload = dict(
            store=row["store"],
            id=row["id"],
            title=row["title"],
            outcome=outcome,
            reason=reason,
            retry_after=retry_after,
            time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO metadata_results VALUES (?,?,?)",
                (row["store"], row["id"], json.dumps(payload, ensure_ascii=False)),
            )

    def metadata_results(self):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT payload FROM metadata_results ORDER BY store,id"
                )
            ]

    def status(self, store, message, count=None, severity="info"):
        with self.connect() as db:
            self._write_status(db, store, message, count, severity)

    def _write_status(
        self, db, store, message, count=None, severity="info", timestamp=None
    ):
        payload = dict(
            message=message,
            count=count,
            severity=severity,
            time=timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        db.execute(
            "INSERT OR REPLACE INTO status VALUES (?,?)", (store, json.dumps(payload))
        )

    def save_refresh(
        self,
        store,
        rows,
        report,
        message,
        severity="info",
        complete=True,
        before_commit=None,
    ):
        """Commit one authoritative source result, or roll back every part of it."""
        if any(row.get("store") != store for row in rows):
            raise ValueError("Refresh rows must belong to the selected store")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connect() as db:
            # Acquire the write lock before reading old payloads for merge/reconciliation.
            db.execute("BEGIN IMMEDIATE")
            self._write_rows(db, rows, store, complete)
            if report is not None:
                self._write_acquisition_report(db, store, report, timestamp)
            self._write_status(db, store, message, len(rows), severity, timestamp)
            if before_commit is not None:
                before_commit()

    def statuses(self):
        with self.connect() as db:
            return dict(
                (k, json.loads(v))
                for k, v in db.execute("SELECT store,payload FROM status")
            )
