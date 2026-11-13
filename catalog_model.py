"""Table columns, display values, sorting and filtering."""

from PySide6.QtCore import Qt, QAbstractTableModel, QSortFilterProxyModel
from PySide6.QtWidgets import QApplication
from date_display import DATE_FIELDS, friendly_date, date_sort_key
from visuals import store_background, is_installed, installed_icon
from browsing import matches
from unknown_style import unknown_color


COLUMNS = [
    ("title", "Title"),
    ("store", "Store"),
    ("type", "Type"),
    ("genres", "Genres"),
    ("developers", "Developer"),
    ("publishers", "Publisher"),
    ("release", "Release"),
    ("platforms", "Platforms"),
    ("languages", "Languages"),
    ("controller", "Controller"),
    ("score", "Metacritic"),
    ("playtime", "Hours played"),
    ("last_played", "Last played"),
    ("source", "Data source"),
    ("updated", "Last updated"),
    ("active", "Found in latest refresh"),
    ("installation_status", "Installation status"),
    ("launch_provider", "Launcher"),
    ("installation_path", "Installation path"),
    ("date_added", "Date added to library"),
    ("date_added_source", "How the date was found"),
    ("mc_user_score", "Metacritic users / 10 (PC)"),
    ("mc_critic_count", "Metacritic critic reviews (PC)"),
    ("mc_user_count", "Metacritic user reviews (PC)"),
    ("mc_sentiment", "Metacritic verdict (PC)"),
    ("mc_rating", "Metacritic age rating"),
    ("mc_genre", "Metacritic genre"),
    ("mc_release", "Metacritic PC release"),
    ("mc_url", "Metacritic page"),
    ("mc_checked", "Metacritic last checked"),
    ("mc_status", "Metacritic match status"),
]


from extra_schema import COLUMNS as EXTRA_COLUMNS
COLUMNS += EXTRA_COLUMNS
COLUMNS += [("favorite", "Favorite"), ("personal_tags", "Personal tags")]

COLUMN_HELP = {
    "oc_score": "Average OpenCritic top critic score out of 100, combined across platforms. It is separate from the PC Metacritic score.",
    "oc_recommended": "Percentage of OpenCritic critics recommending the game. This is not an average review score.",
    "hltb_main": "Community-estimated main story length in hours from HowLongToBeat. It is not a measurement of your own playthrough.",
    "hltb_status": "Result of the last HowLongToBeat check. A unique exact PC title match is required; editions, DLCs and alternate titles are not guessed. A failed check keeps previously saved values.",
    "hltb_checked": "When HowLongToBeat was last checked. Successful matches are cached for seven days; unmatched titles for one day.",
    "proton_tier": "Community Linux compatibility rating for the verified Steam app ID. This is not a guarantee for your hardware, launcher or game version.",
    "sgdb_artists": "Artists credited for the chosen SteamGridDB images. Per-image artist profiles and asset IDs are saved in the entry’s source data.",
    "mc_user_score": "User rating out of 10, saved only when the page explicitly identifies PC. This is separate from the critic score out of 100.",
    "mc_status": "Result of the last direct Metacritic check. Exact normalized titles and a PC entry are required; editions and alternate titles are not guessed. A failed check keeps previously saved values.",
    "mc_checked": "When Metacritic was last checked. Successful matches are cached for seven days; unmatched titles for one day.",
    "mc_release": "PC release date reported by Metacritic; kept separately from the store release date.",
    "date_added": "When the game joined your store account, not when it was installed. A dash means no reliable date was found.",
    "date_added_source": "Where this date came from. A manually set date takes priority over dates found during refreshes.",
    "active": "Whether the store included this game in its latest complete library response. This is unrelated to installation status.",
    "updated": "When this saved entry was last updated. This is not the date the game was added to your account.",
    "score": "Critic score out of 100. A verified direct Metacritic PC score takes priority over store-supplied scores. See Metacritic match status for verification.",
    "installation_status": "What the latest local scan found. Installed does not guarantee every game file is present. See Installation report for details.",
    "playtime": "Hours reported by the store. A dash means the store did not supply playtime; it does not mean zero.",
}


def display(value, key):
    if value is None or value == "":
        return "—"
    if isinstance(value,str) and value.casefold()=="unknown":
        return "—"
    if key in ("oc_score", "oc_recommended", "igdb_rating", "igdb_critic_rating", "hltb_main", "hltb_main_extra", "hltb_completionist", "hltb_all_styles") and isinstance(value, (int, float)):
        return f"{value:.1f}"
    if key == "playtime":
        return f"{value / 60:.1f}"
    if key == "last_played" and not value:
        return "Never played, or date not provided"
    if key in DATE_FIELDS:
        return friendly_date(value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


class Model(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.installed_marker = installed_icon()

    def load(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.ToolTipRole:
            return COLUMN_HELP.get(
                COLUMNS[section][0],
                "A dash means this information was not supplied or could not be found.",
            )
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section][1]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        key = COLUMNS[index.column()][0]
        value = self.rows[index.row()].get(key)
        if role == Qt.DisplayRole:
            return display(value, key)
        if role == Qt.TextAlignmentRole and key != "title":
            return Qt.AlignCenter
        if role == Qt.ForegroundRole and display(value, key) == "—":
            return unknown_color(
                store_background(
                    self.rows[index.row()].get("store"), QApplication.palette()
                )
            )
        if role == Qt.BackgroundRole:
            return store_background(
                self.rows[index.row()].get("store"), QApplication.palette()
            )
        if (
            role == Qt.DecorationRole
            and key == "title"
            and is_installed(self.rows[index.row()])
        ):
            return self.installed_marker
        if role == Qt.UserRole:
            if key in DATE_FIELDS:
                return date_sort_key(value)
            return value
        if role == Qt.ToolTipRole:
            return display(value, key) + (
                " — Installed on this system"
                if key == "title" and is_installed(self.rows[index.row()])
                else ""
            )


class Filter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.filters = {}
        self.setSortRole(Qt.UserRole)

    def filterAcceptsRow(self, n, parent):
        return matches(self.sourceModel().rows[n], self.filters)

    def lessThan(self, a, b):
        av = self.sourceModel().data(a, Qt.UserRole)
        bv = self.sourceModel().data(b, Qt.UserRole)
        if av is None:
            return bv is not None
        if bv is None:
            return False
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            return av < bv
        return str(av).casefold() < str(bv).casefold()
