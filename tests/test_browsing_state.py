import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browsing_state import normalize_snapshot, normalize_presets


class BrowsingStateTests(unittest.TestCase):
    def test_valid_roundtrip_is_independent(self):
        original = {
            "filters": {
                "search": "alpha",
                "store": ["Steam", "GOG"],
                "score": 80,
                "played": "Played",
                "current": True,
            },
            "sort_key": 3,
            "descending": True,
            "view": 1,
        }
        before = deepcopy(original)
        result = normalize_snapshot(original, 21)
        self.assertEqual(normalize_snapshot(result, 21), result)
        self.assertEqual(original, before)
        result["filters"]["store"].append("Epic")
        self.assertEqual(original, before)

    def test_untrusted_json_shapes(self):
        for value in [
            None,
            False,
            7,
            "text",
            [],
            {"filters": None},
            {
                "filters": {
                    "played": [],
                    "search": {},
                    "score": float("inf"),
                    "store": [{}, [], None, True],
                }
            },
        ]:
            result = normalize_snapshot(value, 21)
            self.assertEqual(result["filters"]["score"], 0)
            self.assertEqual(result["filters"]["store"], [])
            self.assertEqual(result["filters"]["played"], "All")

    def test_bounds_and_strict_flags(self):
        result = normalize_snapshot(
            {
                "filters": {"score": 120, "current": "false"},
                "sort_key": 100,
                "descending": "false",
                "view": True,
            },
            21,
        )
        self.assertEqual(result["sort_key"], 20)
        self.assertEqual(result["filters"]["score"], 100)
        self.assertFalse(result["descending"])
        self.assertFalse(result["filters"]["current"])
        self.assertEqual(result["view"], 0)
        self.assertEqual(
            normalize_snapshot({"sort_key": -5, "filters": {"score": -5}}, 21)[
                "sort_key"
            ],
            0,
        )

    def test_facets_and_presets(self):
        result = normalize_presets(
            {
                "Good": {
                    "filters": {"store": "Steam", "genres": ["RPG", "RPG", 4, ""]}
                },
                "Bad": None,
                " ": {},
            },
            21,
        )
        self.assertEqual(list(result), ["Good"])
        self.assertEqual(result["Good"]["filters"]["store"], ["Steam"])
        self.assertEqual(result["Good"]["filters"]["genres"], ["RPG"])
        self.assertEqual(normalize_presets([], 21), {})
