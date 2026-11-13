"""Application identity and paths. Keep settings names stable across releases."""

import os
from pathlib import Path

VERSION = "0.42"
APP_ID = "magik-games-library"
DISPLAY_NAME = "Magik Games Library"
SETTINGS_ORG = "Magik"
SETTINGS_APP = "GamesLibrary"
SOURCE_ROOT = Path(__file__).resolve().parent
ASSETS = SOURCE_ROOT / "assets"


def user_data_home():
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))


def data_root():
    return user_data_home() / APP_ID
