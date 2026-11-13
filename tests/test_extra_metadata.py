import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extra_metadata import Clients, run_extra, exact_match, steam_id
from extra_schema import SOURCES
from connector_io import FetchError, Cancelled
from core import game
from storage import Database
from catalog_import import import_saved_library


class FastCancel(threading.Event):
    def wait(self, seconds=None):
        return self.is_set()


def options(*sources):
    return {"metadata_" + s: s in sources for s in SOURCES}


class ExtraTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "games.db")
        self.cancel = FastCancel()

    def run_source(self, settings, call):
        return run_extra(
            self.db, settings, self.cancel, lambda _: None, lambda: None, call
        )

    def test_exact_matching_rejects_ambiguity_editions_console_and_year(self):
        row = game("Steam", "620", "Portal 2", {}, release="2011-04-19")
        for items in (
            [{"name": "Portal 2 Deluxe"}],
            [{"name": "Portal 2"}, {"name": "Portal 2"}],
            [{"name": "Portal 2", "platforms": [48]}],
            [{"name": "Portal 2", "platforms": [6], "firstReleaseDate": "2024-01-01"}],
        ):
            with self.assertRaises(ValueError):
                exact_match(items, row, pc=True)

    def test_proton_exact_id_cache_and_import(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])
        calls = []

        def call(url, **kwargs):
            calls.append(url)
            return {
                "tier": "platinum",
                "trendingTier": "gold",
                "confidence": "strong",
                "total": 349,
            }

        self.run_source(options("ProtonDB"), call)
        self.run_source(options("ProtonDB"), call)
        self.assertEqual(
            calls, ["https://www.protondb.com/api/v1/reports/summaries/620.json"]
        )
        row = self.db.rows()[0]
        self.assertEqual(row["proton_reports"], 349)
        self.assertEqual(
            import_saved_library({"games": [row]})[0]["proton_tier"], "platinum"
        )

    def test_proton_nonsteam_never_guesses(self):
        row = game("GOG", "1", "Portal 2", {})
        self.db.save([row])
        calls = []
        self.run_source(options("ProtonDB"), lambda *a, **k: calls.append(a))
        self.assertFalse(calls)
        row["raw"] = {
            "extra_metadata": {
                "IGDB": {"steam_id": "620", "matched_title": "Another Game"}
            }
        }
        self.assertIsNone(steam_id(row))

    def test_missing_credentials_make_no_calls(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])
        calls = []
        events = self.run_source(
            options("IGDB", "SteamGridDB", "OpenCritic"),
            lambda *a, **k: calls.append(a),
        )
        self.assertEqual(len(events), 3)
        self.assertFalse(calls)

    def test_igdb_token_renewal_and_pc_counts(self):
        counts = {"tokens": 0, "games": 0}

        def call(url, **kwargs):
            if "oauth2" in url:
                counts["tokens"] += 1
                self.assertNotIn("secret", url)
                return {
                    "access_token": "token" + str(counts["tokens"]),
                    "expires_in": 3600,
                }
            counts["games"] += 1
            if counts["games"] == 1:
                raise FetchError("HTTP 401", status=401)
            self.assertIn('search "Portal 2";', kwargs["data"].decode())
            return [
                {
                    "id": 2,
                    "name": "Portal 2",
                    "platforms": [6],
                    "rating": 92,
                    "url": "https://www.igdb.com/games/portal-2",
                    "multiplayer_modes": [
                        {"platform": 48, "offlinemax": 4},
                        {"platform": 6, "offlinemax": 2, "offlinecoopmax": 2},
                    ],
                    "external_games": [
                        {"uid": "620", "external_game_source": {"name": "Steam"}}
                    ],
                }
            ]

        client = Clients(
            {"igdb_client_id": "id", "igdb_client_secret": "secret"}, self.cancel, call
        )
        data, meta = client.igdb(game("Steam", "620", "Portal 2", {}))
        self.assertEqual(counts["tokens"], 2)
        self.assertEqual(data["igdb_local_coop"], 2)
        self.assertEqual(meta["steam_id"], "620")
        self.assertNotIn("token", str(data) + str(meta))

    def test_igdb_stops_after_second_401(self):
        calls = []

        def call(url, **kwargs):
            calls.append(url)
            if "oauth2" in url:
                return {"access_token": "secret", "expires_in": 3600}
            raise FetchError("HTTP 401", status=401)

        with self.assertRaises(FetchError):
            Clients(
                {"igdb_client_id": "id", "igdb_client_secret": "secret"},
                self.cancel,
                call,
            ).igdb(game("Steam", "620", "Portal 2", {}))
        self.assertEqual(len(calls), 4)

    def test_opencritic_fields_are_separate_and_scoped(self):
        self.db.save([game("Steam", "620", "Portal 2", {}, score=95)])
        settings = {**options("OpenCritic"), "opencritic_api_key": "secret"}

        def call(url, **kwargs):
            self.assertEqual(kwargs["headers"]["X-RapidAPI-Key"], "secret")
            if "/search?" in url:
                return [{"id": 1, "name": "Portal 2"}]
            return {
                "id": 1,
                "name": "Portal 2",
                "topCriticScore": 92.5,
                "percentRecommended": 95,
                "tier": "Mighty",
                "numReviews": 100,
            }

        self.run_source(settings, call)
        row = self.db.rows()[0]
        self.assertEqual(row["score"], 95)
        self.assertEqual(row["oc_score"], 92.5)
        self.assertIn("combined", row["opencritic_status"])
        self.assertNotIn("secret", str(row))

    def test_rate_limit_persists_and_does_not_erase_data(self):
        self.db.save([game("Steam", "620", "Portal 2", {}, oc_score=92.5)])
        settings = {**options("OpenCritic"), "opencritic_api_key": "secret"}
        calls = []

        def call(url, **kwargs):
            calls.append(url)
            raise FetchError("HTTP 429", status=429, retry_after=90000)

        self.run_source(settings, call)
        self.run_source(settings, call)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.db.rows()[0]["oc_score"], 92.5)

    def test_artwork_uses_steam_mapping_keeps_cover_and_credits(self):
        self.db.save(
            [
                game(
                    "Steam",
                    "620",
                    "Portal 2",
                    {},
                    cover="https://store.example/old.jpg",
                )
            ]
        )
        calls = []

        def call(url, **kwargs):
            calls.append(url)
            if "/games/steam/620" in url:
                return {"success": True, "data": {"id": 1, "name": "Portal 2"}}
            return {
                "success": True,
                "data": [
                    {"id": 10, "nsfw": True, "url": "https://cdn.example/excluded.jpg"},
                    {
                        "id": 11,
                        "url": "https://cdn.example/art.png",
                        "author": {
                            "name": "Artist",
                            "url": "https://www.steamgriddb.com/profile/1",
                        },
                    },
                ],
            }

        self.run_source({**options("SteamGridDB"), "sgdb_api_key": "secret"}, call)
        row = self.db.rows()[0]
        self.assertEqual(len(calls), 5)
        self.assertEqual(row["cover"], "https://store.example/old.jpg")
        self.assertEqual(row["sgdb_artists"], "Artist")
        self.assertEqual(
            row["raw"]["extra_metadata"]["SteamGridDB"]["credits"]["grid"]["id"], 11
        )

    def test_source_failure_does_not_stop_next_provider(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])

        def call(url, **kwargs):
            if "twitch" in url:
                raise FetchError("HTTP 403", status=403)
            return {"tier": "gold", "total": 1}

        self.run_source(
            {
                **options("IGDB", "ProtonDB"),
                "igdb_client_id": "id",
                "igdb_client_secret": "secret",
            },
            call,
        )
        self.assertEqual(self.db.rows()[0]["proton_tier"], "gold")

    def test_cancel_makes_no_request(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])
        self.cancel.set()
        calls = []
        with self.assertRaises(Cancelled):
            self.run_source(options("ProtonDB"), lambda *a, **k: calls.append(a))
        self.assertFalse(calls)

    def test_corrected_credentials_bypass_old_auth_failure(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])
        calls = []

        def call(url, **kwargs):
            calls.append(url)
            if kwargs["headers"]["X-RapidAPI-Key"] == "bad":
                raise FetchError("HTTP 401", status=401)
            if "/search?" in url:
                return [{"id": 1, "name": "Portal 2"}]
            return {"id": 1, "name": "Portal 2", "topCriticScore": 92}

        self.run_source({**options("OpenCritic"), "opencritic_api_key": "bad"}, call)
        self.run_source({**options("OpenCritic"), "opencritic_api_key": "good"}, call)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.db.rows()[0]["oc_score"], 92)

    def test_new_igdb_mapping_rechecks_cached_missing_proton_id(self):
        self.db.save([game("GOG", "1", "Portal 2", {})])
        calls = []

        def call(url, **kwargs):
            calls.append(url)
            return {"tier": "gold", "total": 1}

        self.run_source(options("ProtonDB"), call)
        row = self.db.rows()[0]
        row["raw"]["extra_metadata"]["IGDB"] = {
            "steam_id": "620",
            "matched_title": "Portal 2",
        }
        self.db.save([row])
        self.run_source(options("ProtonDB"), call)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.db.rows()[0]["proton_tier"], "gold")

    def test_settings_fields_and_reveal_controls(self):
        from PySide6.QtWidgets import QApplication, QTabWidget, QLineEdit
        from source_dialog import Sources

        q = QApplication.instance() or QApplication([])
        dialog = Sources({"sgdb_api_key": "saved"})
        tabs = dialog.findChild(QTabWidget)
        self.assertTrue(
            set(SOURCES).issubset({tabs.tabText(i) for i in range(tabs.count())})
        )
        self.assertEqual(dialog.fields["sgdb_api_key"].echoMode(), QLineEdit.Password)
        self.assertEqual(dialog.values()["sgdb_api_key"], "saved")
        self.assertTrue(dialog.values()["metadata_ProtonDB"])
        dialog.close()
