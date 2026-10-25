"""Project directories."""

from archiwista.messages import Text

MESSAGES = {
    "dir_missing": Text(
        "Project directory does not exist: {path}",
        "Katalog projektów nie istnieje: {path}",
    ),
    "dir_not_directory": Text(
        "Project directory path is not a directory: {path}",
        "Ścieżka katalogu projektów nie jest katalogiem: {path}",
    ),
    "dir_unreadable": Text(
        "No permission to read the project directory: {path}",
        "Brak uprawnień do odczytu katalogu projektów: {path}",
    ),
    "not_found": Text(
        'There is no project "{project}".',
        "Nie ma projektu „{project}”.",
    ),
}
