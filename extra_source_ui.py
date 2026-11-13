"""Optional enrichment settings, kept separate from account-library connections."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIntValidator
from PySide6.QtWidgets import QWidget, QFormLayout, QCheckBox, QLineEdit
from unknown_style import UnknownTextEdit
from ui_actions import action_button
from request_budgets import request_limit, option_key, MAXIMUM

DEFINITIONS = {
    "IGDB": (
        [
            ("igdb_client_id", "Twitch client ID", False),
            ("igdb_client_secret", "Twitch client secret", True),
        ],
        "https://api-docs.igdb.com/#account-creation",
        "Create a Twitch developer application (Confidential client), then enter its client ID and secret. The app obtains and renews an IGDB access token automatically. IGDB adds genres, themes, game modes, player perspectives, franchises, summaries, ratings and PC local-player counts when supplied. Only a unique exact PC title match is accepted. A verified Steam mapping can also enable ProtonDB for games from other stores.",
    ),
    "ProtonDB": (
        [],
        "https://www.protondb.com/",
        "No API key is needed. Fetches Linux compatibility tier, recent tier, confidence and report count. Steam games use their exact app ID. Other stores require a Steam mapping from a verified IGDB match; title guesses are never used. Community reports are not a guarantee for your setup.",
    ),
    "SteamGridDB": (
        [("sgdb_api_key", "SteamGridDB API key", True)],
        "https://www.steamgriddb.com/profile/preferences/api",
        "Sign in to SteamGridDB and generate an API key. Fetches cover, banner, logo and icon URLs with artist attribution. Exact Steam mappings take priority; other games need a unique exact title match. Images flagged as NSFW, humor or flashing are excluded. Covers fill empty library artwork; existing covers are kept.",
    ),
    "OpenCritic": (
        [("opencritic_api_key", "RapidAPI key for OpenCritic", True)],
        "https://rapidapi.com/opencritic-opencritic-default/api/opencritic-api",
        "Subscribe to the OpenCritic API through RapidAPI, then enter your RapidAPI key. Your plan may have request limits or charges; the app never subscribes for you. Fetches average top critic score, percentage recommended, tier and review count. OpenCritic combines platforms; its scores are stored separately from PC Metacritic scores. Only unique exact title matches are accepted.",
    ),
    "HLTB": (
        [],
        "https://howlongtobeat.com/",
        "No API key is needed. Searches the public HowLongToBeat site by title and saves main story, main + extras, completionist and all-styles lengths in hours, plus the game page link. Only a unique exact title match on a PC-listed entry is accepted; editions, DLCs and alternate titles are not guessed. HowLongToBeat lengths are community estimates, not a measurement of your own playthrough.",
    ),
}


def add_extra_tabs(tabs, options, fields, toggles, secret_toggle):
    for name, (definitions, url, help_text) in DEFINITIONS.items():
        page = QWidget()
        form = QFormLayout(page)
        check = QCheckBox("Include in Get extra game data")
        check.setChecked(options.get("metadata_" + name, True) is True)
        toggles["metadata_" + name] = check
        form.addRow(check)
        if name == "OpenCritic":
            resume = QCheckBox("Automatically continue queued OpenCritic games using reported quota")
            resume.setChecked(options.get("opencritic_auto_resume", True) is True)
            toggles["opencritic_auto_resume"] = resume
            form.addRow(resume)
        help_view = UnknownTextEdit()
        help_view.setReadOnly(True)
        help_view.setPlainText(
            help_text
            + "\n\nCredentials are saved locally on this computer. Results are cached for seven days, unmatched entries for one day. Fetches run when you choose Get extra game data or explicitly select this source in Fetch selected details. Existing values are kept after failures. New optional columns are available in Columns… and exports."
        )
        help_view.setMaximumHeight(240)
        form.addRow(help_view)
        for key, label, secret in definitions:
            edit = QLineEdit(str(options.get(key, "")))
            fields[key] = edit
            if secret:
                secret_toggle(edit)
            form.addRow(label, edit)
        budget = QLineEdit(str(request_limit(options, name)))
        budget.setValidator(QIntValidator(0, MAXIMUM, budget))
        budget.setToolTip("Maximum HTTP attempts for this source in one metadata fetch. 0 means no local cap. Failed requests, retries and IGDB authentication count. Background connection checks are separate. This does not measure your provider subscription quota.")
        fields[option_key(name)] = budget
        form.addRow("HTTP requests per fetch (0 = unlimited)", budget)
        button = action_button("Open " + name + " setup page", "settings")
        button.clicked.connect(
            lambda checked=False, target=url: QDesktopServices.openUrl(QUrl(target))
        )
        form.addRow(button)
        tabs.addTab(page, name)
