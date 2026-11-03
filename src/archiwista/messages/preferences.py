"""A person's own preferences: ``GET`` and ``PUT /preferences`` (ADR-047)."""

from archiwista.messages import Text

MESSAGES = {
    "server_not_absolute": Text(
        "the prefix on the server must be an absolute path",
        "prefiks na serwerze musi być ścieżką bezwzględną",
    ),
    "personal_blank": Text(
        "the prefix on your computer must not be empty",
        "prefiks na Twoim komputerze nie może być pusty",
    ),
    "unknown_basemap": Text(
        'No basemap "{basemap}" is configured (configured: {names}).',
        "Nie skonfigurowano podkładu „{basemap}” (skonfigurowane: {names}).",
    ),
}
