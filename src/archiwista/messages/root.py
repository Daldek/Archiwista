"""Producer directories of a store and their checks."""

from archiwista.messages import Text

MESSAGES = {
    "missing": Text(
        (
            'The {producer} directory of store "{store}" does not exist or the'
            " network share is not connected: {path}"
        ),
        (
            "Katalog {producer} magazynu „{store}” nie istnieje albo udział nie jest"
            " podłączony: {path}"
        ),
    ),
    "not_directory": Text(
        'The {producer} path of store "{store}" is not a directory: {path}',
        "Ścieżka {producer} magazynu „{store}” nie jest katalogiem: {path}",
    ),
    "unreadable": Text(
        'No permission to read the {producer} directory of store "{store}": {path}',
        "Brak uprawnień do odczytu katalogu {producer} magazynu „{store}”: {path}",
    ),
    "nested": Text(
        (
            "Directory {path} is located inside directory {other} — producer"
            " directories cannot be nested"
        ),
        (
            "Katalog {path} leży wewnątrz katalogu {other} — katalogi producentów nie"
            " mogą być zagnieżdżone"
        ),
    ),
    "in_store": Text(
        (
            "Directory {path} is located inside the store {other} (it holds"
            " {marker}) — a store cannot be nested in another store"
        ),
        (
            "Katalog {path} leży wewnątrz magazynu {other} (jest w nim {marker}) —"
            " magazyn nie może być zagnieżdżony w innym magazynie"
        ),
    ),
    "holds_store": Text(
        (
            "Directory {path} contains the store {other} (it holds {marker}) — a"
            " store cannot be nested in another store"
        ),
        (
            "Katalog {path} zawiera magazyn {other} (jest w nim {marker}) — magazyn"
            " nie może być zagnieżdżony w innym magazynie"
        ),
    ),
    "source": Text(
        (
            'The {producer} directory of store "{store}" is not a compatible store'
            " ({status})"
        ),
        "Katalog {producer} magazynu „{store}” nie jest zgodnym magazynem ({status})",
    ),
}
