import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metacritic import parse_page, run_metacritic
from connectors import FetchError
from storage import Database
from core import game
from catalog_import import import_saved_library


def page(title="Portal 2", platform="PC", score=95, user_platform="pc"):
    product = dict(
        title=title,
        slug="portal-2",
        production={},
        rating="E10+",
        genres=[{"name": "Puzzle"}],
        platforms=[
            dict(
                name=platform,
                releaseDate="2011-04-18",
                criticScoreSummary=dict(
                    score=score, reviewCount=52, sentiment="Universal acclaim"
                ),
            )
        ],
    )
    summary = dict(
        max=10,
        score=9.1,
        reviewCount=400,
        url="/game/portal-2/user-reviews/?platform=" + user_platform,
    )
    values = []

    def encode(value):
        index = len(values)
        values.append(None)
        values[index] = (
            {k: encode(v) for k, v in value.items()}
            if isinstance(value, dict)
            else [encode(v) for v in value]
            if isinstance(value, list)
            else value
        )
        return index

    encode([product, summary])
    return (
        '<script type="application/json" id="__NUXT_DATA__">'
        + json.dumps(values)
        + "</script>"
    )


class MetacriticTests(unittest.TestCase):
    def test_pc_score_and_zero_are_valid(self):
        data = parse_page(page(score=0), "Portal 2", "portal-2")
        self.assertEqual(data["score"], 0)
        self.assertEqual(data["mc_user_score"], 9.1)
        self.assertEqual(data["mc_critic_count"], 52)

    def test_console_user_summary_never_used(self):
        self.assertNotIn(
            "mc_user_score",
            parse_page(page(user_platform="xbox-360"), "Portal 2", "portal-2"),
        )
        with self.assertRaises(ValueError):
            parse_page(page(platform="Xbox 360"), "Portal 2", "portal-2")

    def test_wrong_title_edition_and_year_rejected(self):
        for title in ("Portal", "Portal 2 Deluxe Edition"):
            with self.assertRaises(ValueError):
                parse_page(page(), title, "portal-2")
        with self.assertRaises(ValueError):
            parse_page(page(), "Portal 2", "portal-2", "2024-01-01")

    def test_direct_score_survives_refresh_and_export_import(self):
        with tempfile.TemporaryDirectory() as root:
            db = Database(Path(root) / "games.sqlite")
            db.save([game("Steam", "620", "Portal 2", {}, score=90)])
            cancel = threading.Event()
            cancel.wait = lambda seconds: False
            calls = []

            def fetch(url):
                calls.append(url)
                return page()

            run_metacritic(db, cancel, lambda _: None, lambda: None, fetch)
            self.assertEqual(len(calls), 1)
            self.assertEqual(db.rows()[0]["score"], 95)
            db.save([game("Steam", "620", "Portal 2", {}, score=80)])
            self.assertEqual(db.rows()[0]["score"], 95)
            imported = import_saved_library({"games": db.rows()})
            self.assertEqual(imported[0]["mc_user_score"], 9.1)
            run_metacritic(db, cancel, lambda _: None, lambda: None, fetch)
            self.assertEqual(len(calls), 1)

    def test_access_refusal_pauses_and_keeps_scores(self):
        with tempfile.TemporaryDirectory() as root:
            db = Database(Path(root) / "games.sqlite")
            db.save([game("Steam", "620", "Portal 2", {}, score=90)])
            cancel = threading.Event()
            calls = []

            def fetch(url):
                calls.append(url)
                raise FetchError("Metacritic returned HTTP 403", status=403)

            run_metacritic(db, cancel, lambda _: None, lambda: None, fetch)
            run_metacritic(db, cancel, lambda _: None, lambda: None, fetch)
            self.assertEqual(len(calls), 1)
            self.assertEqual(db.rows()[0]["score"], 90)
