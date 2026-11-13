"""Launch configuration dialogs, with compatibility service imports."""

from ui_actions import action_button
import json
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QTabWidget,
    QWidget,
    QLabel,
    QPlainTextEdit,
    QLineEdit,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
)
from installations import LaunchError
from launch_commands import override_command
from launch_service import Launches  # noqa: F401 — compatibility import


class InstallationSettings(QDialog):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Find installed games and choose launchers")
        self.resize(850, 620)
        self.fields = {}
        layout = QVBoxLayout(self)
        label = QLabel(
            "The app checks the usual Steam, Heroic and Lutris folders automatically, including Flatpak installations. Add a folder only if your launcher stores its data somewhere else.\nChoose the launcher’s data folder, not just a game folder: the app needs the launcher’s list of installed games. Scanning does not change launcher files."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        for kind, title, description in [
            (
                "steam",
                "Steam",
                "Choose the Steam folder containing steamapps/libraryfolders.vdf. The app also checks the game libraries listed in that file.",
            ),
            (
                "heroic",
                "Heroic",
                "Choose the Heroic settings folder containing gog_store, legendaryConfig or nile_config. The AppImage version can use this same folder.",
            ),
            (
                "lutris",
                "Lutris",
                "Choose the Lutris data folder containing pga.db. Games are linked automatically when their store IDs match. Use Link installation for other games.",
            ),
        ]:
            page = QWidget()
            form = QFormLayout(page)
            helptext = QLabel(
                description
                + "\nIf you use a separate launcher profile, you may need a script that starts the launcher with that profile. Select it below."
            )
            helptext.setWordWrap(True)
            form.addRow(helptext)
            roots = QPlainTextEdit(options.get("scan_" + kind + "_roots", ""))
            roots.setPlaceholderText(
                "Additional launcher data folders, one per line. Leave blank to use the usual folders."
            )
            self.fields["scan_" + kind + "_roots"] = roots
            form.addRow("Additional launcher data folders", roots)
            executable = QLineEdit(options.get("launch_" + kind + "_exe", ""))
            executable.setPlaceholderText("Leave blank for automatic detection.")
            executable.setToolTip(
                "Uses the launcher installed on your system. Flatpak launchers are detected separately. For a custom launcher profile, choose a script that opens it."
            )
            self.fields["launch_" + kind + "_exe"] = executable
            wrap = QWidget()
            row = QHBoxLayout(wrap)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(executable)
            browse = action_button("Browse…", "file")
            row.addWidget(browse)
            browse.clicked.connect(
                lambda checked=False, e=executable: self.choose_exe(e)
            )
            form.addRow("Launcher program or script", wrap)
            tabs.addTab(page, title)
        page = QWidget()
        form = QFormLayout(page)
        helptext = QLabel(
            "A Wine or Proton prefix is a folder that acts as a Windows environment for a launcher and its games. The app checks Steam libraries, ~/Games, ~/.wine and Lutris game folders automatically.\nAdd other prefix folders below: they contain drive_c or pfx/drive_c. The app reads Epic and EA installation records without changing them. These records do not guarantee that every game file is present. To play one of these games, choose a working script in its Launch setup."
        )
        helptext.setWordWrap(True)
        form.addRow(helptext)
        for key, label in [
            ("scan_prefix_roots", "Wine / Proton prefixes"),
            ("scan_ea_game_roots", "Additional EA game library folders"),
        ]:
            edit = QPlainTextEdit(options.get(key, ""))
            edit.setPlaceholderText(
                "Full folder paths, one per line (for example /home/toto/Games)."
            )
            self.fields[key] = edit
            form.addRow(label, edit)
        tabs.addTab(page, "Windows game environments")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choose_exe(self, edit):
        path = QFileDialog.getOpenFileName(
            self, "Choose launcher executable", edit.text()
        )[0]
        if path:
            edit.setText(path)

    def values(self):
        return {
            k: w.toPlainText().strip()
            if isinstance(w, QPlainTextEdit)
            else w.text().strip()
            for k, w in self.fields.items()
        }


class LaunchOverride(QDialog):
    """Explicit local configuration, never read from downloaded game metadata."""

    def __init__(self, title, value, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Launch setup — " + title)
        self.resize(760, 560)
        form = QFormLayout(self)
        helptext = QLabel(
            "Choose a program or script that already starts this game correctly. For a Windows game, the script must select its launcher, Wine or Proton version, and Windows environment (prefix).\nArguments are passed exactly as written; shell commands and variables are not expanded. Leave the program blank to use the default launcher again. This setup applies to every detected installation of this game in this store."
        )
        helptext.setWordWrap(True)
        form.addRow(helptext)
        self.program = QLineEdit(value.get("program", ""))
        browse = action_button("Browse…", "file")
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.program)
        row.addWidget(browse)
        browse.clicked.connect(self.choose)
        form.addRow("Program or script", wrap)
        self.args = QPlainTextEdit(
            json.dumps(value.get("args", []), ensure_ascii=False)
        )
        self.args.setToolTip(
            'Use a JSON list of separate arguments, for example ["--fullscreen"]. Keep [] if none are needed.'
        )
        form.addRow("Arguments (optional JSON list)", self.args)
        self.cwd = QLineEdit(value.get("cwd", ""))
        form.addRow("Working directory (optional)", self.cwd)
        self.env = QPlainTextEdit(json.dumps(value.get("env", {}), indent=2))
        self.env.setToolTip(
            'Use a JSON object, for example {"WINEPREFIX": "/home/toto/Games/example"}. Keep {} if none are needed.'
        )
        form.addRow("Environment variables (optional JSON)", self.env)
        self.error = QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def choose(self):
        path = QFileDialog.getOpenFileName(
            self, "Choose executable or game launch script"
        )[0]
        if path:
            self.program.setText(path)

    def save(self):
        try:
            self.value = {
                "program": self.program.text().strip(),
                "args": json.loads(self.args.toPlainText()),
                "cwd": self.cwd.text().strip(),
                "env": json.loads(self.env.toPlainText()),
            }
            if self.value["program"]:
                override_command(self.value)
            self.accept()
        except (ValueError, TypeError, LaunchError) as exc:
            self.error.setText(str(exc))
