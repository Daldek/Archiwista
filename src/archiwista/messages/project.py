"""Project directories and the changes of a project's manifest."""

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
    "no_actions": Text(
        "The source {producer} does not create or change projects.",
        "Źródło {producer} nie tworzy ani nie zmienia projektów.",
    ),
    "locked": Text(
        "The project's manifest is locked ({lock})",
        "Manifest projektu jest zablokowany ({lock})",
    ),
    "not_discoverable": Text(
        (
            "A scan finds a project at most {depth} levels below a project"
            " directory, outside hidden directories and stores; {path} is no such"
            " place."
        ),
        (
            "Skan znajduje projekt najwyżej {depth} poziomy pod katalogiem"
            " projektów, poza katalogami ukrytymi i magazynami; {path} nie jest"
            " takim miejscem."
        ),
    ),
    "not_found": Text(
        'There is no project "{project}".',
        "Nie ma projektu „{project}”.",
    ),
    "other_producer": Text(
        (
            'The project "{project}" is a project of the source {project_producer},'
            " not of {producer}."
        ),
        "Projekt „{project}” jest projektem źródła {project_producer}, nie {producer}.",
    ),
    "outside_project_dirs": Text(
        (
            "A new project lies in a project directory of the settings or below one"
            " ({dirs}), given as an absolute path: {path}"
        ),
        (
            "Nowy projekt leży w katalogu projektów z ustawień albo pod nim ({dirs}),"
            " podany jako ścieżka bezwzględna: {path}"
        ),
    ),
}
