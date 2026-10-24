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
            "Folder danych przekracza limit skanowania (plików, wpisów,"
            " katalogów, migawek lub głębokości); indeks może nie obejmować"
            " wszystkich danych: {path}"
        ),
        "fix_own_folder_too_large": (
            "Przenieś nadmiar plików i migawek poza folder danych, ogranicz"
            " liczbę podkatalogów lub podziel dane między projekty."
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
        # Permissions (``project.write``).
        "permission_project_write": (
            "Migawkę i zmiany projektu robi tylko jego właściciel albo administrator."
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
        # Own data and snapshots over HTTP and the command line (step 9).
        "own_file_changed": (
            "Plik {path} projektu „{project}” zmienił się od ostatniego skanu"
            " danych własnych — odśwież dane własne projektu („Odśwież” albo"
            " POST /api/v1/projects/{project}/scan) i spróbuj ponownie."
        ),
        "own_snapshot_not_found": (
            "Plik {path} projektu „{project}” nie ma migawki {label}."
        ),
        # ``archiwista files``, ``file``, ``snapshot``, ``own-scan`` (decision 11).
        "cli_files_help": (
            "Pliki danych własnych projektu wg ścieżki, z folderem danych i zmianą"
            " od ostatniej migawki (--json: model OwnFileList); kolejna strona:"
            " --cursor."
        ),
        "cli_file_help": (
            "Karta pliku danych własnych: warstwy, zasięg, historia stanów,"
            " migawki i podgląd (--json: model OwnFileCard)."
        ),
        "cli_snapshot_help": (
            "Migawka pliku danych własnych do .wersje/ na pierwszym planie"
            " (--json: model JobDetail z wynikiem); --plan: plan migawki bez"
            " zapisu (model SnapshotPlan)."
        ),
        "cli_own_scan_help": (
            "Skan danych własnych na pierwszym planie, jak „Odśwież” (--json:"
            " model JobDetail z wynikiem); bez --project — wszystkie projekty."
        ),
        "cli_own_project_help": "Identyfikator projektu (pole project z API).",
        "cli_own_file_help": (
            "Ścieżka pliku w folderze danych (z /, np. sieci/kanalizacja.gpkg)"
            " albo jego file_id (16 znaków szesnastkowych)."
        ),
        "cli_files_q_help": "Słowa, które muszą wystąpić w ścieżce.",
        "cli_files_state_help": (
            "Tylko pliki w tym stanie (ok, unrecognized, unreadable, missing)"
            " albo o tej zmianie (unsnapshotted, unchanged, changed)."
        ),
        "cli_files_limit_help": "Liczba plików na stronie (1–200, domyślnie 50).",
        "cli_files_cursor_help": "next_cursor poprzedniej strony tych samych filtrów.",
        "cli_snapshot_note_help": "Notatka zapisywana w migawka.json.",
        "cli_snapshot_plan_help": (
            "Tylko plan migawki: co zostanie skopiowane, dokąd i czy coś ją"
            " blokuje; nic nie jest zapisywane."
        ),
        "cli_own_scan_project_help": "Tylko folder danych tego projektu.",
        "cli_own_failed": "Nie można odczytać danych własnych",
        "cli_own_state_ok": "w porządku",
        "cli_own_state_unrecognized": "nierozpoznany",
        "cli_own_state_unreadable": "nieczytelny",
        "cli_own_state_missing": "nie istnieje",
        "cli_own_state_invalid": "odrzucony przez reguły",
        "cli_own_change_unsnapshotted": "bez migawki",
        "cli_own_change_unchanged": "bez zmian od migawki",
        "cli_own_change_changed": "zmieniony od migawki",
        "cli_own_folder": (
            "{project}: folder danych {path} ({state}), plików {files}, {size},"
            " migawki {snapshots}; skan: {scanned}"
        ),
        "cli_own_problem": "Problem: {message} {instruction}",
        "cli_own_row": "{path}  {state}, {change}, migawek {snapshots}",
        "cli_own_no_files": "Brak plików.",
        "cli_own_card_title": "{ref} ({file_id}): {kind}, {format}, {size}",
        "cli_own_card_state": (
            "Stan: {state}, {change}; ostatnia migawka: {last}; zmieniony {modified}"
        ),
        "cli_own_card_path": "Plik: {path}",
        "cli_own_card_crs": "Układ: {crs}",
        "cli_own_card_layer": "Warstwa {name}: {geometry}, obiektów {count}",
        "cli_own_card_raster": "Raster: {width}×{height}, kanałów {bands}, {dtype}",
        "cli_own_card_snapshots": "Migawki ({count}):",
        "cli_own_card_snapshot": "  {label}  {created}  {size}  {state}{note}",
        "cli_own_card_preview": "Podgląd: {state}",
        "cli_snapshot_state_ok": "w porządku",
        "cli_snapshot_state_invalid": "bez poprawnego opisu",
        "cli_snapshot_state_modified": "pliki zmienione",
        "cli_snapshot_plan": (
            "Migawka {file}: {size} do {destination} (kopia {copy_method},"
            " treść {content_method})"
        ),
        "cli_snapshot_plan_unchanged": (
            "Ostatnia migawka {label} ({created}) ma tę treść — nowa ją powtórzy."
        ),
        "cli_snapshot_plan_blocked": "Migawka niemożliwa: {message}",
        "cli_snapshot_plan_free": "Wolne miejsce: {free}",
        "cli_snapshot_plan_warning": "Uwaga: {message}",
        "cli_snapshot_started": "Migawka: zadanie {job}.",
        "cli_snapshot_progress": "Migawka: etap {current}/{total} ({phase}).",
        "cli_snapshot_phase_copy": "kopiowanie",
        "cli_snapshot_phase_checksums": "sumy kontrolne",
        "cli_snapshot_phase_document": "opis migawka.json",
        "cli_snapshot_phase_rename": "przeniesienie na miejsce",
        "cli_snapshot_phase_published": "opublikowana",
        "cli_snapshot_notice": "Migawka: {message}",
        "cli_snapshot_cancelling": "Przerywam migawkę (zadanie {job})…",
        "cli_snapshot_created": (
            "Migawka {label} utworzona (zadanie {job}): {size}, SHA-256 treści"
            " {sha256}, {seconds} s."
        ),
        "cli_snapshot_unchanged": (
            "Bez nowej migawki (zadanie {job}): ostatnia migawka {label} ma tę treść."
        ),
        "cli_own_scan_started": "Skan danych własnych: zadanie {job}.",
        "cli_own_scan_progress": (
            "Skan danych własnych: projekt {current}/{total}, plików {files},"
            " odczytanych {read}."
        ),
        "cli_own_scan_notice": "Skan danych własnych: {message}",
        "cli_own_scan_cancelling": "Przerywam skan danych własnych (zadanie {job})…",
        "cli_own_scan_done": (
            "Skan danych własnych (zadanie {job}): projektów {projects}, plików"
            " {files} (nowe {new}, zmienione {changed}, brakujące {missing},"
            " nieczytelne {unreadable}), migawek {snapshots}, problemów"
            " {problems}; {seconds} s."
        ),
        "cli_own_job": "Zadanie {job} ({kind}): {state}.",
        "cli_own_job_failed": "Zadanie {job} ({kind}) {state}: {detail}",
    }
)
