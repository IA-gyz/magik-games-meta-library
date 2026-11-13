"""Optional metadata columns and configuration keys; no dependencies."""

SOURCES = ("IGDB", "ProtonDB", "SteamGridDB", "OpenCritic")
# Appended columns preserve existing saved column indexes.
COLUMNS = [
    ("igdb_rating", "IGDB users / 100"),
    ("igdb_critic_rating", "IGDB critics / 100"),
    ("igdb_genres", "IGDB genres"),
    ("igdb_themes", "IGDB themes"),
    ("igdb_modes", "IGDB game modes"),
    ("igdb_perspectives", "IGDB perspectives"),
    ("igdb_franchises", "IGDB franchises"),
    ("igdb_summary", "IGDB summary"),
    ("igdb_local_players", "IGDB local players (PC)"),
    ("igdb_local_coop", "IGDB local co-op players (PC)"),
    ("igdb_url", "IGDB page"),
    ("igdb_cover", "IGDB cover"),
    ("proton_tier", "ProtonDB rating"),
    ("proton_trending", "ProtonDB recent rating"),
    ("proton_confidence", "ProtonDB confidence"),
    ("proton_reports", "ProtonDB report count"),
    ("proton_url", "ProtonDB page"),
    ("sgdb_grid", "SteamGridDB cover"),
    ("sgdb_hero", "SteamGridDB banner"),
    ("sgdb_logo", "SteamGridDB logo"),
    ("sgdb_icon", "SteamGridDB icon"),
    ("sgdb_artists", "SteamGridDB artists"),
    ("sgdb_url", "SteamGridDB page"),
    ("oc_score", "OpenCritic average / 100"),
    ("oc_recommended", "OpenCritic recommended %"),
    ("oc_tier", "OpenCritic tier"),
    ("oc_reviews", "OpenCritic review count"),
    ("oc_url", "OpenCritic page"),
]
for _source in SOURCES:
    COLUMNS += [
        (_source.lower() + "_checked", _source + " last checked"),
        (_source.lower() + "_status", _source + " match status"),
    ]
FIELDS = [key for key, _ in COLUMNS]
NUMERIC = {
    "igdb_rating": 100,
    "igdb_critic_rating": 100,
    "igdb_local_players": None,
    "igdb_local_coop": None,
    "proton_reports": None,
    "oc_score": 100,
    "oc_recommended": 100,
    "oc_reviews": None,
}
OPTIONS = {"igdb_client_id", "igdb_client_secret", "sgdb_api_key", "opencritic_api_key"}
