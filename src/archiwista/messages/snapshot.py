"""Own-data snapshots: refusals, failures and warnings."""

from archiwista.messages import Text

MESSAGES = {
    "blocked_folder_invalid": Text(
        "Data folder {path} will not accept a snapshot: {reason}.",
        "Folder danych {path} nie przyjmie migawki: {reason}.",
    ),
    "blocked_folder_unavailable": Text(
        (
            "Data folder {path} does not exist or cannot be read — the snapshot will"
            " not be created."
        ),
        (
            "Folder danych {path} nie istnieje albo nie można go odczytać — migawka"
            " nie powstanie."
        ),
    ),
    "blocked_file_missing": Text(
        (
            "File {file} is missing from data folder {path} — refresh the project's"
            " own data."
        ),
        "Pliku {file} nie ma w folderze danych {path} — odśwież dane własne projektu.",
    ),
    "blocked_read_only_folder": Text(
        "No write permission in {path} — the snapshot cannot be created there.",
        "Brak prawa zapisu w {path} — migawka nie może tam powstać.",
    ),
    "blocked_insufficient_space": Text(
        (
            "Not enough space in data folder {path}: the snapshot needs {needed},"
            " free: {free}."
        ),
        (
            "Za mało miejsca w folderze danych {path}: migawka potrzebuje {needed},"
            " wolne {free}."
        ),
    ),
    "blocked_insufficient_work_space": Text(
        (
            "Not enough space in the Archiwista working directory {path}: the database"
            " copy needs {needed}, free: {free}."
        ),
        (
            "Za mało miejsca w katalogu roboczym Archiwisty {path}: kopia bazy"
            " potrzebuje {needed}, wolne {free}."
        ),
    ),
    "inconsistent_copy": Text(
        "File {file} changed during copying — finish editing and try again.",
        (
            "Plik {file} zmieniał się w trakcie kopiowania — zakończ edycję i spróbuj"
            " ponownie."
        ),
    ),
    "checksum_mismatch": Text(
        (
            "The saved copy {name} differs from what was read (SHA-256 checksum) —"
            " check the disk or network share and try again."
        ),
        (
            "Zapisana kopia {name} różni się od odczytanej (suma SHA-256) — sprawdź"
            " dysk albo udział sieciowy i spróbuj ponownie."
        ),
    ),
    "integrity_failed": Text(
        (
            "Database copy {file} fails the SQLite integrity check ({detail}) — the"
            " file may be corrupted."
        ),
        (
            "Kopia bazy {file} nie przechodzi sprawdzenia integralności SQLite"
            " ({detail}) — plik może być uszkodzony."
        ),
    ),
    "target_exists": Text(
        (
            "Snapshot {label} of file {file} was created at the same moment by another"
            " process; Archiwista does not overwrite it — try again."
        ),
        (
            "Migawka {label} pliku {file} powstała w tej samej chwili w innym"
            " procesie; Archiwista jej nie nadpisuje — spróbuj ponownie."
        ),
    ),
    "editing_detected": Text(
        (
            "File {file} is open in an editor or the editor did not close it: the"
            " snapshot will include only committed changes."
        ),
        (
            "Plik {file} jest otwarty w edytorze albo edytor go nie zamknął: migawka"
            " obejmie tylko zatwierdzone zmiany."
        ),
    ),
    "chmod_refused": Text(
        (
            "The file system did not mark the snapshot as read-only ({detail}) —"
            " protect it with directory permissions."
        ),
        (
            "System plików nie oznaczył migawki jako tylko do odczytu ({detail}) —"
            " chroń ją uprawnieniami folderu."
        ),
    ),
    "directory_sync_refused": Text(
        (
            "The file system did not confirm that the snapshot directory was written"
            " to disk ({detail})."
        ),
        "System plików nie potwierdził zapisu katalogu migawki na dysku ({detail}).",
    ),
    "not_indexed": Text(
        (
            "Snapshot {label} is saved, but the index does not know it yet — the next"
            " refresh of own data will add it."
        ),
        (
            "Migawka {label} jest zapisana, ale indeks jej jeszcze nie zna — doda ją"
            " najbliższe odświeżenie danych własnych."
        ),
    ),
}
