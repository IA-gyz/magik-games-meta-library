import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from configuration import (
    normalize_options,
    normalize_links,
    normalize_overrides,
    override_values,
)
from launch_commands import override_command
from installations import LaunchError


class ConfigurationTests(unittest.TestCase):
    def test_options_keep_valid_values_and_unknown_extensions(self):
        source = {
            "steam_key": " secret ",
            "ea_token": "token",
            "enabled_Steam": True,
            "enabled_Rockstar": True,
            "extension": {"a": [1]},
        }
        before = deepcopy(source)
        result = normalize_options(source)
        self.assertEqual(result["steam_key"], " secret ")
        self.assertEqual(result["ea_token"], "token")
        self.assertTrue(result["enabled_Steam"])
        self.assertFalse(result["enabled_Rockstar"])
        result["extension"]["a"].append(2)
        self.assertEqual(source, before)

    def test_bad_options_are_not_stringified_or_truthy(self):
        result = normalize_options(
            {
                "steam_id": 123,
                "ea_token": None,
                "scan_prefix_roots": [],
                "enabled_Steam": "false",
                "ea_session_enabled": 1,
            }
        )
        self.assertNotIn("steam_id", result)
        self.assertNotIn("ea_token", result)
        self.assertNotIn("scan_prefix_roots", result)
        self.assertFalse(result["enabled_Steam"])
        self.assertFalse(result["ea_session_enabled"])
        for value in [None, [], 1, "text"]:
            self.assertEqual(normalize_options(value), {"enabled_Rockstar": False})

    def test_links_require_strings(self):
        self.assertEqual(
            normalize_links({"Steam|1": "record", "Steam|2": [], "": "bad"}),
            {"Steam|1": "record"},
        )
        self.assertEqual(normalize_links(None), {})

    def test_unmounted_launch_config_remains_editable(self):
        value = {
            "program": "/unmounted/script",
            "args": ["a b", "$(literal)"],
            "cwd": "/unmounted/path",
            "env": {"WINEPREFIX": "/some prefix"},
        }
        before = deepcopy(value)
        result = normalize_overrides(
            {"EA|1": value, "bad": [], "other": {"program": "x", "args": False}}
        )
        self.assertEqual(result, {"EA|1": value})
        result["EA|1"]["args"].append("x")
        self.assertEqual(value, before)

    def test_invalid_override_is_reported_as_launch_error(self):
        for value in [
            None,
            [],
            {"program": "x\0y"},
            {"program": "x", "cwd": []},
            {"program": "x", "env": {"A=B": "x"}},
            {"program": "x", "args": [1]},
        ]:
            with self.assertRaises(ValueError):
                override_values(value)
            with self.assertRaises(LaunchError):
                override_command(value)
