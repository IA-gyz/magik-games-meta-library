import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extra_metadata import run_extra, HLTB_BASE, HLTB_SEARCH_PATHS, HLTB_USER_AGENT
from connector_io import FetchError
from core import game
from storage import Database
from catalog_import import import_saved_library
from test_extra_metadata import FastCancel, options


def hltb_item(
    name="Portal 2",
    ident=123,
    game_type="game",
    platform="PC (Microsoft Windows), PlayStation 3",
    release="Apr 19, 2011",
    main=14400,
    plus=28800,
    comp100=43200,
    comp_all=30000,
):
    return {
        "game_id": ident,
        "game_name": name,
        "game_type": game_type,
        "profile_platform": platform,
        "release_world": release,
        "comp_main": main,
        "comp_plus": plus,
        "comp_100": comp100,
        "comp_all": comp_all,
    }


def page(items, page_number=1, total=1):
    return {
        "count": len(items) * total,
        "pageCurrent": page_number,
        "pageTotal": total,
        "pageSize": 20,
        "data": items,
    }


def make_call(pages, init_fail_paths=(), search_plan=None):
    """Fake transport. pages: list of search responses by page. search_plan: optional callable(attempt, payload) -> response or exception."""
    state = {"inits": [], "searches": [], "payloads": [], "attempt": 0}

    def call(url, **kwargs):
        if "/init" in url:
            state["inits"].append(url)
            for bad in init_fail_paths:
                if bad in url:
                    raise FetchError("HTTP 404", status=404)
            token = "tok%d" % (len(state["inits"]))
            return {"token": token, "hpKey": "hp-key", "hpVal": "hp-val"}
        payload = json.loads(kwargs["data"].decode())
        state["searches"].append(url)
        state["payloads"].append(payload)
        state["attempt"] += 1
        if search_plan is not None:
            outcome = search_plan(state["attempt"], payload)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return pages[payload["searchPage"] - 1]

    return call, state


class HLTBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "games.db")
        self.cancel = FastCancel()

    def run_hltb(self, call, rows=None):
        return run_extra(
            self.db, options("HLTB"), self.cancel, lambda _: None, lambda: None, call, rows=rows
        )

    def test_saves_hours_url_and_state_without_credentials(self):
        self.db.save([game("Steam", "620", "Portal 2", {}, release="2011-04-19")])
        call, state = make_call([page([hltb_item()])])
        events = self.run_hltb(call)
        self.assertTrue(any("1 saved" in str(e) for e in events))
        row = self.db.rows()[0]
        self.assertEqual(row["hltb_main"], 4.0)
        self.assertEqual(row["hltb_main_extra"], 8.0)
        self.assertEqual(row["hltb_completionist"], 12.0)
        self.assertEqual(row["hltb_all_styles"], 8.33)
        self.assertEqual(row["hltb_url"], HLTB_BASE + "/game/123")
        self.assertEqual(row["hltb_status"], "Saved")
        self.assertTrue(row["hltb_checked"])
        state_entry = row["raw"]["extra_metadata"]["HLTB"]
        self.assertEqual(state_entry["id"], 123)
        self.assertEqual(state_entry["outcome"], "Saved")
        # One token request, one search request.
        self.assertEqual(len(state["inits"]), 1)
        self.assertEqual(len(state["searches"]), 1)
        self.assertTrue(state["inits"][0].startswith(HLTB_BASE + HLTB_SEARCH_PATHS[0].rstrip("/") + "/init?t="))
        self.assertEqual(state["searches"][0], HLTB_BASE + HLTB_SEARCH_PATHS[0])
        payload = state["payloads"][0]
        self.assertEqual(payload["searchType"], "games")
        self.assertEqual(payload["searchTerms"], ["Portal", "2"])
        self.assertEqual(payload["searchPage"], 1)
        self.assertEqual(payload["hp-key"], "hp-val")
        # Saved rows still pass import validation.
        imported = import_saved_library({"games": [row]})[0]
        self.assertEqual(imported["hltb_main"], 4.0)

    def test_request_headers_carry_shared_user_agent_and_token(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])
        seen = {}

        def call(url, **kwargs):
            if "/init" in url:
                seen["init_headers"] = kwargs["headers"]
                return {"token": "tok1", "hpKey": "hp-key", "hpVal": "hp-val"}
            seen["search_headers"] = kwargs["headers"]
            self.assertEqual(kwargs["content_type"], "application/json")
            return page([hltb_item()])

        self.run_hltb(call)
        for headers in (seen["init_headers"], seen["search_headers"]):
            self.assertEqual(headers["User-Agent"], HLTB_USER_AGENT)
            self.assertEqual(headers["Referer"], HLTB_BASE + "/")
        self.assertEqual(seen["search_headers"]["x-auth-token"], "tok1")
        self.assertEqual(seen["search_headers"]["x-hp-key"], "hp-key")
        self.assertEqual(seen["search_headers"]["x-hp-val"], "hp-val")

    def test_second_run_uses_cache_and_token(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])
        call, state = make_call([page([hltb_item()])])
        self.run_hltb(call)
        self.run_hltb(call)
        self.assertEqual(len(state["inits"]), 1)
        self.assertEqual(len(state["searches"]), 1)
        self.assertEqual(self.db.rows()[0]["hltb_status"], "Saved")

    def test_unique_exact_pc_title_match_required(self):
        for case, items in enumerate((
            [hltb_item(), hltb_item(ident=124)],  # ambiguous
            [hltb_item(name="Portal 2 Deluxe")],  # edition
            [hltb_item(platform="PlayStation 4, Xbox One")],  # no PC entry
            [hltb_item(game_type="dlc")],  # DLC entry for a game row
            [hltb_item(release="Apr 1, 2024")],  # release year differs
        )):
            db = Database(Path(self.tmp.name) / ("case%d.db" % case))
            db.save([game("Steam", "620", "Portal 2", {}, release="2011-04-19")])
            call, _ = make_call([page(items)])
            run_extra(db, options("HLTB"), self.cancel, lambda _: None, lambda: None, call)
            row = db.rows()[0]
            self.assertIsNone(row.get("hltb_main"), items)
            self.assertIn("unique exact title match", row["hltb_status"])

    def test_dlc_row_matches_dlc_entry(self):
        self.db.save([game("Epic", "dlc1", "Portal 2: The Fall", {}, type="DLC")])
        call, _ = make_call([page([hltb_item(name="Portal 2: The Fall", ident=555, game_type="dlc", release="Nov 1, 2023")])])
        self.run_hltb(call)
        row = self.db.rows()[0]
        self.assertEqual(row["hltb_main"], 4.0)
        self.assertEqual(row["hltb_url"], HLTB_BASE + "/game/555")
        self.assertEqual(row["raw"]["extra_metadata"]["HLTB"]["id"], 555)

    def test_multi_page_search_finds_match_on_later_page(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])
        pages = [page([hltb_item(name="Portal", ident=1)], page_number=1, total=2), page([hltb_item()], page_number=2, total=2)]
        call, state = make_call(pages)
        self.run_hltb(call)
        self.assertEqual(len(state["searches"]), 2)
        self.assertEqual(state["payloads"][1]["searchPage"], 2)
        self.assertEqual(self.db.rows()[0]["hltb_main"], 4.0)

    def test_token_refreshed_once_after_403(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])

        def plan(attempt, payload):
            if attempt == 1:
                return FetchError("HTTP 403", status=403)
            return page([hltb_item()])

        call, state = make_call(None, search_plan=plan)
        self.run_hltb(call)
        self.assertEqual(len(state["inits"]), 2)
        self.assertEqual(self.db.rows()[0]["hltb_main"], 4.0)

    def test_persistent_403_pauses_source_and_keeps_saved_values(self):
        self.db.save([game("Steam", "620", "Portal 2", {}, hltb_main=4.0, hltb_url=HLTB_BASE + "/game/123")])

        def plan(attempt, payload):
            return FetchError("HTTP 403", status=403)

        call, state = make_call(None, search_plan=plan)
        self.run_hltb(call)
        row = self.db.rows()[0]
        self.assertEqual(row["hltb_main"], 4.0)
        self.assertEqual(row["hltb_url"], HLTB_BASE + "/game/123")
        calls_after_first = (len(state["inits"]), len(state["searches"]))
        self.run_hltb(call)
        self.assertEqual((len(state["inits"]), len(state["searches"])), calls_after_first)
        row = self.db.rows()[0]
        self.assertEqual(row["hltb_main"], 4.0)
        self.assertEqual(row["hltb_status"], "HTTP 403")

    def test_token_endpoint_falls_back_to_next_path(self):
        self.db.save([game("Steam", "620", "Portal 2", {})])
        call, state = make_call([page([hltb_item()])], init_fail_paths=(HLTB_SEARCH_PATHS[0],))
        self.run_hltb(call)
        self.assertEqual(len(state["inits"]), 2)
        self.assertEqual(state["searches"][0], HLTB_BASE + HLTB_SEARCH_PATHS[1])
        self.assertEqual(self.db.rows()[0]["hltb_main"], 4.0)

    def test_lookup_title_override_is_searched(self):
        row = game("Steam", "620", "Portal 2", {})
        row["raw"]["metadata_matches"] = {"HLTB": "Portal Two"}
        self.db.save([row])
        call, state = make_call([page([hltb_item(name="Portal Two")])])
        self.run_hltb(call)
        self.assertEqual(state["payloads"][0]["searchTerms"], ["Portal", "Two"])
        self.assertEqual(self.db.rows()[0]["hltb_main"], 4.0)

    def test_missing_comp_values_stay_empty(self):
        item = hltb_item()
        item["comp_plus"] = None
        item["comp_all"] = None
        self.db.save([game("Steam", "620", "Portal 2", {})])
        call, _ = make_call([page([item])])
        self.run_hltb(call)
        row = self.db.rows()[0]
        self.assertEqual(row["hltb_main"], 4.0)
        self.assertIsNone(row.get("hltb_main_extra"))
        self.assertIsNone(row.get("hltb_all_styles"))


if __name__ == "__main__":
    unittest.main()
