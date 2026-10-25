"""References to objects and paths that leave their root."""

from archiwista.messages import Text

MESSAGES = {
    "path_outside_root": Text(
        'The path "{path}" lies outside the store or project directory.',
        "Ścieżka „{path}” wychodzi poza katalog magazynu albo projektu.",
    ),
    "invalid": Text(
        (
            '"{ref}" is not an object reference: version:<store>:<path>,'
            " file:<project>:<path> or snapshot:<project>:<label>:<path>."
        ),
        (
            "„{ref}” nie jest odwołaniem do obiektu: version:<magazyn>:<ścieżka>,"
            " file:<projekt>:<ścieżka> albo snapshot:<projekt>:<etykieta>:<ścieżka>."
        ),
    ),
}
