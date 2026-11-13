"""Validated advanced filters shared by browsing and persisted presets."""
import math

SCORES = {
    'mc_user_score': ('Metacritic users (PC)', 10),
    'igdb_rating': ('IGDB users', 100),
    'igdb_critic_rating': ('IGDB critics', 100),
    'oc_score': ('OpenCritic average (all platforms)', 100),
    'oc_recommended': ('OpenCritic recommended %', 100),
}
TIERS = ('native', 'platinum', 'gold', 'silver', 'bronze', 'borked', 'unrated')


def normalize(value):
    value = value if isinstance(value, dict) else {}
    result = {'scores': {}, 'tiers': [], 'local_players': 0, 'local_coop': 0}
    scores = value.get('scores')
    scores = scores if isinstance(scores, dict) else {}
    for key, (_, maximum) in SCORES.items():
        entry = scores.get(key)
        entry = entry if isinstance(entry, dict) else {}
        minimum = entry.get('minimum', 0)
        minimum = max(0, min(maximum, minimum)) if type(minimum) in (int, float) and math.isfinite(minimum) else 0
        mode = entry.get('mode')
        result['scores'][key] = {'mode': mode if mode in ('Any', 'Known', 'Missing', 'Minimum') else 'Any', 'minimum': minimum}
    for key in ('local_players', 'local_coop'):
        number = value.get(key)
        result[key] = max(0, min(64, number)) if type(number) is int else 0
    tiers = value.get('tiers')
    if isinstance(tiers, list):
        result['tiers'] = [tier for tier in TIERS if tier in tiers]
    return result


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


def matches(row, value):
    value = normalize(value)
    for key, entry in value['scores'].items():
        known = numeric(row.get(key)) and 0 <= row[key] <= SCORES[key][1]
        mode = entry['mode']
        if mode == 'Missing' and known:
            return False
        if mode in ('Known', 'Minimum') and not known:
            return False
        if mode == 'Minimum' and row[key] < entry['minimum']:
            return False
    for key in ('local_players', 'local_coop'):
        minimum = value[key]
        actual = row.get('igdb_' + key)
        if minimum and (not numeric(actual) or actual < minimum):
            return False
    tier = str(row.get('proton_tier') or '').casefold()
    tier = tier if tier in TIERS else 'unrated'
    return not value['tiers'] or tier in value['tiers']


def active_count(value):
    value = normalize(value)
    return sum(e['mode'] != 'Any' for e in value['scores'].values()) + sum(value[k] > 0 for k in ('local_players', 'local_coop')) + bool(value['tiers'])


def create_dialog(value, parent=None):
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QFormLayout, QWidget,
                                  QHBoxLayout, QComboBox, QDoubleSpinBox, QSpinBox,
                                  QCheckBox, QDialogButtonBox)
    value = normalize(value)
    dialog = QDialog(parent)
    dialog.setWindowTitle('Advanced filters')
    layout = QVBoxLayout(dialog)
    intro = QLabel('Filter saved data only. Every active filter must match. Minimum values exclude games without that information; Missing shows those games instead.')
    intro.setWordWrap(True)
    layout.addWidget(intro)
    form = QFormLayout()
    layout.addLayout(form)
    score_widgets = {}
    for key, (label, maximum) in SCORES.items():
        group = QWidget()
        line = QHBoxLayout(group)
        line.setContentsMargins(0, 0, 0, 0)
        mode = QComboBox()
        mode.addItems(['Any', 'Known', 'Missing', 'Minimum'])
        mode.setCurrentText(value['scores'][key]['mode'])
        minimum = QDoubleSpinBox()
        minimum.setRange(0, maximum)
        minimum.setDecimals(1)
        minimum.setSuffix(' / ' + str(maximum))
        minimum.setValue(value['scores'][key]['minimum'])
        minimum.setEnabled(mode.currentText() == 'Minimum')
        mode.currentTextChanged.connect(lambda text, spin=minimum: spin.setEnabled(text == 'Minimum'))
        line.addWidget(mode)
        line.addWidget(minimum)
        form.addRow(label, group)
        score_widgets[key] = (mode, minimum)
    players = {}
    for key, label in [('local_players', 'Minimum local players (PC)'), ('local_coop', 'Minimum local co-op players (PC)')]:
        spin = QSpinBox()
        spin.setRange(0, 64)
        spin.setSpecialValueText('Any')
        spin.setValue(value[key])
        form.addRow(label, spin)
        players[key] = spin
    note = QLabel('Player counts come from IGDB. Local players includes competitive games; local co-op specifically requires cooperative play. Missing counts are not inferred from genres.')
    note.setWordWrap(True)
    layout.addWidget(note)
    layout.addWidget(QLabel('ProtonDB rating: any checked tier matches; none checked includes all.'))
    tiers = {}
    group = QHBoxLayout()
    layout.addLayout(group)
    for tier in TIERS:
        check = QCheckBox('No rating' if tier == 'unrated' else tier.title())
        check.setChecked(tier in value['tiers'])
        tiers[tier] = check
        group.addWidget(check)
    note = QLabel('ProtonDB community ratings do not guarantee compatibility. No rating includes missing or unrecognized ratings. No network requests are made here.')
    note.setWordWrap(True)
    layout.addWidget(note)
    buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel | QDialogButtonBox.Reset)
    buttons.button(QDialogButtonBox.Apply).clicked.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    def reset():
        for mode, minimum in score_widgets.values():
            mode.setCurrentText('Any')
            minimum.setValue(0)
        for spin in players.values():
            spin.setValue(0)
        for check in tiers.values():
            check.setChecked(False)
    buttons.button(QDialogButtonBox.Reset).clicked.connect(reset)
    layout.addWidget(buttons)
    dialog.values = lambda: normalize({
        'scores': {key: {'mode': mode.currentText(), 'minimum': minimum.value()} for key, (mode, minimum) in score_widgets.items()},
        **{key: spin.value() for key, spin in players.items()},
        'tiers': [tier for tier, check in tiers.items() if check.isChecked()],
    })
    return dialog
