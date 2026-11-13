"""Detached process handoff and launch activity reporting."""

from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal
from contracts import LogEntry, Severity
from installations import command, validate, check_provider, LaunchError
from launch_commands import override_command


class Launches(QObject):
    message = Signal(str)
    event = Signal(object)

    def __init__(self, log_path, parent=None):
        super().__init__(parent)
        self.log_path = Path(log_path)

    def log(self, message, severity=Severity.INFO):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.exists() and self.log_path.stat().st_size > 1024 * 1024:
                self.log_path.replace(self.log_path.with_suffix(".previous.log"))
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(
                    datetime.now(timezone.utc).isoformat(timespec="seconds")
                    + " "
                    + message
                    + "\n"
                )
        except OSError:
            pass
        self.message.emit(message)
        self.event.emit(LogEntry(message, severity))

    def launch(self, entry, options, override=None):
        validate(entry)
        if override:
            executable, arguments, cwd, env = override_command(override)
            process = QProcess()
            process.setProgram(executable)
            process.setArguments(arguments)
            if cwd:
                process.setWorkingDirectory(cwd)
            environment = QProcessEnvironment.systemEnvironment()
            for key, value in env.items():
                environment.insert(key, value)
            process.setProcessEnvironment(environment)
            started, pid = process.startDetached()
            if not started:
                raise LaunchError("Could not start the configured game command.")
            self.log(
                f"Launch request sent to your chosen program: {entry.get('title') or entry['record_id']} [PID {pid}]. This does not confirm the game is running.",
                Severity.SUCCESS,
            )
            return pid
        args = command(entry, options)
        check_provider(args)
        # Start a new launcher process independently so closing the catalog cannot kill a game.
        # QProcess reports failure to hand off; actual game runtime is owned by the provider.
        started, pid = QProcess.startDetached(args[0], args[1:])
        if not started:
            raise LaunchError(
                "Could not start "
                + entry["provider"]
                + ". Check the launcher executable and permissions."
            )
        self.log(
            f"Launch request sent to {entry['provider']}: {entry.get('title') or entry['record_id']} [ID {entry['record_id']}, PID {pid}]. This does not confirm the game is running.",
            Severity.SUCCESS,
        )
        return pid
