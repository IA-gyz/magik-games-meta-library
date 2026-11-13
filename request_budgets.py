"""Per-fetch HTTP request caps; never a claim about the provider's remaining quota."""
from extra_schema import SOURCES

MAXIMUM = 1000000
DEFAULTS = {source: 50 if source == 'OpenCritic' else 0 for source in SOURCES}


def option_key(source):
    return 'request_budget_' + source


def request_limit(options, source):
    value = options.get(option_key(source), DEFAULTS[source])
    if type(value) is int:
        return min(MAXIMUM, value) if value >= 0 else DEFAULTS[source]
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 7:
        return min(MAXIMUM, int(value))
    return DEFAULTS[source]


class BudgetExhausted(Exception):
    """A local request cap was reached; this is not an unavailable game."""
