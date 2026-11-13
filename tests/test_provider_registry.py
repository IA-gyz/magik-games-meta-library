import sys, threading, unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import connectors
from connector_io import ConnectorIO, FetchError
from provider_registry import PROVIDERS, provider, selected_providers, launch_supported
from core import STORES
from providers import steam as steam_provider


class ProviderRegistryTests(unittest.TestCase):
    def test_order_capabilities_and_public_dispatch_stay_compatible(self):
        self.assertEqual(STORES, ["Steam", "GOG", "Epic", "Amazon", "EA", "Rockstar"])
        self.assertEqual(list(connectors.FETCHERS), STORES)
        self.assertIs(connectors.FetchError, FetchError)
        for spec in PROVIDERS:
            self.assertIs(
                connectors.FETCHERS[spec.name], getattr(connectors, spec.fetch_function)
            )
        self.assertEqual(
            [spec.name for spec in PROVIDERS if spec.metadata_function],
            ["Steam", "GOG", "Epic"],
        )

    def test_disabled_provider_is_not_selected_even_with_saved_enable_flag(self):
        options = {"enabled_" + name: True for name in STORES}
        self.assertEqual(
            [spec.name for spec in selected_providers(options)], STORES[:-1]
        )
        self.assertFalse(launch_supported("Rockstar"))
        self.assertFalse(launch_supported("unknown"))
        self.assertTrue(launch_supported("EA"))
        self.assertFalse(provider("Rockstar").complete_library)

    def test_config_keys_and_kinds_remain_stable(self):
        expected = {
            "Steam": ["steam_id", "steam_key", "steam_licenses_html"],
            "GOG": ["gog_auth"],
            "Epic": ["epic_exe", "epic_config", "epic_heroic_root"],
            "Amazon": ["amazon_exe", "amazon_config"],
            "EA": ["ea_auth", "ea_token"],
            "Rockstar": ["rockstar_log"],
        }
        self.assertEqual(
            {
                spec.name: [field[0] for field in spec.source_fields]
                for spec in PROVIDERS
            },
            expected,
        )
        self.assertTrue(
            all(
                kind in ["text", "secret", "file", "dir"]
                for spec in PROVIDERS
                for _, _, kind in spec.source_fields
            )
        )

    def test_provider_uses_injected_transport_and_preserves_owned_request(self):
        request = Mock(
            return_value={
                "response": {
                    "game_count": 1,
                    "games": [
                        {"appid": 70, "name": "Half-Life", "playtime_forever": 12}
                    ],
                }
            }
        )
        io = ConnectorIO(request, Mock(), Mock())
        rows = steam_provider.steam(
            {"steam_key": "test-key", "steam_id": "76561198018049642"},
            threading.Event(),
            Mock(),
            io=io,
        )
        self.assertEqual(rows[0]["id"], "70")
        self.assertEqual(rows[0]["playtime"], 12)
        request.assert_called_once_with(
            "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/",
            {
                "key": "test-key",
                "steamid": "76561198018049642",
                "include_appinfo": 1,
                "include_played_free_games": 1,
            },
        )
        io.helper.assert_not_called()
        io.token_file.assert_not_called()

    def test_facade_transport_is_late_bound_not_captured_at_import(self):
        options = {"steam_key": "test-key", "steam_id": "76561198018049642"}
        for count in [0, 1]:
            games = [] if count == 0 else [{"appid": 1, "name": "A"}]
            with patch(
                "connectors.request",
                return_value={"response": {"game_count": count, "games": games}},
            ) as request:
                self.assertEqual(
                    len(connectors.steam(options, threading.Event(), Mock())), count
                )
                request.assert_called_once()
