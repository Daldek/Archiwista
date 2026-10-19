"""Polish texts of the projects' own data (plan v0.2, decision 8).

The settings problems of a data folder (``own_data_dir_<code>``), the
problems of a folder, its files and snapshots with their fixes
(``problem_<code>``, ``fix_<code>``; ``archiwista.services.problems``), the
reasons a folder is refused (``own_folder_reason_<reason>``) and the
``own_scan`` job.
"""

from types import MappingProxyType

OWN_DATA_MESSAGES = MappingProxyType(
    {
        # Local index queries (422 validation_error).
        "index_invalid_own_state": (
            "Nieznany stan pliku „{state}” — dozwolone: {allowed}."
        ),
        # A data folder in the settings (``AppSettings.own_data_dirs``).
        "own_data_dir_missing": "Folder danych projektu {project} nie istnieje: {path}",
        "own_data_dir_not_directory": (
            "Folder danych projektu {project} nie jest katalogiem: {path}"
        ),
        "own_data_dir_unreadable": (
            "Brak uprawnień do odczytu folderu danych projektu {project}: {path}"
        ),
        "own_data_dir_inside_store": (
            "Folder danych {path} leży w magazynie ({other}) — migawka nie może"
            " trafić do magazynu"
        ),
        "own_data_dir_inside_app_data": (
            "Folder danych {path} nakłada się na katalog danych Archiwisty ({other})"
        ),
        "own_data_dir_overlaps_project": (
            "Folder danych {path} nakłada się na folder danych innego projektu"
            " ({other}) — plik należy do jednego projektu"
        ),
        "fix_own_data_dir": (
            "wskaż projektowi istniejący folder danych poza magazynami, folderami"
            " innych projektów i katalogiem danych Archiwisty albo usuń wpis"
            " own_data_dirs (folder domyślny: <katalog projektu>/dane)."
        ),
        # Why a data folder is not used (``own_folder_invalid``).
        "own_folder_reason_inside_store": "leży w magazynie",
        "own_folder_reason_inside_app_data": (
            "nakłada się na katalog danych Archiwisty"
        ),
        "own_folder_reason_overlaps_project": (
            "zawiera folder danych innego projektu albo w nim leży"
        ),
        # Why a file was not read (``own_file_unreadable``).
        "own_read_error_unsupported_format": (
            "format nieobsługiwany albo plik wskazujący inne pliki"
        ),
        "own_read_error_unreadable": "plik uszkodzony albo nieczytelny",
        "own_read_error_timeout": "odczyt przekroczył 30 s",
        "own_read_error_memory_limit": "odczyt przekroczył limit pamięci",
        "own_read_error_inconsistent": "plik zmieniał się w trakcie odczytu",
        "own_read_error_invalid_name": "nazwa pliku nie jest poprawnym UTF-8",
        # Problems of a folder, its files and snapshots, with their fixes.
        "problem_own_folder_unreadable": "Nie można odczytać folderu danych: {path}",
        "fix_own_folder_unreadable": (
            "Podłącz udział albo nadaj użytkownikowi uruchamiającemu Archiwistę"
            " prawo odczytu i wejścia do folderu."
        ),
        "problem_own_folder_invalid": (
            "Folder danych {path} nie jest czytany: {reason}"
        ),
        "fix_own_folder_invalid": (
            "Administrator wskazuje projektowi inny folder danych, rozłączny"
            " z magazynami, z folderami innych projektów i z katalogiem danych"
            " Archiwisty."
        ),
        "problem_own_folder_too_large": (
            "Folder danych ma więcej niż {limit} plików — w indeksie jest"
            " pierwsze {limit} w porządku ścieżki: {path}"
        ),
        "fix_own_folder_too_large": (
            "Przenieś pliki archiwalne poza folder danych albo podziel go"
            " między projekty."
        ),
        "problem_own_file_unreadable": "Nie można odczytać pliku {path} ({reason})",
        "fix_own_file_unreadable": (
            "Sprawdź plik w programie GIS; jeśli był właśnie zapisywany, odśwież"
            " dane własne po zakończeniu edycji."
        ),
        "problem_invalid_snapshot": (
            "Migawka bez poprawnego opisu migawka.json: {path}"
        ),
        "fix_invalid_snapshot": (
            "Nie zmieniaj plików w katalogu .wersje; przywróć migawkę z kopii"
            " zapasowej — Archiwista nie poprawia ani nie usuwa migawek."
        ),
        "problem_unknown_snapshot_schema": (
            "Migawka w nieznanym formacie {reason}: {path}"
        ),
        "fix_unknown_snapshot_schema": (
            "Migawkę zapisała nowsza Archiwista — zaktualizuj Archiwistę."
        ),
        "problem_snapshot_modified": (
            "Pliki migawki różnią się od jej opisu (rozmiar albo suma kontrolna):"
            " {path}"
        ),
        "fix_snapshot_modified": (
            "Przywróć migawkę z kopii zapasowej; Archiwista nie zmienia migawek."
        ),
        "problem_stale_snapshot_incoming": (
            "Pozostałość przerwanej migawki starsza niż 24 godziny: {path}"
        ),
        "fix_stale_snapshot_incoming": (
            "Gdy żadna migawka nie trwa, usuń ten katalog ręcznie — Archiwista go"
            " nie usuwa."
        ),
        "problem_path_outside_root": (
            "Dowiązanie symboliczne wychodzi poza folder danych: {path}"
        ),
        "fix_path_outside_root": (
            "Skopiuj dane do folderu danych zamiast dowiązania — Archiwista nie"
            " czyta plików spoza folderu."
        ),
        # The ``own_scan`` job.
        "job_kind_own_scan": "skan danych własnych",
        "own_scan_reader_failed": (
            "Nie można uruchomić procesu czytającego pliki danych własnych: {detail}"
        ),
    }
)
