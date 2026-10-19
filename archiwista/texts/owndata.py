"""Polish texts of the projects' own data (plan v0.2, decisions 8 and 9).

The settings problems of a data folder (``own_data_dir_<code>``), the
problems of a folder, its files and snapshots with their fixes
(``problem_<code>``, ``fix_<code>``; ``archiwista.services.problems``), the
reasons a folder is refused (``own_folder_reason_<reason>``), the
``own_scan`` job, and snapshots: why one is blocked
(``snapshot_blocked_<reason>``), why it failed (``snapshot_<code>``), its
warnings and the ``snapshot`` job.
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
        # Snapshots (``archiwista.owndata.snapshots``) and the ``snapshot`` job.
        "job_kind_snapshot": "migawka",
        "job_conflict_snapshot": (
            "Migawka tego pliku już trwa: zadanie {job} ({state}). Poczekaj na"
            " jego koniec."
        ),
        "own_file_not_found": (
            "Projekt „{project}” nie ma w danych własnych pliku {file_id} —"
            " odśwież dane własne projektu."
        ),
        "snapshot_blocked_folder_invalid": (
            "Folder danych {path} nie przyjmie migawki: {reason}."
        ),
        "snapshot_blocked_folder_unavailable": (
            "Folder danych {path} nie istnieje albo nie można go odczytać —"
            " migawka nie powstanie."
        ),
        "snapshot_blocked_file_missing": (
            "Pliku {file} nie ma w folderze danych {path} — odśwież dane własne"
            " projektu."
        ),
        "snapshot_blocked_read_only_folder": (
            "Brak prawa zapisu w {path} — migawka nie może tam powstać."
        ),
        "snapshot_blocked_insufficient_space": (
            "Za mało miejsca w folderze danych {path}: migawka potrzebuje {needed},"
            " wolne {free}."
        ),
        "snapshot_blocked_insufficient_work_space": (
            "Za mało miejsca w katalogu roboczym Archiwisty {path}: kopia bazy"
            " potrzebuje {needed}, wolne {free}."
        ),
        "snapshot_inconsistent_copy": (
            "Plik {file} zmieniał się w trakcie kopiowania — zakończ edycję"
            " i spróbuj ponownie."
        ),
        "snapshot_checksum_mismatch": (
            "Zapisana kopia {name} różni się od odczytanej (suma SHA-256) —"
            " sprawdź dysk albo udział sieciowy i spróbuj ponownie."
        ),
        "snapshot_integrity_failed": (
            "Kopia bazy {file} nie przechodzi sprawdzenia integralności SQLite"
            " ({detail}) — plik może być uszkodzony."
        ),
        "snapshot_target_exists": (
            "Migawka {label} pliku {file} powstała w tej samej chwili w innym"
            " procesie; Archiwista jej nie nadpisuje — spróbuj ponownie."
        ),
        "snapshot_editing_detected": (
            "Plik {file} jest otwarty w edytorze albo edytor go nie zamknął:"
            " migawka obejmie tylko zatwierdzone zmiany."
        ),
        "snapshot_chmod_refused": (
            "System plików nie oznaczył migawki jako tylko do odczytu ({detail})"
            " — chroń ją uprawnieniami folderu."
        ),
        "snapshot_directory_sync_refused": (
            "System plików nie potwierdził zapisu katalogu migawki na dysku ({detail})."
        ),
        "snapshot_not_indexed": (
            "Migawka {label} jest zapisana, ale indeks jej jeszcze nie zna —"
            " doda ją najbliższe odświeżenie danych własnych."
        ),
    }
)
