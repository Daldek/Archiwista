"""Own project data: folders and read errors."""

from archiwista.messages import Text

MESSAGES = {
    "data_dir_missing": Text(
        "The data directory of project {project} does not exist: {path}",
        "Folder danych projektu {project} nie istnieje: {path}",
    ),
    "data_dir_not_directory": Text(
        "The data directory of project {project} is not a directory: {path}",
        "Folder danych projektu {project} nie jest katalogiem: {path}",
    ),
    "data_dir_unreadable": Text(
        "No permission to read the data directory of project {project}: {path}",
        "Brak uprawnień do odczytu folderu danych projektu {project}: {path}",
    ),
    "data_dir_inside_store": Text(
        (
            "Data directory {path} is inside a store ({other}) — a snapshot cannot be"
            " placed in a store"
        ),
        (
            "Folder danych {path} leży w magazynie ({other}) — migawka nie może trafić"
            " do magazynu"
        ),
    ),
    "data_dir_inside_app_data": Text(
        "Data directory {path} overlaps the Archiwista data directory ({other})",
        "Folder danych {path} nakłada się na katalog danych Archiwisty ({other})",
    ),
    "data_dir_overlaps_project": Text(
        (
            "Data directory {path} overlaps the data directory of another project"
            " ({other}) — a file belongs to one project"
        ),
        (
            "Folder danych {path} nakłada się na folder danych innego projektu"
            " ({other}) — plik należy do jednego projektu"
        ),
    ),
    "folder_reason_inside_store": Text(
        "is inside a store",
        "leży w magazynie",
    ),
    "folder_reason_inside_app_data": Text(
        "overlaps the Archiwista data directory",
        "nakłada się na katalog danych Archiwisty",
    ),
    "folder_reason_overlaps_project": Text(
        "contains the data directory of another project or is inside it",
        "zawiera folder danych innego projektu albo w nim leży",
    ),
    "read_error_unsupported_format": Text(
        "unsupported format or a file that points to other files",
        "format nieobsługiwany albo plik wskazujący inne pliki",
    ),
    "read_error_unreadable": Text(
        "file is corrupted or unreadable",
        "plik uszkodzony albo nieczytelny",
    ),
    "read_error_timeout": Text(
        "read exceeded 30 s",
        "odczyt przekroczył 30 s",
    ),
    "read_error_memory_limit": Text(
        "read exceeded the memory limit",
        "odczyt przekroczył limit pamięci",
    ),
    "read_error_inconsistent": Text(
        "file changed during reading",
        "plik zmieniał się w trakcie odczytu",
    ),
    "read_error_invalid_name": Text(
        "file name is not valid UTF-8",
        "nazwa pliku nie jest poprawnym UTF-8",
    ),
    "scan_reader_failed": Text(
        "Cannot start the process that reads own data files: {detail}",
        "Nie można uruchomić procesu czytającego pliki danych własnych: {detail}",
    ),
    "file_not_found": Text(
        (
            'Project "{project}" has no file {file_id} in its own data — refresh the'
            " project's own data."
        ),
        (
            "Projekt „{project}” nie ma w danych własnych pliku {file_id} — odśwież"
            " dane własne projektu."
        ),
    ),
    "file_changed": Text(
        (
            'File {path} of project "{project}" has changed since the last scan of'
            ' own data — refresh the project\'s own data (the "Odśwież" button or POST'
            " /api/v1/projects/{project}/scan) and try again."
        ),
        (
            "Plik {path} projektu „{project}” zmienił się od ostatniego skanu danych"
            " własnych — odśwież dane własne projektu („Odśwież” albo POST"
            " /api/v1/projects/{project}/scan) i spróbuj ponownie."
        ),
    ),
    "snapshot_not_found": Text(
        'File {path} of project "{project}" has no snapshot {label}.',
        "Plik {path} projektu „{project}” nie ma migawki {label}.",
    ),
}
