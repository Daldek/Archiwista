"""References to objects, paths that leave their root, folders not read."""

from archiwista.messages import Text

MESSAGES = {
    "path_outside_root": Text(
        'The path "{path}" lies outside the store or project directory.',
        "Ścieżka „{path}” wychodzi poza katalog magazynu albo projektu.",
    ),
    "folder_invalid": Text(
        (
            'The data folder {path} of the project "{project}" {reason}: none of'
            " its files and snapshots is read until it is fixed."
        ),
        (
            "Folder danych {path} projektu „{project}” {reason}: żaden jego plik"
            " ani migawka nie są odczytywane, dopóki tego nie naprawisz."
        ),
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
