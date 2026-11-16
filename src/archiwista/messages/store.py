"""Stores: readable or not, and their kinds."""

from archiwista.messages import Text

MESSAGES = {
    "unreadable": Text(
        "Cannot read store {path}",
        "Nie można odczytać magazynu {path}",
    ),
    "kind_local": Text(
        "local disk",
        "dysk lokalny",
    ),
    "kind_share": Text(
        "network share",
        "udział sieciowy",
    ),
}
