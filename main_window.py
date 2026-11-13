from database_connections import ConnectionPanel
"""Main window composition and user actions."""

import html
import json
import threading
from PySide6.QtCore import Qt, QSettings, QSize, QTimer, QItemSelectionModel
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QTableView,
    QLineEdit,
    QComboBox,
    QLabel,
    QTabWidget,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QHeaderView,
    QSpinBox,
    QProgressBar,
    QListView,
    QStackedWidget,
    QMenu,
    QInputDialog,
    QStyle,
)
from core import Database, STORES
from unknown_style import (
    UnknownTextEdit,
    UnknownItemDelegate,
    UnknownComboBox,
    set_unknown_label,
)
from catalog_loading import CatalogLoads
from import_worker import ImportWorker
from local_tasks import LocalTask
from provider_registry import launch_supported
from configuration import normalize_options, normalize_links, normalize_overrides
from contracts import LogEntry, Severity
from operation_policy import completion_message, needs_installation_scan
from date_display import friendly_date
from date_ui import DateAddedDialog
from appearance import appearance
from log_view import ColorLog
from browsing_state import PLAYED_OPTIONS, normalize_snapshot, normalize_presets
from widgets import MultiSelect, Covers, CoverDelegate
from installations import LaunchError
from launch_ui import InstallationSettings, LaunchOverride
from launch_service import Launches
from launch_commands import ready_installations


from app_config import VERSION, DISPLAY_NAME, SETTINGS_ORG, SETTINGS_APP, data_root
from catalog_model import COLUMNS, display, Model, Filter
from source_dialog import Sources
from sync_worker import Worker
from report_dialogs import show_prepared_report
from settings_store import read_json_setting, write_json_setting
from ui_actions import action_button

ROOT = data_root()


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{DISPLAY_NAME} · {VERSION}")
        self.resize(1560, 950)
        self.appearance = appearance()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.db = Database(ROOT / "library.sqlite3")
        self.catalog_loads = CatalogLoads(self.db, self)
        self.catalog_loads.loaded.connect(self.apply_catalog)
        self.catalog_loads.failed.connect(self.catalog_failed)
        self.catalog_loads.idle.connect(self.catalog_idle)
        self.close_after_load = False
        self.local_active = False
        self.local_worker = None
        self.local_cancel = None
        self.import_active = False
        self.import_worker = None
        self.import_cancel = None
        self.worker = None
        self.operation_result = None
        self.closing = False
        self.options = normalize_options(self.read_setting("options", {}))
        self.launch_overrides = normalize_overrides(
            self.read_setting("launch_overrides", {})
        )
        self.launch_links = normalize_links(self.read_setting("launch_links", {}))
        self.installation_snapshot = {}
        self.launches = Launches(ROOT / "launch.log", self)
        self.launches.event.connect(self.launch_message)
        self.presets = normalize_presets(self.read_setting("presets", {}), len(COLUMNS))
        self.selected_cover_url = None
        self.restoring = True
        self.covers = Covers(ROOT / "covers", self)
        self.covers.ready.connect(self.cover_ready)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        heading = QLabel("Magik Games Library")
        heading.setStyleSheet("font-size:24px;font-weight:600;padding:8px")
        heading_row = QHBoxLayout()
        heading_row.addWidget(heading)
        heading_row.addStretch()
        self.connections = ConnectionPanel(
            self,
            can_check=lambda: (
                not self.closing
                and not self.activity_busy()
                and QApplication.activeModalWidget() is None
            ),
        )
        self.connections.idle.connect(self.catalog_idle)
        heading_row.addWidget(self.connections)
        layout.addLayout(heading_row)
        self.connections.set_options(self.options)
        bar = QHBoxLayout()
        layout.addLayout(bar)
        self.buttons = []
        # Button labels drive the window minimum width; rarely used actions live in the
        # Tools menu so the rows stay narrow on any screen.
        tips = {
            "Sources…": "Connect store accounts and choose which libraries to refresh.",
            "Refresh libraries": "Read your enabled store accounts and update your game list and dates added. Then check installed games.",
            "Get missing game details": "Request missing descriptions, genres and other details from Steam, GOG and Epic. Account history is not checked.",
            "Retry missing details": "Try missing game details again now, including entries that are waiting after a failed request.",
            "Rescan installations": "Check local launcher records and game folders. This does not contact your store accounts or install games.",
            "Installations…": "Add launcher data folders and choose launcher programs. The usual folders are checked automatically.",
            "Export…": "Save the games currently visible, in their displayed order, as JSON or CSV, with all fields, names only, or names and dates added.",
            "Import JSON…": "Merge games from a saved JSON file into this library. Other entries are kept.",
            "Date added report…": "See where account dates came from and why some dates are still unknown.",
            "Game details report…": "See which games have missing details, the last request result and when you can retry.",
            "Installation report…": "See every installation found by the last scan and what could not be checked.",
            "Appearance…": "Choose the global theme and colour palette.",
            "Fetch selected details…": "Request details for the selected games only, choosing which sources are used.",
            "Review metadata match…": "Check which store page was matched to the selected game and correct the match.",
            "Favorite / tags…": "Set the favorite marker and personal tags for the selected game.",
            "Copies across stores…": "Find games owned on several stores and jump to each copy.",
            "Get Metacritic data": "Request missing Metacritic scores. The API key is configured in Sources.",
            "Get extra game data": "Request extra details from the optional sources enabled in Sources.",
            "OpenCritic quota…": "See the OpenCritic request quota and the queue of waiting games.",
            "Save preset…": "Save the current filters, sort and view as a reusable preset.",
            "Delete preset": "Delete the preset currently selected in the dropdown.",
            "Backups…": "Create, inspect or restore database backups.",
            "Tools": "Less frequently used tools, reports and settings.",
        }

        def button(text, callback, target=bar, disable=True, role="settings"):
            b = action_button(text, role)
            if text in tips:
                b.setToolTip(tips[text])
            b.clicked.connect(callback)
            target.addWidget(b)
            if disable:
                self.buttons.append(b)
            return b

        def menu_action(text, callback, menu, disable=True):
            action = QAction(text, self)
            if text in tips:
                action.setToolTip(tips[text])
            action.triggered.connect(callback)
            menu.addAction(action)
            if disable:
                self.buttons.append(action)
            return action

        button("Sources…", self.sources, role="settings")
        button("Refresh libraries", lambda: self.start("sync"), role="sync")
        self.enrich = QCheckBox("Get game details after refresh")
        self.enrich.setChecked(True)
        self.enrich.setToolTip(
            "After updating account libraries, request missing Steam, GOG and Epic game details. Entries waiting after an error are skipped until they can be retried. Missing date-added lookups are always finished first."
        )
        bar.addWidget(self.enrich)
        button(
            "Get missing game details", lambda: self.start("enrich"), role="metadata"
        )
        self.stop = button("Stop", self.cancel, disable=False, role="danger")
        self.stop.setEnabled(False)
        bar.addStretch()
        tools_menu = QMenu(self)
        tools_menu.setToolTipsVisible(True)
        menu_action("Appearance…", lambda: self.appearance.choose(self), tools_menu, False)
        menu_action("Retry missing details", lambda: self.start("retry"), tools_menu)
        tools_menu.addSection("Selected game")
        menu_action("Fetch selected details…", self.fetch_selected_details, tools_menu)
        menu_action("Review metadata match…", self.review_metadata_match, tools_menu)
        menu_action("Favorite / tags…", self.edit_personal_entry, tools_menu, False)
        menu_action("Copies across stores…", self.show_store_copies, tools_menu, False)
        tools_menu.addSection("More game data")
        menu_action("Get Metacritic data", lambda: self.start("metacritic"), tools_menu)
        menu_action("Get extra game data", lambda: self.start("extra"), tools_menu)
        self.oc_quota_action = menu_action("OpenCritic quota…", self.opencritic_quota, tools_menu, False)
        tools_menu.addSection("Reports")
        menu_action("Date added report…", self.acquisition_report, tools_menu, False)
        menu_action("Game details report…", self.metadata_report, tools_menu, False)
        menu_action("Installation report…", self.installation_report, tools_menu, False)
        tools_menu.addSection("Library and presets")
        menu_action("Save preset…", self.save_preset, tools_menu, False)
        menu_action("Delete preset", self.delete_preset, tools_menu, False)
        menu_action("Backups…", self.database_backups, tools_menu)
        tools_button = button("Tools", lambda: None, disable=False, role="settings")
        tools_button.setMenu(tools_menu)
        tools = QHBoxLayout()
        layout.addLayout(tools)
        self.preset = QComboBox()
        self.preset.setPlaceholderText("Saved filter presets")
        self.preset.setMinimumWidth(160)
        tools.addWidget(self.preset)
        button("Apply preset", self.apply_preset, tools, False, role="filter")
        button("Columns…", self.columns_menu, tools, False, role="settings")
        button("Export…", self.export, tools, role="file")
        button("Import JSON…", self.import_json, tools, role="file")
        button(
            "Rescan installations", lambda: self.start("scan"), tools, role="sync"
        )
        button("Installations…", self.installation_settings, tools, role="settings")
        tools.addStretch()
        filters = QHBoxLayout()
        layout.addLayout(filters)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, developer, genre, description, personal tags…")
        filters.addWidget(self.search, 3)
        self.facets = {}
        for key, label in [
            ("store", "Stores"),
            ("type", "Types"),
            ("genres", "Genres"),
            ("platforms", "Platforms"),
            ("languages", "Languages"),
            ("installation_status", "Installed status"),
            ("personal_tags", "Personal tags"),
        ]:
            pick = MultiSelect(label)
            self.facets[key] = pick
            filters.addWidget(pick)
            pick.changed.connect(self.apply_filters)
        self.played = UnknownComboBox()
        self.played.addItems(PLAYED_OPTIONS)
        filters.addWidget(self.played)
        second = QHBoxLayout()
        layout.addLayout(second)
        second.addWidget(QLabel("Minimum review score"))
        self.score = QSpinBox()
        self.score.setRange(0, 100)
        self.score.setSpecialValueText("Any")
        self.score.setToolTip(
            "Metacritic review score. Any includes games without a score. A minimum score hides games with a lower score or no score."
        )
        second.addWidget(self.score)
        self.current = QCheckBox("Found in latest refresh only")
        self.current.setToolTip(
            "Hide saved games that were absent from the latest complete library response for their store. This is unrelated to whether they are installed."
        )
        second.addWidget(self.current)
        self.favorites = QCheckBox("Favorites only")
        self.favorites.toggled.connect(self.apply_filters)
        second.addWidget(self.favorites)
        self.advanced_filters = {}
        self.advanced_button = button("Advanced filters…", self.edit_advanced_filters, second, False, role="filter")
        button("Clear filters", self.clear_filters, second, False, role="filter")
        second.addStretch()
        second.addWidget(QLabel("Sort by"))
        self.sort_key = QComboBox()
        self.sort_key.addItems([v[1] for v in COLUMNS])
        second.addWidget(self.sort_key)
        self.descending = QCheckBox("Descending")
        second.addWidget(self.descending)
        self.view_mode = QComboBox()
        self.view_mode.addItems(["Table", "Covers"])
        second.addWidget(self.view_mode)
        split = QSplitter()
        layout.addWidget(split, 1)
        self.model = Model()
        self.proxy = Filter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.setItemDelegate(UnknownItemDelegate(self.table))
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionsMovable(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(3, 180)
        self.grid = QListView()
        self.grid.setModel(self.proxy)
        self.grid.setModelColumn(0)
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWrapping(True)
        self.grid.setGridSize(QSize(190, 312))
        self.grid.setUniformItemSizes(True)
        self.grid.setSelectionMode(QListView.ExtendedSelection)
        self.grid.setSelectionModel(self.table.selectionModel())
        self.grid.setItemDelegate(CoverDelegate(self.covers, self.grid))
        for view in [self.table, self.grid]:
            view.setContextMenuPolicy(Qt.CustomContextMenu)
            view.customContextMenuRequested.connect(
                lambda pos, v=view: self.game_menu(v, pos)
            )
            view.doubleClicked.connect(lambda index: self.play_selected())
        self.views = QStackedWidget()
        self.views.addWidget(self.table)
        self.views.addWidget(self.grid)
        split.addWidget(self.views)
        side = QWidget()
        sl = QVBoxLayout(side)
        playrow = QHBoxLayout()
        sl.addLayout(playrow)
        self.play_button = action_button("▶ Play", "launch")
        self.play_button.setToolTip(
            "Play opens the game through its existing launcher. A successful request does not confirm the game is running."
        )
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(self.play_selected)
        playrow.addWidget(self.play_button)
        self.install_button = action_button("Install with Heroic…", "sync")
        self.install_button.setToolTip("Open Heroic’s install confirmation for this game. If Heroic already considers it installed, Heroic may launch it instead. Installation options and confirmation stay in Heroic.")
        self.install_button.setVisible(False)
        self.install_button.clicked.connect(self.install_with_heroic)
        sl.addWidget(self.install_button)
        self.steam_button = action_button("Open in Steam", "launch")
        self.steam_button.setToolTip("Open this game’s library page in the Steam client. This does not launch or install the game.")
        self.steam_button.setVisible(False)
        self.steam_button.clicked.connect(self.open_selected_in_steam)
        sl.addWidget(self.steam_button)
        self.link_button = action_button("Link installation…", "settings")
        self.link_button.setToolTip(
            "Associate this store game with an existing Lutris or Windows installation. No game files are moved."
        )
        self.link_button.setEnabled(False)
        self.link_button.clicked.connect(self.link_lutris)
        playrow.addWidget(self.link_button)
        self.setup_button = action_button("Launch setup…", "settings")
        self.setup_button.setToolTip(
            "Choose a local program or script for launching this game. Leave it blank to return to the default launcher."
        )
        self.setup_button.setEnabled(False)
        self.setup_button.clicked.connect(self.launch_setup)
        sl.addWidget(self.setup_button)
        self.installation_label = QLabel("Select a game")
        self.installation_label.setWordWrap(True)
        sl.addWidget(self.installation_label)
        self.cover = QLabel("Select a game")
        self.cover.setMinimumHeight(130)
        self.cover.setMaximumHeight(230)
        self.cover.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.cover)
        tabs = QTabWidget()
        self.details = UnknownTextEdit()
        self.raw = UnknownTextEdit()
        for label, widget in [
            ("Details", self.details),
            ("Source data (technical)", self.raw),
        ]:
            widget.setReadOnly(True)
            tabs.addTab(widget, label)
        sl.addWidget(tabs, 1)
        split.addWidget(side)
        split.setSizes([1100, 400])
        self.count = QLabel()
        self.count.setToolTip(
            "A game must match every filter; any selected value within a filter is enough."
        )
        layout.addWidget(self.count)
        self.status = ColorLog()
        self.log_restored = False
        self.status.setReadOnly(True)
        self.status.setMaximumHeight(115)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.table.selectionModel().currentRowChanged.connect(self.select)
        self.search.textChanged.connect(self.apply_filters)
        self.played.currentIndexChanged.connect(self.apply_filters)
        self.score.valueChanged.connect(self.apply_filters)
        self.current.toggled.connect(self.apply_filters)
        self.connections.store_filter_changed.connect(self.apply_filters)
        self.sort_key.currentIndexChanged.connect(self.sort_changed)
        self.descending.toggled.connect(self.sort_changed)
        self.table.horizontalHeader().sortIndicatorChanged.connect(
            self.header_sort_changed
        )
        self.view_mode.currentIndexChanged.connect(self.change_view)
        geometry = self.settings.value("geometry")
        header = self.settings.value("header")
        if geometry:
            self.restoreGeometry(geometry)
        if header:
            self.table.horizontalHeader().restoreState(header)
        self.statusBar().showMessage("Loading your saved library…")
        self.reload()
        self.refresh_presets()
        self.restoring = False
        self.restore_snapshot(self.read_setting("browsing", {}))
        self.quota_timer = QTimer(self)
        self.quota_timer.setInterval(30000)
        self.quota_timer.timeout.connect(self.resume_opencritic_queue)
        self.quota_timer.start()

    def read_setting(self, key, fallback):
        return read_json_setting(self.settings, key, fallback)

    def showEvent(self, event):
        super().showEvent(event)
        self.clamp_to_screen()

    def clamp_to_screen(self):
        """Never let the window exceed the screen, even if restored geometry or a
        wider layout would push it past the visible area."""
        if self.closing or self.isMinimized() or self.isMaximized() or self.isFullScreen():
            return
        handle = self.windowHandle()
        screen = handle.screen() if handle is not None else QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        if frame.width() <= available.width() and frame.height() <= available.height() and available.intersects(frame):
            return
        size = QSize(min(self.width(), available.width()), min(self.height(), available.height()))
        self.setGeometry(QStyle.alignedRect(Qt.LeftToRight, Qt.AlignCenter, size, available))

    def sources(self):
        self.connections.pause()
        d = Sources(self.options, self)
        if d.exec():
            self.options.update(d.values())
            self.connections.set_options(self.options)
            saved = dict(self.options)
            write_json_setting(self.settings, "options", saved)
            self.settings.sync()
        QTimer.singleShot(0, self.connections.refresh)

    def start(self, mode, **kwargs):
        if (
            self.closing
            or self.import_active
            or self.local_active
            or (self.worker and self.worker.isRunning())
        ):
            return
        self.connections.pause()
        self.operation_result = None
        self.worker = Worker(self.db, self.options, mode, self.enrich.isChecked(), **kwargs)
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.changed.connect(self.reload)
        self.worker.result.connect(self.finished)
        self.worker.finished.connect(self.idle)
        for b in self.buttons:
            b.setEnabled(False)
        self.stop.setEnabled(True)
        self.progress.show()
        self.worker.start()

    def finished(self, result):
        self.operation_result = result
        self.status.append_events(result.events)
        self.statusBar().showMessage(completion_message(result))

    def idle(self):
        self.update_activity_controls()
        completed = self.worker
        if completed and needs_installation_scan(
            completed.mode, self.operation_result, completed.cancel.is_set()
        ):
            QTimer.singleShot(0, lambda: self.scan_after_refresh(completed))
        elif self.operation_result is not None and not self.operation_result.cancelled:
            QTimer.singleShot(0, self.connections.refresh)

    def scan_after_refresh(self, completed):
        if (
            not self.closing
            and self.worker is completed
            and not completed.isRunning()
            and needs_installation_scan(
                completed.mode, self.operation_result, completed.cancel.is_set()
            )
        ):
            self.start("scan")

    def cancel(self):
        if self.local_active:
            self.local_cancel.set()
            self.statusBar().showMessage(
                "Stopping… An export already saved will be kept; an unfinished report will not open."
            )
            return
        if self.import_active:
            self.import_cancel.set()
            self.statusBar().showMessage(
                "Stopping the import… Changes will be kept only if the import has already committed."
            )
            return
        if self.worker:
            self.worker.cancel.set()
            if self.worker.mode in ("extra", "selected") and self.options.get("opencritic_api_key"):
                from opencritic_quota import Quota, QuotaPaused
                try:
                    Quota(self.options).clear_queue()
                except (QuotaPaused, OSError):
                    pass
            self.statusBar().showMessage(
                "Stopping… The current request may need to finish first. Saved results will be kept."
            )

    def reload(self):
        if not self.closing:
            self.catalog_loads.request(self.launch_links)

    def catalog_failed(self, message):
        self.status.append_events([LogEntry(message, Severity.ERROR)])
        self.statusBar().showMessage(message)

    def catalog_idle(self):
        if (
            self.close_after_load
            and not self.catalog_loads.busy
            and not self.connections.busy
        ):
            QTimer.singleShot(0, self.close)

    def apply_catalog(self, data):
        from metadata_review import selected_keys
        selected = selected_keys(self.table, self.proxy, self.model)
        current = self.table.currentIndex()
        identity = None
        if current.isValid():
            previous = self.model.rows[self.proxy.mapToSource(current).row()]
            identity = (previous["store"], previous["id"])
        table_scroll = self.table.verticalScrollBar().value()
        grid_scroll = self.grid.verticalScrollBar().value()
        if self.closing:
            return
        self.installation_snapshot = data["installations"]
        self.store_copy_groups = data.get("copies", [])
        rows = data["rows"]
        self.model.load(rows)
        for key, pick in self.facets.items():
            pick.set_options(data["facets"][key])
        self.apply_filters()
        if identity:
            for i, row in enumerate(rows):
                if (row["store"], row["id"]) == identity:
                    index = self.proxy.mapFromSource(self.model.index(i, 0))
                    if index.isValid():
                        self.table.setCurrentIndex(index)
                    break
        selection = self.table.selectionModel()
        for i, row in enumerate(rows):
            if (row["store"], str(row["id"])) in selected:
                index = self.proxy.mapFromSource(self.model.index(i, 0))
                if index.isValid():
                    selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.table.verticalScrollBar().setValue(table_scroll)
        self.grid.verticalScrollBar().setValue(grid_scroll)
        if not self.log_restored:
            if self.statusBar().currentMessage() == "Loading your saved library…":
                self.statusBar().clearMessage()
            self.log_restored = True
            statuses = data["statuses"]
            if statuses:
                events = []
                for store, value in statuses.items():
                    try:
                        level = Severity(value.get("severity", "info"))
                    except (ValueError, TypeError):
                        level = Severity.INFO
                    events.append(
                        LogEntry(
                            f"{store}: {value['message']} ({friendly_date(value['time'])})",
                            level,
                            store,
                        )
                    )
                self.status.set_events(events + list(self.status.entries))
            elif not rows and not self.status.entries:
                self.status.setPlainText(
                    "Your library is empty. Open Sources to connect your accounts, then choose Refresh libraries. Rockstar is not supported yet."
                )

    def open_selected_in_steam(self):
        index = self.table.currentIndex()
        if not index.isValid():
            return
        row = self.model.rows[self.proxy.mapToSource(index).row()]
        from steam_open import open_in_steam
        try:
            open_in_steam(row, self.options)
            self.launch_message(LogEntry("Steam library page requested for " + row["title"] + ".", Severity.SUCCESS))
        except ValueError as exc:
            self.launch_message(LogEntry(str(exc), Severity.ERROR))

    def install_with_heroic(self):
        index = self.table.currentIndex()
        if not index.isValid():
            return
        row = self.model.rows[self.proxy.mapToSource(index).row()]
        from heroic_install import open_install, can_install
        if not can_install(row):
            return
        try:
            open_install(row, self.options)
            self.launch_message(LogEntry("Heroic request sent for " + row["title"] + ". Confirm installation in Heroic; rescan installations when it finishes.", Severity.SUCCESS))
        except ValueError as exc:
            self.launch_message(LogEntry(str(exc), Severity.ERROR))

    def filter_values(self):
        return dict(
            search=self.search.text(),
            played=self.played.currentText(),
            score=self.score.value(),
            current=self.current.isChecked(),
            favorites=self.favorites.isChecked(),
            advanced=self.advanced_filters,
            visible_stores=self.connections.visible_stores(),
            **{k: p.selected[:] for k, p in self.facets.items()},
        )

    def apply_filters(self, *args):
        from advanced_filters import active_count
        count = active_count(self.advanced_filters)
        self.advanced_button.setText(f"Advanced filters… ({count})" if count else "Advanced filters…")
        self.proxy.filters = self.filter_values()
        self.proxy.invalidate()
        self.count.setText(
            f"{self.proxy.rowCount():,} shown · {len(self.model.rows):,} library entries"
        )
        self.remember_browsing()

    def snapshot(self):
        return {
            "filters": self.filter_values(),
            "sort_key": self.sort_key.currentIndex(),
            "descending": self.descending.isChecked(),
            "view": self.view_mode.currentIndex(),
        }

    def remember_browsing(self):
        if not self.restoring:
            write_json_setting(self.settings, "browsing", self.snapshot())

    def restore_snapshot(self, state):
        state = normalize_snapshot(state, len(COLUMNS))
        self.restoring = True
        f = state.get("filters", {})
        self.connections.set_visible_stores(f["visible_stores"])
        self.search.setText(f.get("search", ""))
        self.played.setCurrentText(f.get("played", "All"))
        self.score.setValue(f.get("score", 0))
        self.current.setChecked(f.get("current", False))
        self.advanced_filters = f["advanced"]
        self.favorites.setChecked(f.get("favorites", False))
        for key, pick in self.facets.items():
            pick.set_selected(f.get(key, []))
        self.sort_key.setCurrentIndex(
            max(0, min(len(COLUMNS) - 1, state.get("sort_key", 0)))
        )
        self.descending.setChecked(state.get("descending", False))
        self.view_mode.setCurrentIndex(1 if state.get("view") == 1 else 0)
        self.restoring = False
        self.sort_changed()
        self.change_view()
        self.apply_filters()

    def clear_filters(self):
        state = self.snapshot()
        state["filters"] = {}
        self.restore_snapshot(state)

    def refresh_presets(self, selected=None):
        self.preset.clear()
        self.preset.addItems(sorted(self.presets, key=str.casefold))
        if selected:
            self.preset.setCurrentText(selected)

    def save_preset(self):
        name, ok = QInputDialog.getText(
            self, "Save filter preset", "Name:", text=self.preset.currentText()
        )
        name = name.strip()
        if not ok or not name:
            return
        if (
            name in self.presets
            and QMessageBox.question(self, "Replace preset", f"Replace “{name}”?")
            != QMessageBox.Yes
        ):
            return
        self.presets[name] = self.snapshot()
        write_json_setting(self.settings, "presets", self.presets)
        self.refresh_presets(name)

    def apply_preset(self):
        state = self.presets.get(self.preset.currentText())
        if state:
            self.restore_snapshot(state)

    def delete_preset(self):
        name = self.preset.currentText()
        if name in self.presets:
            del self.presets[name]
            write_json_setting(self.settings, "presets", self.presets)
            self.refresh_presets()

    def columns_menu(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Visible columns")
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                "Check the columns you want to see. Changes apply immediately, and this panel stays open. The Title column is always shown."
            )
        )
        for i, (key, label) in enumerate(COLUMNS):
            check = QCheckBox(label)
            check.setChecked(not self.table.isColumnHidden(i))
            check.setEnabled(i != 0)
            check.toggled.connect(lambda visible, col=i: self.set_column(col, visible))
            layout.addWidget(check)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def set_column(self, col, visible):
        self.table.setColumnHidden(col, not visible)
        self.settings.setValue("header", self.table.horizontalHeader().saveState())

    def sort_changed(self, *args):
        col = self.sort_key.currentIndex()
        order = Qt.DescendingOrder if self.descending.isChecked() else Qt.AscendingOrder
        self.proxy.sort(col, order)
        self.table.horizontalHeader().setSortIndicator(col, order)
        self.remember_browsing()

    def header_sort_changed(self, col, order):
        self.sort_key.blockSignals(True)
        self.descending.blockSignals(True)
        self.sort_key.setCurrentIndex(col)
        self.descending.setChecked(order == Qt.DescendingOrder)
        self.sort_key.blockSignals(False)
        self.descending.blockSignals(False)
        self.remember_browsing()

    def change_view(self, *args):
        self.views.setCurrentIndex(self.view_mode.currentIndex())
        self.remember_browsing()

    def cover_ready(self, url):
        self.grid.viewport().update()
        if url == self.selected_cover_url:
            self.update_cover()

    def update_cover(self):
        pix = self.covers.get_cover(self.selected_cover_url)
        if pix:
            self.cover.setPixmap(
                pix.scaled(390, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        else:
            self.cover.setText(
                "Loading cover, or no cover available"
                if self.selected_cover_url
                else "No cover image available"
            )

    def select(self, index, *args):
        self.selected_cover_url = None
        self.cover.clear()
        if not index.isValid():
            self.install_button.setVisible(False)
            self.steam_button.setVisible(False)
            self.details.clear()
            self.raw.clear()
            self.setup_button.setEnabled(False)
            self.play_button.setEnabled(False)
            self.link_button.setEnabled(False)
            set_unknown_label(self.installation_label, "Select a game")
            return
        row = self.model.rows[self.proxy.mapToSource(index).row()]
        from heroic_install import can_install
        self.install_button.setVisible(can_install(row))
        from steam_open import can_open
        self.steam_button.setVisible(can_open(row))
        self.setup_button.setEnabled(launch_supported(row["store"]))
        candidates = row.get("_installations", [])
        ready = ready_installations(
            row, self.launch_overrides.get(row["store"] + "|" + row["id"])
        )
        self.play_button.setEnabled(bool(ready) and launch_supported(row["store"]))
        self.link_button.setEnabled(
            launch_supported(row["store"])
            and any(
                e["kind"] in ["lutris", "prefix"]
                for e in self.installation_snapshot.get("entries", [])
            )
        )
        set_unknown_label(
            self.installation_label,
            row["installation_status"]
            + (
                " · Ready to launch via "
                + str(len(ready))
                + (" option" if len(ready) == 1 else " options")
                if ready
                else " · Launch setup required: choose how to start this game."
                if any(e["state"] == "Installed" for e in candidates)
                else " · See the installation details below."
            ),
        )
        # Plain text avoids remote resources or active markup in imported descriptions.
        text = "\n\n".join(
            label + ": " + display(row.get(key), key) for key, label in COLUMNS
        )
        description = html.unescape(
            __import__("re").sub("<[^>]+>", " ", row.get("description") or "")
        )
        text += (
            "\n\nA dash means the information was not supplied or could not be found.\n\nInstallation details:\n"
            + "\n".join(
                e["provider"]
                + ": "
                + e["state"]
                + " — "
                + e["detail"]
                + "\n"
                + str(e.get("path") or "Folder not provided by the launcher")
                for e in candidates
            )
        )
        if not candidates:
            text += "No installation was found in the folders checked. The game may be installed elsewhere."
        self.details.setPlainText(
            text
            + "\n\n"
            + description
            + "\n\nStore page: "
            + (row.get("url") or "Unknown")
        )
        self.raw.setPlainText(
            json.dumps(row.get("raw", {}), indent=2, ensure_ascii=False)
        )
        self.selected_cover_url = row.get("cover")
        self.update_cover()

    def selected_game(self):
        index = self.table.currentIndex()
        return (
            self.model.rows[self.proxy.mapToSource(index).row()]
            if index.isValid()
            else None
        )

    def installation_settings(self):
        dialog = InstallationSettings(self.options, self)
        if dialog.exec():
            self.options.update(dialog.values())
            write_json_setting(self.settings, "options", self.options)
            self.settings.sync()
            self.start("scan")

    def installation_report(self):
        self.begin_local_task("installations")

    def link_lutris(self):
        row = self.selected_game()
        if not row or not launch_supported(row["store"]):
            return
        entries = [
            e
            for e in self.installation_snapshot.get("entries", [])
            if e["kind"] in ["lutris", "prefix"]
        ]
        if not entries:
            return
        key = row["store"] + "|" + row["id"]
        labels = [
            f"{e['title']} | {e['provider']} ID {e['record_id']} | {e['state']} | {e.get('path') or 'No path'} | config {e['root']}"
            for e in entries
        ]
        labels.insert(0, "Remove manual association")
        choice, ok = QInputDialog.getItem(
            self,
            "Link existing installation",
            row["title"] + " — choose its actual game installation:",
            labels,
            0,
            False,
        )
        if not ok:
            return
        index = labels.index(choice)
        if index == 0:
            self.launch_links.pop(key, None)
        else:
            self.launch_links[key] = entries[index - 1]["key"]
        write_json_setting(self.settings, "launch_links", self.launch_links)
        self.reload()

    def launch_setup(self):
        row = self.selected_game()
        if not row or not launch_supported(row["store"]):
            return
        key = row["store"] + "|" + row["id"]
        dialog = LaunchOverride(row["title"], self.launch_overrides.get(key, {}), self)
        if dialog.exec():
            if dialog.value["program"]:
                self.launch_overrides[key] = dialog.value
            else:
                self.launch_overrides.pop(key, None)
            write_json_setting(self.settings, "launch_overrides", self.launch_overrides)
            self.settings.sync()
            self.reload()

    def play_selected(self):
        row = self.selected_game()
        if not row or not launch_supported(row["store"]):
            return
        override = self.launch_overrides.get(row["store"] + "|" + row["id"])
        entries = ready_installations(row, override)
        if not entries:
            self.statusBar().showMessage(
                "This game is not ready to launch. Try Rescan installations. If it is installed, use Link installation or Launch setup to choose how to start it."
            )
            return
        entry = entries[0]
        if len(entries) > 1:
            labels = [
                f"{e['provider']} | {e.get('path') or ''} | ID {e['record_id']} | config {e['root']}"
                for e in entries
            ]
            choice, ok = QInputDialog.getItem(
                self, "Choose launch provider", row["title"], labels, 0, False
            )
            if not ok:
                return
            entry = entries[labels.index(choice)]
        try:
            if override:
                self.launches.launch(entry, self.options, override)
            else:
                self.launches.launch(entry, self.options)
        except LaunchError as exc:
            self.launches.log("Launch failed: " + str(exc), Severity.ERROR)
            QMessageBox.warning(self, "Launch failed", str(exc))

    def set_date_added(self):
        row = self.selected_game()
        if not row:
            return
        dialog = DateAddedDialog(row["title"], row.get("date_added"), self)
        if not dialog.exec():
            return
        if not self.db.set_manual_date(row["store"], row["id"], dialog.value):
            return
        self.reload()

    def launch_message(self, event):
        self.status.append_events([event])
        self.statusBar().showMessage(event.text)

    def opencritic_quota(self):
        from opencritic_ui import show_quota
        show_quota(self.options, self)

    def resume_opencritic_queue(self):
        if self.closing or not self.options.get("opencritic_api_key"):
            return
        from opencritic_quota import Quota, QuotaPaused, describe
        try:
            quota = Quota(self.options)
            state = quota.snapshot()
            remaining = [b["remaining"] for b in state.get("buckets", {}).values()]
            self.oc_quota_action.setText(f"OpenCritic quota… ({min(remaining)} left)" if remaining else "OpenCritic quota…")
            self.oc_quota_action.setToolTip(describe(state))
            if (self.activity_busy() or self.connections.busy or self.catalog_loads.busy
                    or QApplication.activeModalWidget() is not None
                    or not self.options.get("metadata_OpenCritic", True)
                    or not self.options.get("opencritic_auto_resume", True)):
                return
            keys = quota.take_ready()
        except (QuotaPaused, OSError):
            return
        if keys:
            self.status.append_events([LogEntry("Resuming queued OpenCritic games after the reported waiting period.")])
            self.start("selected", selected={tuple(v) for v in keys}, sources=["OpenCritic"])

    def database_backups(self):
        if self.closing or self.activity_busy():
            return
        from backup_ui import choose_action
        action = choose_action(self.db, self)
        if not action:
            return
        kind, path = action
        if kind == "restore":
            answer = QMessageBox.question(self, "Restore library database?",
                "This replaces all saved games, metadata, favorites, tags and scan results with the selected backup. A recovery copy of the current database will be saved first. Settings and account logins stay as they are. Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self.begin_local_task(kind, path=path)

    def show_store_copies(self):
        if self.activity_busy():
            return
        from store_copies import choose_copy
        identity = choose_copy(getattr(self, "store_copy_groups", []), self)
        if not identity:
            return
        self.clear_filters()
        for i, row in enumerate(self.model.rows):
            if (row["store"], str(row["id"])) == tuple(identity):
                index = self.proxy.mapFromSource(self.model.index(i, 0))
                if index.isValid():
                    self.table.setCurrentIndex(index)
                    self.table.scrollTo(index)
                    self.grid.scrollTo(index)
                    self.select(index)
                break

    def edit_advanced_filters(self):
        from advanced_filters import create_dialog
        dialog = create_dialog(self.advanced_filters, self)
        if dialog.exec() == QDialog.Accepted:
            self.advanced_filters = dialog.values()
            self.apply_filters()

    def edit_personal_entry(self):
        if self.activity_busy():
            return
        row = self.selected_game()
        if not row:
            self.statusBar().showMessage("Select a game to set its favorite status or personal tags.")
            return
        from personal_library import edit_personal
        if edit_personal(self.db, row, self):
            self.reload()
            self.statusBar().showMessage("Favorite and personal tags saved.")

    def fetch_selected_details(self):
        if self.activity_busy():
            return
        from metadata_review import FetchSelected, selected_keys
        keys = selected_keys(self.table, self.proxy, self.model)
        if not keys:
            self.statusBar().showMessage("Select one or more games first. Use Ctrl or Shift to select several.")
            return
        dialog = FetchSelected(len(keys), self.options, self)
        if dialog.exec() == QDialog.Accepted and dialog.sources():
            self.start("selected", selected=keys, sources=dialog.sources(), force=dialog.force.isChecked())

    def review_metadata_match(self):
        if self.activity_busy():
            return
        row = self.selected_game()
        if not row:
            self.statusBar().showMessage("Select a game to review its metadata matches.")
            return
        from metadata_review import MatchReview, save_matches
        dialog = MatchReview(row, self)
        if dialog.exec() == QDialog.Accepted:
            save_matches(self.db, row, dialog.values())
            self.reload()
            self.statusBar().showMessage("Lookup titles saved. Fetch selected details to request corrected matches.")

    def game_menu(self, view, pos):
        index = view.indexAt(pos)
        if not index.isValid():
            return
        if not self.table.selectionModel().isSelected(index):
            self.table.setCurrentIndex(index)
        else:
            self.table.selectionModel().setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        menu = QMenu(self)
        fetch = menu.addAction("Fetch selected details…")
        fetch.setEnabled(not self.activity_busy())
        fetch.triggered.connect(self.fetch_selected_details)
        review = menu.addAction("Review metadata match…")
        review.setEnabled(not self.activity_busy())
        review.triggered.connect(self.review_metadata_match)
        personal = menu.addAction("Favorite / tags…")
        personal.setEnabled(not self.activity_busy())
        personal.triggered.connect(self.edit_personal_entry)
        play = menu.addAction("Play")
        play.setEnabled(self.play_button.isEnabled())
        play.triggered.connect(self.play_selected)
        link = menu.addAction("Link existing installation…")
        link.setEnabled(self.link_button.isEnabled())
        link.triggered.connect(self.link_lutris)
        added = menu.addAction("Set date added to library…")
        added.triggered.connect(self.set_date_added)
        rescan = menu.addAction("Rescan installations")
        rescan.setEnabled(not self.activity_busy())
        rescan.triggered.connect(lambda: self.start("scan"))
        menu.exec(view.viewport().mapToGlobal(pos))

    def acquisition_report(self):
        self.begin_local_task("acquisition")

    def metadata_report(self):
        self.begin_local_task("metadata")

    def import_json(self):
        if (
            self.closing
            or self.import_active
            or self.local_active
            or (self.worker and self.worker.isRunning())
        ):
            return
        path = QFileDialog.getOpenFileName(
            self, "Import library JSON", "", "JSON (*.json)"
        )[0]
        if not path:
            return
        self.connections.pause()
        self.import_active = True
        self.import_cancel = threading.Event()
        for button in self.buttons:
            button.setEnabled(False)
        self.stop.setEnabled(True)
        self.progress.show()
        self.statusBar().showMessage(
            "Reading and checking the import file… You can keep browsing your library."
        )
        self.run_import(path=path)

    def run_import(self, **kwargs):
        self.import_worker = ImportWorker(
            self.db, self.import_cancel, parent=self, **kwargs
        )
        self.import_worker.finished.connect(self.import_finished)
        self.import_worker.start()

    def import_finished(self):
        completed, self.import_worker = self.import_worker, None
        outcome, value = completed.outcome, completed.value
        completed.deleteLater()
        if outcome == "choose_store" and not self.import_cancel.is_set():
            dialog = QDialog(self)
            form = QFormLayout(dialog)
            store = QComboBox()
            store.addItems(STORES)
            form.addRow("Store this file came from", store)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            form.addRow(buttons)
            if dialog.exec() and not self.import_cancel.is_set():
                self.statusBar().showMessage("Checking and saving imported games…")
                self.run_import(payload=value, store=store.currentText())
                return
            outcome = "cancelled"
        elif outcome == "choose_store":
            outcome = "cancelled"
        self.import_active = False
        self.update_activity_controls()
        QTimer.singleShot(0, self.connections.refresh)
        if outcome == "saved":
            self.reload()
            message = f"Imported {value} entries. Matching entries were updated; other library entries were kept."
            self.status.append_events([LogEntry(message, Severity.SUCCESS)])
            self.statusBar().showMessage(message)
        elif outcome == "cancelled":
            self.statusBar().showMessage(
                "Import stopped. No import changes were saved."
            )
        else:
            QMessageBox.warning(
                self, "Import failed", value or "The import could not finish."
            )
            self.statusBar().showMessage("Import failed. Your library was kept.")

    def activity_busy(self):
        return (
            self.import_active
            or self.local_active
            or bool(self.worker and self.worker.isRunning())
        )

    def update_activity_controls(self):
        busy = self.activity_busy()
        for button in self.buttons:
            button.setEnabled(not busy)
        self.stop.setEnabled(busy)
        self.progress.setVisible(busy)

    def begin_local_task(self, kind, **kwargs):
        if self.closing or self.activity_busy():
            if not self.closing:
                self.statusBar().showMessage(
                    "Please wait for the current task to finish, or choose Stop first."
                )
            return
        self.connections.pause()
        self.local_active = True
        self.local_cancel = threading.Event()
        self.local_worker = LocalTask(
            kind, self.db, self.local_cancel, parent=self, **kwargs
        )
        self.local_worker.finished.connect(self.local_finished)
        self.update_activity_controls()
        self.statusBar().showMessage(
            "Saving the export… You can keep browsing."
            if kind == "export"
            else "Creating a database backup…" if kind == "backup"
            else "Checking and restoring the database…" if kind == "restore"
            else "Preparing the report… You can keep browsing."
        )
        self.local_worker.start()

    def local_finished(self):
        completed, self.local_worker = self.local_worker, None
        outcome, value = completed.outcome, completed.value
        completed.deleteLater()
        self.local_active = False
        self.update_activity_controls()
        QTimer.singleShot(0, self.connections.refresh)
        if outcome in ("backup", "restore"):
            message = "Database backup saved." if outcome == "backup" else "Database restored. The previous database was saved as a recovery copy in Backups."
            self.status.append_events([LogEntry(message, Severity.SUCCESS)])
            self.statusBar().showMessage(message)
            if outcome == "restore":
                self.reload()
        elif outcome == "saved":
            if completed.scope == "names":
                message = f"Exported names for {value} visible library entries."
            elif completed.scope == "names_dates":
                message = f"Exported names and dates for {value} visible library entries."
            else:
                message = f"Exported {value} visible library entries."
            self.status.append_events([LogEntry(message, Severity.SUCCESS)])
            self.statusBar().showMessage(message)
        elif outcome == "cancelled" or (
            outcome == "report" and self.local_cancel.is_set()
        ):
            self.statusBar().showMessage(
                "Task stopped. Unfinished database changes were rolled back; completed backups were kept." if completed.kind in ("backup", "restore") else "Task stopped. An unfinished export was not published, and no report was opened."
            )
        elif outcome == "report":
            self.statusBar().showMessage(
                "Report ready. It shows saved data; no store accounts were contacted."
            )
            show_prepared_report(self, value)
        else:
            title = {"export": "Export failed", "backup": "Backup failed", "restore": "Restore failed"}.get(completed.kind, "Report failed")
            self.statusBar().showMessage(title + ". Existing data was kept.")
            QMessageBox.warning(self, title, value or "The task could not finish.")

    def export(self):
        if self.closing or self.activity_busy():
            return
        path, selected = QFileDialog.getSaveFileName(
            self,
            "Export visible records",
            "games.json",
            "JSON – all fields (*.json);;CSV – all fields (*.csv);;"
            "JSON – names only (*.json);;CSV – names only (*.csv);;"
            "JSON – names and dates (*.json);;CSV – names and dates (*.csv)",
        )
        if not path:
            return
        # Freeze displayed membership/order. Reloads replace row objects rather than mutating them.
        rows = [
            self.model.rows[self.proxy.mapToSource(self.proxy.index(i, 0)).row()]
            for i in range(self.proxy.rowCount())
        ]
        chosen = selected.lower()
        self.begin_local_task(
            "export",
            path=path,
            rows=rows,
            file_format="csv" if "CSV" in selected else "json",
            scope=(
                "names_dates"
                if "names and dates" in chosen
                else "names" if "names only" in chosen
                else "all"
            ),
        )

    def closeEvent(self, event):
        if self.activity_busy():
            self.cancel()
            QMessageBox.information(
                self,
                "Stopping",
                "The current task is stopping. Please wait for it to finish, then close the window.",
            )
            event.ignore()
            return
        self.connections.stop()
        if self.catalog_loads.busy or self.connections.busy:
            self.catalog_loads.stop()
            self.close_after_load = True
            self.closing = True
            self.statusBar().showMessage(
                "Finishing the background checks before closing…"
            )
            event.ignore()
            return
        self.closing = True
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("header", self.table.horizontalHeader().saveState())
        event.accept()
