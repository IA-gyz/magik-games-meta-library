"""JSON values in the existing QSettings store; no format or key migration."""

import json


def read_json_setting(settings, key, fallback):
    try:
        return json.loads(settings.value(key, json.dumps(fallback)))
    except (ValueError, TypeError):
        return fallback


def write_json_setting(settings, key, value):
    settings.setValue(key, json.dumps(value))
