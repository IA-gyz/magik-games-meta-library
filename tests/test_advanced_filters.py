import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from advanced_filters import normalize, matches, active_count
from browsing_state import normalize_snapshot


class AdvancedFilterTests(unittest.TestCase):
    def test_missing_known_minimum_including_zero(self):
        for mode, values in [('Missing', [(None, True), (0, False)]), ('Known', [(None, False), (0, True)]), ('Minimum', [(None, False), (0, False), (80, True)])]:
            filters = {'scores': {'oc_score': {'mode': mode, 'minimum': 80}}}
            for value, expected in values:
                self.assertEqual(matches({'oc_score': value}, filters), expected)
        self.assertFalse(matches({'oc_score': float('nan')}, {'scores': {'oc_score': {'mode': 'Known'}}}))
        self.assertTrue(matches({}, {}))

    def test_players_and_coop_are_distinct_and_combine(self):
        row = {'igdb_local_players': 4, 'igdb_local_coop': 2}
        self.assertTrue(matches(row, {'local_players': 4}))
        self.assertFalse(matches(row, {'local_coop': 4}))
        self.assertFalse(matches({}, {'local_players': 2}))
        self.assertTrue(matches(row, {'local_players': 4, 'local_coop': 2}))

    def test_proton_or_tiers_and_unrated(self):
        filters = {'tiers': ['gold', 'platinum']}
        self.assertTrue(matches({'proton_tier': 'Gold'}, filters))
        self.assertFalse(matches({'proton_tier': 'silver'}, filters))
        self.assertFalse(matches({}, filters))
        self.assertTrue(matches({}, {'tiers': ['unrated']}))
        self.assertFalse(matches({'proton_tier': 'native'}, {'tiers': ['unrated']}))

    def test_validation_presets_and_active_count(self):
        filters = {'scores': {'mc_user_score': {'mode': 'Minimum', 'minimum': 900}, 'oc_score': {'mode': 'Missing'}}, 'local_coop': 4, 'tiers': ['gold', 'invalid']}
        state = normalize_snapshot({'filters': {'advanced': filters}}, 100)
        advanced = state['filters']['advanced']
        self.assertEqual(advanced['scores']['mc_user_score']['minimum'], 10)
        self.assertEqual(advanced['tiers'], ['gold'])
        self.assertEqual(active_count(advanced), 4)
        self.assertEqual(active_count(normalize_snapshot({}, 100)['filters']['advanced']), 0)
        self.assertEqual(normalize({'local_players': True, 'scores': []})['local_players'], 0)

    def test_dialog_round_trip_and_reset(self):
        from PySide6.QtWidgets import QApplication, QDialogButtonBox
        from advanced_filters import create_dialog
        app = QApplication.instance() or QApplication([])
        value = {'local_coop': 4, 'tiers': ['gold'], 'scores': {'oc_score': {'mode': 'Minimum', 'minimum': 80}}}
        dialog = create_dialog(value)
        self.assertEqual(dialog.values(), normalize(value))
        buttons = dialog.findChild(QDialogButtonBox)
        buttons.button(QDialogButtonBox.Reset).click()
        self.assertEqual(active_count(dialog.values()), 0)
        dialog.close()
        app.processEvents()
