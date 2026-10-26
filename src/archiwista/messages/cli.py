"""Texts of the command line: help of commands and options, output and refusals."""

from archiwista.messages import Text

MESSAGES = {
    "description": Text(
        "Archiwista — a browser for a local data store.",
        "Archiwista — przeglądarka lokalnego magazynu danych.",
    ),
    "internal_error": Text(
        (
            "Unexpected program error; the traceback is above. Report it with the"
            " command and the Archiwista version."
        ),
        (
            "Nieoczekiwany błąd programu; ślad wywołań jest wyżej. Zgłoś go z"
            " poleceniem i wersją Archiwisty."
        ),
    ),
    "doctor_help": Text(
        "Checks the installation, data source plugins, stores and the port.",
        "Sprawdza instalację, wtyczki źródeł, magazyny i port.",
    ),
    "serve_help": Text(
        "Starts the Archiwista server on 127.0.0.1 and opens the browser.",
        "Uruchamia serwer Archiwisty na 127.0.0.1 i otwiera przeglądarkę.",
    ),
    "serve_host_help": Text(
        "listen address; without team mode only 127.0.0.1",
        "adres nasłuchu; bez trybu zespołu tylko 127.0.0.1",
    ),
    "serve_port_help": Text(
        "port (default from settings; 0 — any free port)",
        "port (domyślnie z ustawień; 0 — dowolny wolny)",
    ),
    "serve_no_browser_help": Text(
        "do not open the browser, only print the address",
        "nie otwieraj przeglądarki, tylko wypisz adres",
    ),
    "serve_access_log_help": Text(
        "enable the access log (token= values are hidden in it)",
        "włącz dziennik dostępu (wartości token= są w nim ukryte)",
    ),
    "token_help": Text(
        (
            "Issues a one-time agent session URL, valid for 5 min (or ends agent"
            " sessions: --revoke-all)."
        ),
        (
            "Wystawia jednorazowy adres sesji agenta, ważny 5 min (albo kończy sesje"
            " agentów: --revoke-all)."
        ),
    ),
    "token_port_help": Text(
        "server port in the URL (default from settings)",
        "port serwera w adresie (domyślnie z ustawień)",
    ),
    "token_json_help": Text(
        "print JSON like the POST /api/v1/session/tokens response",
        "wypisz JSON jak odpowiedź POST /api/v1/session/tokens",
    ),
    "token_revoke_all_help": Text(
        "end all agent sessions and invalidate unused tokens",
        "zakończ wszystkie sesje agentów i unieważnij niewykorzystane tokeny",
    ),
    "port_invalid": Text(
        "port must be a number from {minimum} to 65535",
        "port musi być liczbą od {minimum} do 65535",
    ),
    "verbose_help": Text(
        "show diagnostic messages on stderr (debug level)",
        "pokaż na stderr komunikaty diagnostyczne (poziom debug)",
    ),
    "quiet_help": Text(
        "show only errors on stderr (error level)",
        "pokaż na stderr tylko błędy (poziom error)",
    ),
    "log_options_exclusive": Text(
        "the --verbose and --quiet options are mutually exclusive",
        "opcje --verbose i --quiet wykluczają się",
    ),
    "usage_error": Text(
        "{prog}: {text}",
        "{prog}: {text}",
    ),
    "log_level_invalid": Text(
        (
            'The variable {variable} has the value "{value}", which is not a log'
            " level; allowed: {allowed}."
        ),
        (
            "Zmienna {variable} ma wartość „{value}”, która nie jest poziomem"
            " dziennika; dozwolone: {allowed}."
        ),
    ),
    "log_level_hint": Text(
        "Set the variable to one of the allowed values or remove it.",
        "Ustaw zmienną na jedną z dozwolonych wartości albo ją usuń.",
    ),
    "users_help": Text(
        "People's accounts and their roles (administrator only).",
        "Konta osób i ich role (tylko administrator).",
    ),
    "users_list_help": Text(
        "Lists accounts with roles and groups.",
        "Wypisuje konta z rolami i grupami.",
    ),
    "users_add_help": Text(
        "Creates an account (in v0.1 without a password or login).",
        "Zakłada konto (w v0.1 bez hasła i logowania).",
    ),
    "users_roles_help": Text(
        "Sets the roles of an account (no roles — regular user).",
        "Ustawia role konta (bez ról — zwykły użytkownik).",
    ),
    "users_remove_help": Text(
        "Removes the account from groups and sharing lists, then the account itself.",
        "Usuwa konto z grup i list udostępnienia, a potem samo konto.",
    ),
    "user_id_help": Text(
        "account identifier, e.g. anna.nowak",
        "identyfikator konta, np. anna.nowak",
    ),
    "name_help": Text(
        "display name (defaults to the identifier)",
        "nazwa wyświetlana (domyślnie identyfikator)",
    ),
    "role_help": Text(
        "role: admin (administrator) or store_writer (write access to the store)",
        "rola: admin (administrator) albo store_writer (zapis do magazynu)",
    ),
    "groups_help": Text(
        "Groups of people, e.g. departments (administrator only).",
        "Grupy osób, np. działy (tylko administrator).",
    ),
    "groups_list_help": Text(
        "Lists groups with their members.",
        "Wypisuje grupy z członkami.",
    ),
    "groups_add_help": Text(
        "Creates a group.",
        "Zakłada grupę.",
    ),
    "groups_members_help": Text(
        "Sets the members of a group (replaces the current ones).",
        "Ustawia członków grupy (zastępuje dotychczasowych).",
    ),
    "groups_remove_help": Text(
        "Removes a group and the project entries that refer to it.",
        "Usuwa grupę i wpisy projektów, które ją wskazują.",
    ),
    "group_id_help": Text(
        "group identifier, e.g. hydro",
        "identyfikator grupy, np. hydro",
    ),
    "member_help": Text(
        "member account identifier",
        "identyfikator konta członka",
    ),
    "share_help": Text(
        "Shows or sets who can see a project (project owner or administrator).",
        (
            "Pokazuje albo ustawia, kto widzi projekt (właściciel projektu albo"
            " administrator)."
        ),
    ),
    "project_help": Text(
        "project identifier, as in /api/v1/projects/{{id}}",
        "identyfikator projektu, jak w /api/v1/projects/{{id}}",
    ),
    "visibility_help": Text(
        (
            "public — everyone, users — selected people (--user), group — members of"
            " groups (--group), private — owner only; without this option the command"
            " only shows the sharing"
        ),
        (
            "public — wszyscy, users — wybrane osoby (--user), group — członkowie grup"
            " (--group), private — tylko właściciel; bez tej opcji polecenie tylko"
            " pokazuje udostępnienie"
        ),
    ),
    "share_user_help": Text(
        "person who can see the project (with --visibility users)",
        "osoba, która widzi projekt (z --visibility users)",
    ),
    "share_group_help": Text(
        "group whose members can see the project (with --visibility group)",
        "grupa, której członkowie widzą projekt (z --visibility group)",
    ),
    "owner_help": Text(
        "new project owner (account identifier)",
        "nowy właściciel projektu (identyfikator konta)",
    ),
    "share_needs_visibility": Text(
        "Specify --visibility to change the project's sharing.",
        "Podaj --visibility, aby zmienić udostępnienie projektu.",
    ),
    "json_help": Text(
        "print JSON like the API response",
        "wypisz JSON jak odpowiedź API",
    ),
    "state_help": Text(
        "Backup of the state database (accounts, groups, sharing, log).",
        "Kopia zapasowa bazy stanu (konta, grupy, udostępnienia, dziennik).",
    ),
    "state_export_help": Text(
        "Writes the state database as JSON archiwista-state/1.",
        "Zapisuje bazę stanu jako JSON archiwista-state/1.",
    ),
    "state_output_help": Text(
        "backup file (default: standard output)",
        "plik kopii (domyślnie standardowe wyjście)",
    ),
    "state_import_help": Text(
        "Restores the state database from a backup — into an empty database only.",
        "Odtwarza bazę stanu z kopii — tylko do pustej bazy.",
    ),
    "state_file_help": Text(
        'file written by "archiwista state export"',
        "plik zapisany przez „archiwista state export”",
    ),
    "state_exported": Text(
        "State database backup saved: {path}",
        "Zapisano kopię bazy stanu: {path}",
    ),
    "state_imported": Text(
        (
            "State database restored: accounts {users}, groups {groups}, projects"
            " {projects}, log entries {changes}."
        ),
        (
            "Odtworzono bazę stanu: konta {users}, grupy {groups}, projekty"
            " {projects}, wpisy dziennika {changes}."
        ),
    ),
    "state_unreadable": Text(
        "Cannot read file {path}: {detail}",
        "Nie można odczytać pliku {path}: {detail}",
    ),
    "admin_failed": Text(
        "Cannot run the command",
        "Nie można wykonać polecenia",
    ),
    "no_users": Text(
        "No accounts.",
        "Brak kont.",
    ),
    "no_groups": Text(
        "No groups.",
        "Brak grup.",
    ),
    "user_line": Text(
        "{id} — {name}; roles: {roles}; groups: {groups}",
        "{id} — {name}; role: {roles}; grupy: {groups}",
    ),
    "user_disabled": Text(
        " (disabled)",
        " (wyłączone)",
    ),
    "group_line": Text(
        "{id} — {name}; members: {members}",
        "{id} — {name}; członkowie: {members}",
    ),
    "user_removed": Text(
        'Account "{id}" removed.',
        "Usunięto konto „{id}”.",
    ),
    "group_removed": Text(
        'Group "{id}" removed.',
        "Usunięto grupę „{id}”.",
    ),
    "access_line": Text(
        'Project "{project}": {visibility}{entries}; owner: {owner}',
        "Projekt „{project}”: {visibility}{entries}; właściciel: {owner}",
    ),
    "access_default": Text(
        " (default visibility — the project has no entry of its own)",
        " (widoczność domyślna — projekt nie ma własnego wpisu)",
    ),
    "none": Text(
        "none",
        "brak",
    ),
    "status_help": Text(
        (
            "Archiwista state: versions, data sources, index and stores (like GET"
            " /api/v1/health)."
        ),
        (
            "Stan Archiwisty: wersje, źródła danych, indeks i magazyny (jak GET"
            " /api/v1/health)."
        ),
    ),
    "sources_help": Text(
        "Data producer plugins and their state (like GET /api/v1/sources).",
        "Wtyczki producentów danych i ich stan (jak GET /api/v1/sources).",
    ),
    "search_help": Text(
        (
            "Searches and filters the file catalog (like GET /api/v1/slots, options"
            " with the same names); next page: --cursor."
        ),
        (
            "Wyszukuje i filtruje katalog plików (jak GET /api/v1/slots, opcje o tych"
            " samych nazwach); kolejna strona: --cursor."
        ),
    ),
    "entry_help": Text(
        (
            "File card: all versions, current, full sheet, pins and problems (like GET"
            " /api/v1/stores/{{store}}/slots/{{slot}})."
        ),
        (
            "Karta pliku: wszystkie wersje, bieżąca, pełny arkusz, przypięcia i"
            " problemy (jak GET /api/v1/stores/{{store}}/slots/{{slot}})."
        ),
    ),
    "version_help": Text(
        (
            "Single version card: values from the index, raw sidecar and path (like"
            " GET /api/v1/stores/{{store}}/versions/{{version}})."
        ),
        (
            "Karta jednej wersji: wartości z indeksu, surowy sidecar i ścieżka (jak"
            " GET /api/v1/stores/{{store}}/versions/{{version}})."
        ),
    ),
    "projects_help": Text(
        "Projects you can see (like GET /api/v1/projects).",
        "Projekty, które widzisz (jak GET /api/v1/projects).",
    ),
    "project_card_help": Text(
        (
            "Project card: jobs, pins and problems (like GET"
            " /api/v1/projects/{{project}})."
        ),
        (
            "Karta projektu: zadania, przypięcia i problemy (jak GET"
            " /api/v1/projects/{{project}})."
        ),
    ),
    "store_id_help": Text(
        "store identifier from the settings, e.g. zespol",
        "identyfikator magazynu z ustawień, np. zespol",
    ),
    "slot_help": Text(
        "slot path in the store, like the slot field of search results",
        "ścieżka slotu w magazynie, jak pole slot wyników search",
    ),
    "version_path_help": Text(
        "version path, like the version.path field",
        "ścieżka wersji, jak pole version.path",
    ),
    "projects_store_help": Text(
        "only projects of this store",
        "tylko projekty tego magazynu",
    ),
    "search_q_help": Text(
        (
            "text to search for; every word must match: sheet designation, TERYT, KU,"
            " file name, product, version label, campaign, start of SHA-256"
        ),
        (
            "szukany tekst; pasować musi każde słowo: godło, TERYT, KU, nazwa pliku,"
            " produkt, etykieta wersji, kampania, początek SHA-256"
        ),
    ),
    "search_store_help": Text(
        "store identifier",
        "identyfikator magazynu",
    ),
    "search_product_help": Text(
        "product, e.g. nmt",
        "produkt, np. nmt",
    ),
    "search_country_help": Text(
        "country code, e.g. PL",
        "kod kraju, np. PL",
    ),
    "search_years_help": Text(
        "data year: 2023, 2020-2023, 2020- or -2023",
        "rok danych: 2023, 2020-2023, 2020- albo -2023",
    ),
    "search_unit_help": Text(
        "exact unit code: sheet designation, TERYT or KU",
        "dokładny kod jednostki: godło arkusza, TERYT albo KU",
    ),
    "search_versions_help": Text(
        (
            "rows: current (current ones, default), all, full_sheet, pinned or"
            " noncurrent_unpinned"
        ),
        (
            "wiersze: current (bieżące, domyślnie), all, full_sheet, pinned albo"
            " noncurrent_unpinned"
        ),
    ),
    "search_status_help": Text(
        "row state: ok, missing, no_sidecar, unreadable or unrecognized",
        "stan wiersza: ok, missing, no_sidecar, unreadable albo unrecognized",
    ),
    "search_project_help": Text(
        "only versions pinned in this project (key from archiwista projects)",
        "tylko wersje przypięte w tym projekcie (klucz z archiwista projects)",
    ),
    "search_location_help": Text(
        (
            "location: any (default), with (footprint or whole country) or none (no"
            " location)"
        ),
        (
            "położenie: any (domyślnie), with (obrys albo cały kraj) albo none (bez"
            " położenia)"
        ),
    ),
    "search_area_id_help": Text(
        "area saved via POST /api/v1/areas",
        "obszar zapisany przez POST /api/v1/areas",
    ),
    "search_bbox_help": Text(
        "rectangle min_x,min_y,max_x,max_y in the CRS from --bbox-crs",
        "prostokąt min_x,min_y,max_x,max_y w układzie z --bbox-crs",
    ),
    "search_bbox_crs_help": Text(
        "CRS of --bbox, e.g. EPSG:2180 (default EPSG:4326)",
        "układ współrzędnych --bbox, np. EPSG:2180 (domyślnie EPSG:4326)",
    ),
    "search_limit_help": Text(
        "number of rows per page: 1–200 (default 50)",
        "liczba wierszy na stronie: 1–200 (domyślnie 50)",
    ),
    "search_cursor_help": Text(
        "next_cursor of the previous page of the same query",
        "next_cursor poprzedniej strony tego samego zapytania",
    ),
    "read_failed": Text(
        "Cannot read the index",
        "Nie można odczytać indeksu",
    ),
    "status_line": Text(
        "Archiwista {version}; index: schema {schema}, {size}.",
        "Archiwista {version}; indeks: schemat {schema}, {size}.",
    ),
    "source_line": Text(
        "Source {producer} ({version}): {message}",
        "Źródło {producer} ({version}): {message}",
    ),
    "store_line": Text(
        (
            'Store "{store}" ({name}): {status}; slots {slots}, versions {versions},'
            " missing {missing}, issues {issues}; index from {indexed_at}; last full"
            " scan: {full_scan_at}."
        ),
        (
            "Magazyn „{store}” ({name}): {status}; sloty {slots}, wersje {versions},"
            " brakujące {missing}, problemy {issues}; indeks z {indexed_at}; ostatni"
            " pełny skan: {full_scan_at}."
        ),
    ),
    "store_job": Text(
        " Job: {kind}, {state}.",
        " Zadanie: {kind}, {state}.",
    ),
    "store_status_unknown": Text(
        "not scanned yet",
        "jeszcze nie zeskanowany",
    ),
    "store_status_available": Text(
        "available",
        "dostępny",
    ),
    "store_status_unavailable": Text(
        "unavailable",
        "niedostępny",
    ),
    "stale_line": Text(
        (
            'Note: store "{store}" is unavailable — the response is based on the'
            " index from {indexed_at}."
        ),
        (
            "Uwaga: magazyn „{store}” jest niedostępny — odpowiedź według indeksu z"
            " {indexed_at}."
        ),
    ),
    "never": Text(
        "never",
        "nigdy",
    ),
    "search_row": Text(
        "{store}  {slot}  (version {label}, data year {year})",
        "{store}  {slot}  (wersja {label}, rok danych {year})",
    ),
    "search_summary": Text(
        (
            "Rows: {count}. Location across the whole result — footprint: {footprint},"
            " country: {country}, none: {none}."
        ),
        (
            "Wierszy: {count}. Położenie w całym wyniku — obrys: {footprint}, kraj:"
            " {country}, brak: {none}."
        ),
    ),
    "search_next": Text(
        "Next page: --cursor {cursor}",
        "Następna strona: --cursor {cursor}",
    ),
    "no_rows": Text(
        "No results.",
        "Brak wyników.",
    ),
    "entry_title": Text(
        "{store}/{slot} — {name}",
        "{store}/{slot} — {name}",
    ),
    "entry_facts": Text(
        (
            "Segment: {segment}; unit: {unit}; product: {product}; country: {country};"
            " state: {status}."
        ),
        (
            "Segment: {segment}; jednostka: {unit}; produkt: {product}; kraj:"
            " {country}; stan: {status}."
        ),
    ),
    "version_line": Text(
        "  {path} — {label}, data year {year}{marks}",
        "  {path} — {label}, rok danych {year}{marks}",
    ),
    "version_current": Text(
        ", current",
        ", bieżąca",
    ),
    "version_full_sheet": Text(
        ", full sheet",
        ", pełny arkusz",
    ),
    "version_missing": Text(
        ", file missing",
        ", brak pliku",
    ),
    "version_pinned": Text(
        "; pinned in: {projects}",
        "; przypięta w: {projects}",
    ),
    "version_title": Text(
        "{store}/{path} (slot {slot})",
        "{store}/{path} (slot {slot})",
    ),
    "version_facts": Text(
        (
            "Label: {label}; data year: {year}; size: {size}; CRS: {crs}; SHA-256:"
            " {sha256}."
        ),
        (
            "Etykieta: {label}; rok danych: {year}; rozmiar: {size}; układ: {crs};"
            " SHA-256: {sha256}."
        ),
    ),
    "version_license": Text(
        "License: {license}; attribution: {attribution}.",
        "Licencja: {license}; atrybucja: {attribution}.",
    ),
    "path_line": Text(
        "Path: {path}",
        "Ścieżka: {path}",
    ),
    "problem_line": Text(
        "Problem: {message} {instruction}",
        "Problem: {message} {instruction}",
    ),
    "project_line": Text(
        (
            "{project} — {name}; manifests: {manifests}; tasks {tasks}, pins {pins},"
            " missing {missing}."
        ),
        (
            "{project} — {name}; manifesty: {manifests}; zadania {tasks}, przypięcia"
            " {pins}, brakujące {missing}."
        ),
    ),
    "manifest_item": Text(
        "{producer} (store {store})",
        "{producer} (magazyn {store})",
    ),
    "no_projects": Text(
        "No visible projects.",
        "Brak widocznych projektów.",
    ),
    "task_line": Text(
        "  task {task} ({producer}): {command}; state: {status}",
        "  zadanie {task} ({producer}): {command}; stan: {status}",
    ),
    "pin_line": Text(
        "  pin {version} ({producer}, task {task}): {state}",
        "  przypięcie {version} ({producer}, zadanie {task}): {state}",
    ),
    "reindex_help": Text(
        (
            "Rebuilds the index: a full scan of the store (of all stores without"
            " --store) run as a job in the foreground."
        ),
        (
            "Przebudowuje indeks: pełny skan magazynu (bez --store — wszystkich) jako"
            " zadanie, wykonywane na pierwszym planie."
        ),
    ),
    "reindex_store_help": Text(
        "store identifier from the settings",
        "identyfikator magazynu z ustawień",
    ),
    "preview_help": Text(
        (
            "Describes an object's preview (--json: PreviewInfo model), writes a"
            " thumbnail to a PNG file (--output), or builds the preview in the"
            " foreground (--build)."
        ),
        (
            "Opis podglądu obiektu (--json: model PreviewInfo), miniatura do pliku PNG"
            " (--output) albo budowa podglądu na pierwszym planie (--build)."
        ),
    ),
    "preview_ref_help": Text(
        (
            "Object reference copied from the API response (ref field), e.g."
            " version:zespol:nmt/…/plik.asc."
        ),
        (
            "Odwołanie do obiektu przepisane z odpowiedzi API (pole ref), np."
            " version:zespol:nmt/…/plik.asc."
        ),
    ),
    "preview_style_help": Text(
        (
            "Style of the thumbnail written by --output; defaults to the file's"
            " default style."
        ),
        "Styl miniatury zapisywanej przez --output; domyślnie styl domyślny pliku.",
    ),
    "preview_size_help": Text(
        "Side length of the thumbnail written by --output, in pixels (default 512).",
        "Bok miniatury zapisywanej przez --output w pikselach (domyślnie 512).",
    ),
    "preview_output_help": Text(
        (
            "Writes the thumbnail to a PNG file using the same rendering process and"
            " the same preview cache as the server."
        ),
        (
            "Zapisuje miniaturę do pliku PNG tym samym procesem renderującym i przez"
            " tę samą pamięć podglądów co serwer."
        ),
    ),
    "preview_build_help": Text(
        (
            "Builds the preview (local COG) in the foreground, including for a file"
            " above the automatic build thresholds, and prints the description after"
            " the build."
        ),
        (
            "Buduje podgląd (lokalny COG) na pierwszym planie, także pliku ponad progi"
            " budowy automatycznej, i podaje opis po budowie."
        ),
    ),
    "preview_failed": Text(
        "Cannot prepare the preview",
        "Nie można przygotować podglądu",
    ),
    "preview_title": Text(
        "{ref}: {kind}, preview {state}",
        "{ref}: {kind}, podgląd {state}",
    ),
    "preview_reason": Text(
        "Reason: {message} {fix}",
        "Powód: {message} {fix}",
    ),
    "preview_styles": Text(
        "Styles: {styles} (default: {default})",
        "Style: {styles} (domyślny: {default})",
    ),
    "preview_map": Text(
        "On the map: zoom levels {minzoom}–{maxzoom}, extent {bounds}",
        "Na mapie: powiększenia {minzoom}–{maxzoom}, zasięg {bounds}",
    ),
    "preview_job": Text(
        "Build: job {job} ({state})",
        "Budowa: zadanie {job} ({state})",
    ),
    "preview_written": Text(
        "Thumbnail written to {path} ({size} px, style {style}).",
        "Zapisano miniaturę {path} ({size} px, styl {style}).",
    ),
    "preview_build_started": Text(
        "Preview build: job {job}.",
        "Budowa podglądu: zadanie {job}.",
    ),
    "preview_build_progress": Text(
        (
            "Preview build: {current}/{total} (built {built}, from cache {cached},"
            " failed {failed})."
        ),
        (
            "Budowa podglądu: {current}/{total} (zbudowane {built}, z pamięci"
            " {cached}, nieudane {failed})."
        ),
    ),
    "preview_build_notice": Text(
        "Preview build: {message}",
        "Budowa podglądu: {message}",
    ),
    "preview_build_cancelling": Text(
        "Cancelling the preview build (job {job})…",
        "Przerywam budowę podglądu (zadanie {job})…",
    ),
    "preview_build_failed": Text(
        "Preview build (job {job}) {state}: {detail}",
        "Budowa podglądu (zadanie {job}) {state}: {detail}",
    ),
    "files_help": Text(
        (
            "Own data files of the project by path, with the data folder and the"
            " change since the last snapshot (--json: OwnFileList model); next page:"
            " --cursor."
        ),
        (
            "Pliki danych własnych projektu wg ścieżki, z folderem danych i zmianą od"
            " ostatniej migawki (--json: model OwnFileList); kolejna strona: --cursor."
        ),
    ),
    "file_help": Text(
        (
            "Own data file card: layers, extent, state history, snapshots and preview"
            " (--json: OwnFileCard model)."
        ),
        (
            "Karta pliku danych własnych: warstwy, zasięg, historia stanów, migawki i"
            " podgląd (--json: model OwnFileCard)."
        ),
    ),
    "snapshot_help": Text(
        (
            "Snapshot of an own data file into .wersje/ in the foreground (--json:"
            " JobDetail model with the result); --plan: snapshot plan without writing"
            " (SnapshotPlan model)."
        ),
        (
            "Migawka pliku danych własnych do .wersje/ na pierwszym planie (--json:"
            " model JobDetail z wynikiem); --plan: plan migawki bez zapisu (model"
            " SnapshotPlan)."
        ),
    ),
    "own_scan_help": Text(
        (
            'Scan of own data in the foreground, like the "Odśwież" button (--json:'
            " JobDetail model with the result); without --project — all projects."
        ),
        (
            "Skan danych własnych na pierwszym planie, jak „Odśwież” (--json: model"
            " JobDetail z wynikiem); bez --project — wszystkie projekty."
        ),
    ),
    "own_project_help": Text(
        "Project identifier (the project field from the API).",
        "Identyfikator projektu (pole project z API).",
    ),
    "own_file_help": Text(
        (
            "File path in the data folder (with /, e.g. sieci/kanalizacja.gpkg) or its"
            " file_id (16 hexadecimal characters)."
        ),
        (
            "Ścieżka pliku w folderze danych (z /, np. sieci/kanalizacja.gpkg) albo"
            " jego file_id (16 znaków szesnastkowych)."
        ),
    ),
    "files_q_help": Text(
        "Words that must appear in the path.",
        "Słowa, które muszą wystąpić w ścieżce.",
    ),
    "files_state_help": Text(
        (
            "Only files in this state (ok, unrecognized, unreadable, missing) or with"
            " this change (unsnapshotted, unchanged, changed)."
        ),
        (
            "Tylko pliki w tym stanie (ok, unrecognized, unreadable, missing) albo o"
            " tej zmianie (unsnapshotted, unchanged, changed)."
        ),
    ),
    "files_limit_help": Text(
        "Number of files per page (1–200, default 50).",
        "Liczba plików na stronie (1–200, domyślnie 50).",
    ),
    "files_cursor_help": Text(
        "next_cursor of the previous page with the same filters.",
        "next_cursor poprzedniej strony tych samych filtrów.",
    ),
    "snapshot_note_help": Text(
        "Note written to migawka.json.",
        "Notatka zapisywana w migawka.json.",
    ),
    "snapshot_plan_help": Text(
        (
            "Snapshot plan only: what will be copied, where to, and whether anything"
            " blocks it; nothing is written."
        ),
        (
            "Tylko plan migawki: co zostanie skopiowane, dokąd i czy coś ją blokuje;"
            " nic nie jest zapisywane."
        ),
    ),
    "own_scan_project_help": Text(
        "Only the data folder of this project.",
        "Tylko folder danych tego projektu.",
    ),
    "own_failed": Text(
        "Cannot read own data",
        "Nie można odczytać danych własnych",
    ),
    "own_state_ok": Text(
        "OK",
        "w porządku",
    ),
    "own_state_unrecognized": Text(
        "unrecognized",
        "nierozpoznany",
    ),
    "own_state_unreadable": Text(
        "unreadable",
        "nieczytelny",
    ),
    "own_state_missing": Text(
        "missing",
        "nie istnieje",
    ),
    "own_state_invalid": Text(
        "rejected by rules",
        "odrzucony przez reguły",
    ),
    "own_change_unsnapshotted": Text(
        "no snapshot",
        "bez migawki",
    ),
    "own_change_unchanged": Text(
        "unchanged since snapshot",
        "bez zmian od migawki",
    ),
    "own_change_changed": Text(
        "changed since snapshot",
        "zmieniony od migawki",
    ),
    "own_folder": Text(
        (
            "{project}: data folder {path} ({state}), files: {files}, {size},"
            " snapshots: {snapshots}; scan: {scanned}"
        ),
        (
            "{project}: folder danych {path} ({state}), plików {files}, {size},"
            " migawki {snapshots}; skan: {scanned}"
        ),
    ),
    "own_problem": Text(
        "Problem: {message} {instruction}",
        "Problem: {message} {instruction}",
    ),
    "own_row": Text(
        "{path}  {state}, {change}, snapshots: {snapshots}",
        "{path}  {state}, {change}, migawek {snapshots}",
    ),
    "own_no_files": Text(
        "No files.",
        "Brak plików.",
    ),
    "own_card_title": Text(
        "{ref} ({file_id}): {kind}, {format}, {size}",
        "{ref} ({file_id}): {kind}, {format}, {size}",
    ),
    "own_card_state": Text(
        "State: {state}, {change}; last snapshot: {last}; modified {modified}",
        "Stan: {state}, {change}; ostatnia migawka: {last}; zmieniony {modified}",
    ),
    "own_card_path": Text(
        "File: {path}",
        "Plik: {path}",
    ),
    "own_card_crs": Text(
        "CRS: {crs}",
        "Układ: {crs}",
    ),
    "own_card_layer": Text(
        "Layer {name}: {geometry}, features: {count}",
        "Warstwa {name}: {geometry}, obiektów {count}",
    ),
    "own_card_raster": Text(
        "Raster: {width}×{height}, bands: {bands}, {dtype}",
        "Raster: {width}×{height}, kanałów {bands}, {dtype}",
    ),
    "own_card_snapshots": Text(
        "Snapshots ({count}):",
        "Migawki ({count}):",
    ),
    "own_card_snapshot": Text(
        "  {label}  {created}  {size}  {state}{note}",
        "  {label}  {created}  {size}  {state}{note}",
    ),
    "own_card_preview": Text(
        "Preview: {state}",
        "Podgląd: {state}",
    ),
    "snapshot_state_ok": Text(
        "OK",
        "w porządku",
    ),
    "snapshot_state_invalid": Text(
        "no valid description",
        "bez poprawnego opisu",
    ),
    "snapshot_state_modified": Text(
        "files modified",
        "pliki zmienione",
    ),
    "snapshot_plan": Text(
        (
            "Snapshot of {file}: {size} to {destination} (copy {copy_method}, content"
            " {content_method})"
        ),
        (
            "Migawka {file}: {size} do {destination} (kopia {copy_method}, treść"
            " {content_method})"
        ),
    ),
    "snapshot_plan_unchanged": Text(
        (
            "The last snapshot {label} ({created}) has this content — the new one will"
            " duplicate it."
        ),
        "Ostatnia migawka {label} ({created}) ma tę treść — nowa ją powtórzy.",
    ),
    "snapshot_plan_blocked": Text(
        "Snapshot not possible: {message}",
        "Migawka niemożliwa: {message}",
    ),
    "snapshot_plan_free": Text(
        "Free space: {free}",
        "Wolne miejsce: {free}",
    ),
    "snapshot_plan_warning": Text(
        "Warning: {message}",
        "Uwaga: {message}",
    ),
    "snapshot_started": Text(
        "Snapshot: job {job}.",
        "Migawka: zadanie {job}.",
    ),
    "snapshot_progress": Text(
        "Snapshot: step {current}/{total} ({phase}).",
        "Migawka: etap {current}/{total} ({phase}).",
    ),
    "snapshot_phase_copy": Text(
        "copying",
        "kopiowanie",
    ),
    "snapshot_phase_checksums": Text(
        "checksums",
        "sumy kontrolne",
    ),
    "snapshot_phase_document": Text(
        "migawka.json description",
        "opis migawka.json",
    ),
    "snapshot_phase_rename": Text(
        "moving into place",
        "przeniesienie na miejsce",
    ),
    "snapshot_phase_published": Text(
        "published",
        "opublikowana",
    ),
    "snapshot_notice": Text(
        "Snapshot: {message}",
        "Migawka: {message}",
    ),
    "snapshot_cancelling": Text(
        "Cancelling the snapshot (job {job})…",
        "Przerywam migawkę (zadanie {job})…",
    ),
    "snapshot_created": Text(
        (
            "Snapshot {label} created (job {job}): {size}, content SHA-256 {sha256},"
            " {seconds} s."
        ),
        (
            "Migawka {label} utworzona (zadanie {job}): {size}, SHA-256 treści"
            " {sha256}, {seconds} s."
        ),
    ),
    "snapshot_unchanged": Text(
        "No new snapshot (job {job}): the latest snapshot {label} has this content.",
        "Bez nowej migawki (zadanie {job}): ostatnia migawka {label} ma tę treść.",
    ),
    "own_scan_started": Text(
        "Own data scan: job {job}.",
        "Skan danych własnych: zadanie {job}.",
    ),
    "own_scan_progress": Text(
        "Own data scan: project {current}/{total}, files: {files}, read: {read}.",
        (
            "Skan danych własnych: projekt {current}/{total}, plików {files},"
            " odczytanych {read}."
        ),
    ),
    "own_scan_notice": Text(
        "Own data scan: {message}",
        "Skan danych własnych: {message}",
    ),
    "own_scan_cancelling": Text(
        "Cancelling the own data scan (job {job})…",
        "Przerywam skan danych własnych (zadanie {job})…",
    ),
    "own_scan_done": Text(
        (
            "Own data scan (job {job}): projects: {projects}, files: {files} (new:"
            " {new}, changed: {changed}, missing: {missing}, unreadable: {unreadable}),"
            " snapshots: {snapshots}, problems: {problems}; {seconds} s."
        ),
        (
            "Skan danych własnych (zadanie {job}): projektów {projects}, plików"
            " {files} (nowe {new}, zmienione {changed}, brakujące {missing},"
            " nieczytelne {unreadable}), migawek {snapshots}, problemów {problems};"
            " {seconds} s."
        ),
    ),
    "own_job": Text(
        "Job {job} ({kind}): {state}.",
        "Zadanie {job} ({kind}): {state}.",
    ),
    "own_job_failed": Text(
        "Job {job} ({kind}) {state}: {detail}",
        "Zadanie {job} ({kind}) {state}: {detail}",
    ),
    "compare_help": Text(
        "Comparison of the metadata of two objects (--json: Comparison model).",
        "Porównanie metadanych dwóch obiektów (--json: model Comparison).",
    ),
    "compare_ref_help": Text(
        (
            "Object reference copied from the API response (ref field), e.g."
            " version:zespol:nmt/…/plik.asc."
        ),
        (
            "Odwołanie do obiektu przepisane z odpowiedzi API (pole ref), np."
            " version:zespol:nmt/…/plik.asc."
        ),
    ),
    "compare_schema": Text(
        "Layer schema (changes from A to B):",
        "Schemat warstw (zmiany z A na B):",
    ),
    "compare_layer_only_a": Text(
        "  layer only in A: {layer}",
        "  warstwa tylko w A: {layer}",
    ),
    "compare_layer_only_b": Text(
        "  layer only in B: {layer}",
        "  warstwa tylko w B: {layer}",
    ),
    "compare_layer": Text(
        "  layer {layer}:",
        "  warstwa {layer}:",
    ),
    "compare_field_added": Text(
        "    + field {name} ({type})",
        "    + pole {name} ({type})",
    ),
    "compare_field_removed": Text(
        "    - field {name} ({type})",
        "    - pole {name} ({type})",
    ),
    "compare_field_changed": Text(
        "    ~ field {name}: {type_a} → {type_b}",
        "    ~ pole {name}: {type_a} → {type_b}",
    ),
    "compare_failed": Text(
        "Cannot compare the objects",
        "Nie można porównać obiektów",
    ),
    "compare_true": Text(
        "yes",
        "tak",
    ),
    "compare_false": Text(
        "no",
        "nie",
    ),
    "compare_side": Text(
        "{side}: {title} ({ref})",
        "{side}: {title} ({ref})",
    ),
    "compare_same_content": Text(
        "Same file content (SHA-256).",
        "Ta sama treść pliku (SHA-256).",
    ),
    "compare_row": Text(
        "{mark} {label}: {a} | {b}",
        "{mark} {label}: {a} | {b}",
    ),
    "compare_summary": Text(
        "Differences: {differs} of {total} fields.",
        "Różnice: {differs} z {total} pól.",
    ),
    "layers_help": Text(
        (
            "Layers of years, campaigns and product releases in the store (--json:"
            " LayerSet model), with the area after refreshing its slots; --thumbnail"
            " writes the layer thumbnail to a PNG file."
        ),
        (
            "Warstwy lat, kampanii i wydań produktu w magazynie (--json: model"
            " LayerSet), z obszarem po odświeżeniu jego slotów; --thumbnail zapisuje"
            " miniaturę warstwy do pliku PNG."
        ),
    ),
    "layers_store_help": Text(
        "Store identifier from the settings.",
        "Identyfikator magazynu z ustawień.",
    ),
    "layers_product_help": Text(
        "Product, e.g. nmt.",
        "Produkt, np. nmt.",
    ),
    "layers_area_help": Text(
        (
            "Area identifier (POST /api/v1/areas); without it, only version counts for"
            " the whole store."
        ),
        (
            "Identyfikator obszaru (POST /api/v1/areas); bez niego tylko liczby wersji"
            " w całym magazynie."
        ),
    ),
    "layers_segment_help": Text(
        "Only this product segment (variant).",
        "Tylko ten segment (wariant) produktu.",
    ),
    "layers_group_help": Text(
        "year (default): one layer per data year; campaign: year split into campaigns.",
        "year (domyślnie): warstwa na rok danych; campaign: rok dzielony na kampanie.",
    ),
    "layers_thumbnail_help": Text(
        "Layer key (the key field) whose thumbnail is saved via --output.",
        "Klucz warstwy (pole key) do zapisania jej miniatury przez --output.",
    ),
    "layers_size_help": Text(
        "Side of the layer thumbnail in pixels (default 512).",
        "Bok miniatury warstwy w pikselach (domyślnie 512).",
    ),
    "layers_output_help": Text(
        (
            "PNG file for the layer thumbnail, drawn by the same rendering process and"
            " through the same preview cache as the server."
        ),
        (
            "Plik PNG miniatury warstwy, rysowanej tym samym procesem renderującym i"
            " przez tę samą pamięć podglądów co serwer."
        ),
    ),
    "layers_output_required": Text(
        "--thumbnail requires --output FILE.png.",
        "--thumbnail wymaga --output PLIK.png.",
    ),
    "layers_failed": Text(
        "Cannot read layers",
        "Nie można odczytać warstw",
    ),
    "layers_written": Text(
        "Saved thumbnail of layer {layer} to {path} ({size} px, style {style}).",
        "Zapisano miniaturę warstwy {layer} do {path} ({size} px, styl {style}).",
    ),
    "layers_heading": Text(
        "{store} · {product}: layers: {count}, area {area}",
        "{store} · {product}: {count} warstw, obszar {area}",
    ),
    "layers_whole_store": Text(
        "whole store",
        "cały magazyn",
    ),
    "layers_stale": Text(
        "Response from the index without refresh: {reason}.",
        "Odpowiedź z indeksu bez odświeżenia: {reason}.",
    ),
    "layers_layer": Text(
        "{key}  {title} · {subtitle} · versions {versions}, units {units}",
        "{key}  {title} · {subtitle} · wersje {versions}, jednostki {units}",
    ),
    "layers_formats": Text(
        "    formats: {formats}",
        "    formaty: {formats}",
    ),
    "layers_coverage": Text(
        "    {label}",
        "    {label}",
    ),
    "layers_preview": Text(
        "    previews: {ready}/{total} ({state}){job}",
        "    podglądy: {ready}/{total} ({state}){job}",
    ),
    "layers_preview_job": Text(
        ", job {job}",
        ", zadanie {job}",
    ),
    "commands_help": Text(
        (
            "Producers' commands: their catalog, a pasted line read into a call, a"
            " call checked without the network and its command line (--json: the"
            " models of /api/v1/commands)."
        ),
        (
            "Polecenia producentów: ich katalog, wklejona linia odczytana jako"
            " wywołanie, wywołanie sprawdzone bez sieci i jego linia polecenia (--json:"
            " modele /api/v1/commands)."
        ),
    ),
    "commands_list_help": Text(
        "Lists the commands of the producers' catalogs (--json: CommandList model).",
        "Wypisuje polecenia z katalogów producentów (--json: model CommandList).",
    ),
    "commands_only_producer_help": Text(
        "Only the commands of this producer, e.g. kartograf.",
        "Tylko polecenia tego producenta, np. kartograf.",
    ),
    "commands_parse_help": Text(
        (
            "Reads a pasted command line of a producer into a call (--json:"
            " CommandCallItem model)."
        ),
        (
            "Odczytuje wklejoną linię polecenia producenta jako wywołanie (--json:"
            " model CommandCallItem)."
        ),
    ),
    "commands_line_help": Text(
        (
            "The command line in quotes, e.g. "
            '"kartograf sheet parse --sheet N-34-130-D-d-2-4".'
        ),
        (
            "Linia polecenia w cudzysłowie, np. "
            '"kartograf sheet parse --sheet N-34-130-D-d-2-4".'
        ),
    ),
    "commands_validate_help": Text(
        (
            "Checks a call of a command of the producer's catalog without the network"
            " (--json: CommandCallItem model)."
        ),
        (
            "Sprawdza wywołanie polecenia z katalogu producenta bez sieci (--json:"
            " model CommandCallItem)."
        ),
    ),
    "commands_store_help": Text(
        (
            "Store identifier from the settings, whose directory of the producer a"
            " command that works on a store is checked with."
        ),
        (
            "Identyfikator magazynu z ustawień, z którego katalogiem producenta jest"
            " sprawdzane polecenie działające na magazynie."
        ),
    ),
    "commands_format_help": Text(
        ("Writes the producer's command line of a call (--json: CommandLine model)."),
        (
            "Zapisuje linię polecenia producenta dla wywołania (--json: model"
            " CommandLine)."
        ),
    ),
    "commands_run_help": Text(
        (
            "What the line gives beside the options, as a JSON object, e.g. "
            '\'{{"root": "./data"}}\'.'
        ),
        (
            "To, co linia podaje poza opcjami, jako obiekt JSON, np. "
            '\'{{"root": "./data"}}\'.'
        ),
    ),
    "commands_producer_help": Text(
        "Producer identifier, e.g. kartograf.",
        "Identyfikator producenta, np. kartograf.",
    ),
    "commands_command_help": Text(
        'Command of the producer\'s catalog, e.g. "sheet parse".',
        "Polecenie z katalogu producenta, np. „sheet parse”.",
    ),
    "commands_options_help": Text(
        (
            "Options of the call as a JSON object, as the catalog names them, e.g. "
            '\'{{"sheet": "N-34-130-D-d-2-4"}}\'.'
        ),
        (
            "Opcje wywołania jako obiekt JSON, z nazwami z katalogu, np. "
            '\'{{"sheet": "N-34-130-D-d-2-4"}}\'.'
        ),
    ),
    "commands_json_object": Text(
        "must be a JSON object",
        "musi być obiektem JSON",
    ),
    "commands_failed": Text(
        "Cannot check the command",
        "Nie można sprawdzić polecenia",
    ),
    "commands_item": Text(
        "{producer} {command}: {summary}",
        "{producer} {command}: {summary}",
    ),
    "commands_none": Text(
        "No source offers commands.",
        "Żadne źródło nie udostępnia poleceń.",
    ),
    "commands_call": Text(
        "Command: {producer} {command}",
        "Polecenie: {producer} {command}",
    ),
    "commands_valid": Text(
        "The call is valid: {producer} {command}",
        "Wywołanie jest poprawne: {producer} {command}",
    ),
    "commands_options": Text(
        "Options: {options}",
        "Opcje: {options}",
    ),
    "commands_run": Text(
        "Beside the options: {run}",
        "Poza opcjami: {run}",
    ),
    "jobs_help": Text(
        (
            "Background jobs: start a job of a producer's command on a store, list"
            " and show jobs, cancel or retry one, read its plan and its log (--json:"
            " the models of /api/v1/jobs)."
        ),
        (
            "Zadania w tle: uruchomienie zadania polecenia producenta na magazynie,"
            " lista i podgląd zadań, anulowanie i ponowienie zadania, odczyt jego"
            " planu i dziennika (--json: modele z /api/v1/jobs)."
        ),
    ),
    "jobs_start_help": Text(
        (
            "Starts a job of calls of commands of the producer's catalog on a store"
            " (all the lines of a row in one job) and follows it to its end; check"
            " plans a run of each call without its effects, download runs them in"
            " the store (--json: the JobDetail model of the job as it ended)."
        ),
        (
            "Uruchamia zadanie wywołań poleceń z katalogu producenta na magazynie"
            " (wszystkie linie wiersza w jednym zadaniu) i śledzi je do końca; check"
            " planuje uruchomienie każdego wywołania bez jego skutków, download"
            " uruchamia je w magazynie (--json: model JobDetail zadania po jego"
            " końcu)."
        ),
    ),
    "jobs_kind_help": Text(
        (
            "Kind of the job: check (the plan of a run, over the network) or download"
            " (the run, over the network; it writes the store)."
        ),
        (
            "Rodzaj zadania: check (plan uruchomienia, przez sieć) albo download"
            " (uruchomienie, przez sieć; zapisuje magazyn)."
        ),
    ),
    "jobs_plan_job_help": Text(
        (
            "download only: the check job whose kept plans the run runs, a job of"
            " the same calls in the same order; each call fetches only its plan's"
            " positions to download."
        ),
        (
            "tylko download: zadanie check, którego zachowane plany uruchomić,"
            " zadanie tych samych wywołań w tej samej kolejności; każde wywołanie"
            " pobiera tylko pozycje do pobrania ze swojego planu."
        ),
    ),
    "jobs_call_help": Text(
        (
            "One call as a JSON object, a command of the producer's catalog on a"
            ' store with its options, e.g. \'{{"command": "elevation download",'
            ' "options": {{"sheet": "N-34-130-D-d-2-4"}}}}\'; --call once for each'
            " line, in their order."
        ),
        (
            "Jedno wywołanie jako obiekt JSON, polecenie z katalogu producenta na"
            ' magazynie z opcjami, np. \'{{"command": "elevation download",'
            ' "options": {{"sheet": "N-34-130-D-d-2-4"}}}}\'; --call raz dla każdej'
            " linii, w ich kolejności."
        ),
    ),
    "jobs_store_help": Text(
        "Store identifier from the settings: the calls work on its directory.",
        "Identyfikator magazynu z ustawień: wywołania działają na jego katalogu.",
    ),
    "jobs_plan_help": Text(
        (
            "Prints the plans a check job kept, a line of each call and its"
            " positions, without the network (--json: ActionPlanInfo model)."
        ),
        (
            "Wypisuje plany, które zachowało zadanie check, linię każdego wywołania"
            " i jego pozycje, bez sieci (--json: model ActionPlanInfo)."
        ),
    ),
    "jobs_job_help": Text(
        "Job identifier (the id of POST /api/v1/jobs).",
        "Identyfikator zadania (id z POST /api/v1/jobs).",
    ),
    "jobs_list_help": Text(
        (
            "Lists the jobs newest first, with who started each (--json: JobList"
            " model of GET /api/v1/jobs)."
        ),
        (
            "Wypisuje zadania od najnowszych, z tym, kto uruchomił każde (--json:"
            " model JobList z GET /api/v1/jobs)."
        ),
    ),
    "jobs_list_kind_help": Text(
        "Only jobs of this kind, e.g. scan, download.",
        "Tylko zadania tego rodzaju, np. scan, download.",
    ),
    "jobs_list_store_help": Text(
        "Only jobs of this store, also one no longer configured.",
        "Tylko zadania tego magazynu, także już nieskonfigurowanego.",
    ),
    "jobs_list_state_help": Text(
        "Only jobs in this state, e.g. running, failed, interrupted.",
        "Tylko zadania w tym stanie, np. running, failed, interrupted.",
    ),
    "jobs_list_project_help": Text(
        "Only jobs with this project's data.",
        "Tylko zadania z danymi tego projektu.",
    ),
    "jobs_list_limit_help": Text(
        "Page size.",
        "Liczba zadań na stronie.",
    ),
    "jobs_list_cursor_help": Text(
        "next_cursor of the previous page of the same filters.",
        "next_cursor poprzedniej strony z tymi samymi filtrami.",
    ),
    "jobs_show_help": Text(
        "Prints a job: its state, progress, and result or error (--json: JobDetail).",
        "Wypisuje zadanie: stan, postęp i wynik albo błąd (--json: model JobDetail).",
    ),
    "jobs_cancel_help": Text(
        (
            "Cancels a job that waits or runs, also one a running server supervises"
            " (--json: the JobDetail model right after the request)."
        ),
        (
            "Anuluje zadanie, które czeka albo trwa, także nadzorowane przez"
            " działający serwer (--json: model JobDetail tuż po żądaniu)."
        ),
    ),
    "jobs_retry_help": Text(
        (
            "Starts a job that did not succeed again as a new job and follows it to"
            " its end (--json: the JobDetail model of the new job as it ended)."
        ),
        (
            "Uruchamia ponownie zadanie, które się nie powiodło, jako nowe zadanie"
            " i śledzi je do końca (--json: model JobDetail nowego zadania po jego"
            " końcu)."
        ),
    ),
    "jobs_log_help": Text(
        (
            "Prints the end of a job's log: its worker's standard error (--json:"
            " JobLog model)."
        ),
        (
            "Wypisuje koniec dziennika zadania: standardowe wyjście błędów jego"
            " procesu roboczego (--json: model JobLog)."
        ),
    ),
    "jobs_list_line": Text(
        "{job}  {kind}: {state}, started by {actor} at {created}",
        "{job}  {kind}: {state}, uruchomił {actor} {created}",
    ),
    "jobs_list_none": Text(
        "No jobs.",
        "Brak zadań.",
    ),
    "jobs_list_next": Text(
        "More jobs: --cursor {cursor}",
        "Dalsze zadania: --cursor {cursor}",
    ),
    "jobs_cancel_requested": Text(
        "Cancelling: the job stops within {seconds} s.",
        "Anulowanie: zadanie zatrzyma się w ciągu {seconds} s.",
    ),
    "jobs_log_truncated": Text(
        "The log is longer: only its last MiB follows ({size} bytes in all).",
        "Dziennik jest dłuższy: poniżej tylko ostatni MiB ({size} bajtów w sumie).",
    ),
    "jobs_failed": Text(
        "Cannot run the job",
        "Nie można uruchomić zadania",
    ),
    "jobs_started": Text(
        "Job {job} started: {kind}.",
        "Zadanie {job} uruchomione: {kind}.",
    ),
    "jobs_notice": Text(
        "Job {job}: {message}",
        "Zadanie {job}: {message}",
    ),
    "jobs_cancelling": Text(
        "Cancelling job {job} ({kind})…",
        "Przerywam zadanie {job} ({kind})…",
    ),
    "jobs_job": Text(
        "Job {job} ({kind}): {state}.",
        "Zadanie {job} ({kind}): {state}.",
    ),
    "jobs_job_failed": Text(
        "Job {job} ({kind}) {state}: {detail}",
        "Zadanie {job} ({kind}) {state}: {detail}",
    ),
    "jobs_counts": Text(
        "Positions: {positions} ({counts}); to download: {todo}, {size}.",
        "Pozycje: {positions} ({counts}); do pobrania: {todo}, {size}.",
    ),
    "jobs_line": Text(
        "Command line of the run: {line}",
        "Linia polecenia uruchomienia: {line}",
    ),
    "jobs_call_failed": Text(
        "Call {place} of {count} failed: {line}: {detail}",
        "Wywołanie {place} z {count} nie powiodło się: {line}: {detail}",
    ),
    "jobs_call_not_planned": Text(
        "Call {place} of {count} skipped, its check failed: {line}",
        "Wywołanie {place} z {count} pominięte, jego sprawdzenie się nie powiodło:"
        " {line}",
    ),
    "jobs_call_nothing": Text(
        "Call {place} of {count} skipped, its plan has nothing to download: {line}",
        "Wywołanie {place} z {count} pominięte, jego plan nie ma nic do pobrania:"
        " {line}",
    ),
    "jobs_size": Text(
        "size {size}",
        "rozmiar {size}",
    ),
    "jobs_size_partial": Text(
        "size at least {size}",
        "rozmiar co najmniej {size}",
    ),
    "jobs_size_unknown": Text(
        "size unknown",
        "rozmiar nieznany",
    ),
    "jobs_plan": Text(
        "Plan of job {job} in the store {store}, checked {checked_at}:",
        "Plan zadania {job} w magazynie {store}, sprawdzony {checked_at}:",
    ),
    "jobs_plan_entry": Text(
        "  {status}: {path} ({local} → {available})",
        "  {status}: {path} ({local} → {available})",
    ),
    "jobs_no_label": Text(
        "none",
        "brak",
    ),
    "jobs_files": Text(
        "Files: {files} ({counts}); failed units: {failed}.",
        "Pliki: {files} ({counts}); jednostki z błędem: {failed}.",
    ),
    "jobs_project_tasks": Text(
        "Tasks: {tasks} ({counts}).",
        "Zadania projektu: {tasks} ({counts}).",
    ),
    "jobs_project_files": Text(
        "Files: {files} ({counts}); tasks without pins: {not_downloaded}.",
        "Pliki: {files} ({counts}); zadania bez przypięć: {not_downloaded}.",
    ),
    "jobs_warm": Text(
        (
            "Versions: {versions}, own files: {files}; prepared now {warmed},"
            " ready before {cached}, waiting for a build {needs_build}, failed"
            " {failed}, skipped {skipped}."
        ),
        (
            "Wersje: {versions}, pliki własne: {files}; przygotowane teraz {warmed},"
            " gotowe wcześniej {cached}, czekające na budowę {needs_build}, z błędem"
            " {failed}, pominięte {skipped}."
        ),
    ),
    "availability_help": Text(
        (
            "What the source has for an area: the last report and a check at the"
            " source (--json: the AvailabilityInfo model of /api/v1/availability)."
        ),
        (
            "Co źródło ma dla obszaru: ostatni raport i sprawdzenie u źródła (--json:"
            " model AvailabilityInfo z /api/v1/availability)."
        ),
    ),
    "availability_show_help": Text(
        (
            "Prints the last report of an area and a product from the index, without"
            " the network (--json: AvailabilityInfo model)."
        ),
        (
            "Wypisuje ostatni raport obszaru i produktu z indeksu, bez sieci (--json:"
            " model AvailabilityInfo)."
        ),
    ),
    "availability_check_help": Text(
        (
            "Asks the source what it has for an area and a product: a report younger"
            " than seven days answers at once, otherwise a job asks the source"
            " (--json: AvailabilityInfo model; a check that does not succeed:"
            " JobDetail)."
        ),
        (
            "Pyta źródło, co ma dla obszaru i produktu: raport młodszy niż siedem dni"
            " odpowiada od razu, w przeciwnym razie zadanie pyta źródło (--json: model"
            " AvailabilityInfo; sprawdzenie, które się nie udało: JobDetail)."
        ),
    ),
    "availability_area_help": Text(
        "Area identifier (the id of POST /api/v1/areas).",
        "Identyfikator obszaru (id z POST /api/v1/areas).",
    ),
    "availability_product_help": Text(
        "Product, e.g. nmt.",
        "Produkt, np. nmt.",
    ),
    "availability_producer_help": Text(
        "Producer identifier (default: kartograf).",
        "Identyfikator producenta (domyślnie: kartograf).",
    ),
    "availability_force_help": Text(
        "Ask the source even when a report younger than seven days is kept.",
        "Zapytaj źródło także wtedy, gdy jest raport młodszy niż siedem dni.",
    ),
    "availability_store_help": Text(
        "Configured store whose versions the badge of each variant counts.",
        "Skonfigurowany magazyn, którego wersje liczy plakietka każdego wariantu.",
    ),
    "availability_horizontal_help": Text(
        "Only variants of this sheet system or horizontal CRS (e.g. PL-1992).",
        "Tylko warianty tego układu arkuszy lub układu poziomego (np. PL-1992).",
    ),
    "availability_resolution_help": Text(
        "Only variants of this resolution (e.g. 1m).",
        "Tylko warianty tej rozdzielczości (np. 1m).",
    ),
    "availability_vertical_crs_help": Text(
        "Only variants of this height system (e.g. EVRF2007).",
        "Tylko warianty tego układu wysokości (np. EVRF2007).",
    ),
    "availability_failed": Text(
        "Cannot check the availability",
        "Nie można sprawdzić dostępności",
    ),
    "availability_started": Text(
        "Availability check: job {job}.",
        "Sprawdzenie dostępności: zadanie {job}.",
    ),
    "availability_notice": Text(
        "Availability check: {message}",
        "Sprawdzenie dostępności: {message}",
    ),
    "availability_cancelling": Text(
        "Cancelling the availability check (job {job})…",
        "Przerywam sprawdzenie dostępności (zadanie {job})…",
    ),
    "availability_job": Text(
        "Availability check (job {job}): {state}.",
        "Sprawdzenie dostępności (zadanie {job}): {state}.",
    ),
    "availability_job_failed": Text(
        "Availability check (job {job}) {state}: {detail}",
        "Sprawdzenie dostępności (zadanie {job}) {state}: {detail}",
    ),
    "availability_report": Text(
        (
            "Availability of {product} for the area {area} ({producer}), checked"
            " {checked_at}:"
        ),
        (
            "Dostępność {product} dla obszaru {area} ({producer}), sprawdzona"
            " {checked_at}:"
        ),
    ),
    "availability_row": Text(
        "  {year} {country}: {label}",
        "  {year} {country}: {label}",
    ),
    "availability_row_variant": Text(
        "{row}; variant {variant}",
        "{row}; wariant {variant}",
    ),
    "availability_row_more": Text(
        "{row} ({more})",
        "{row} ({more})",
    ),
    "availability_row_local": Text(
        "{row}; {local}",
        "{row}; {local}",
    ),
    "availability_no_year": Text(
        "no year",
        "bez roku",
    ),
    "availability_nothing": Text(
        "  The source has nothing for the area.",
        "  Źródło nie ma nic dla obszaru.",
    ),
    "availability_not_checked": Text(
        "  Not checked: {part}: {detail}",
        "  Nie sprawdzono: {part}: {detail}",
    ),
    "project_init_help": Text(
        (
            "Creates a project of a producer in a directory, bound to a configured"
            " store (--json: the ProjectCard model of POST /api/v1/projects)."
        ),
        (
            "Tworzy projekt producenta w katalogu, związany ze skonfigurowanym"
            " magazynem (--json: model ProjectCard z POST /api/v1/projects)."
        ),
    ),
    "project_directory_help": Text(
        (
            "Project directory, made when missing: a project directory of the"
            " settings or a directory at most four levels below one; a relative path"
            " is taken from the current directory."
        ),
        (
            "Katalog projektu, tworzony, gdy go brak: katalog projektów z ustawień"
            " albo katalog najwyżej cztery poziomy pod nim; ścieżka względna liczy"
            " się od bieżącego katalogu."
        ),
    ),
    "project_store_help": Text(
        (
            "Identifier of the configured store whose directory of the producer the"
            " project's manifest names."
        ),
        (
            "Identyfikator skonfigurowanego magazynu, którego katalog producenta"
            " wskazuje manifest projektu."
        ),
    ),
    "project_add_help": Text(
        (
            "Adds a task to a project through its producer: a command of the catalog"
            " with its options, checked without the network (--json: the ProjectCard"
            " model of POST /api/v1/projects/{{project}}/tasks)."
        ),
        (
            "Dodaje zadanie do projektu przez jego producenta: polecenie z katalogu z"
            " opcjami, sprawdzone bez sieci (--json: model ProjectCard z POST"
            " /api/v1/projects/{{project}}/tasks)."
        ),
    ),
    "project_task_help": Text(
        "Task name; the producer's rules apply, e.g. teren.",
        "Nazwa zadania; obowiązują zasady producenta, np. teren.",
    ),
    "project_command_help": Text(
        'Data command of the producer\'s catalog, e.g. "elevation download".',
        "Polecenie danych z katalogu producenta, np. „elevation download”.",
    ),
    "project_producer_help": Text(
        (
            "The producer whose manifest the command acts on; by default the"
            " project's only one."
        ),
        (
            "Producent, którego manifestu dotyczy polecenie; domyślnie jedyny"
            " manifest projektu."
        ),
    ),
    "project_remove_help": Text(
        (
            "Removes a task and its pins from a project through its producer; its"
            " files stay in the store (--json: the ProjectCard model of DELETE"
            " /api/v1/projects/{{project}}/tasks/{{name}})."
        ),
        (
            "Usuwa zadanie i jego przypięcia z projektu przez jego producenta; pliki"
            " zostają w magazynie (--json: model ProjectCard z DELETE"
            " /api/v1/projects/{{project}}/tasks/{{name}})."
        ),
    ),
    "project_status_help": Text(
        (
            "Asks the project's producer for its status now, without the network"
            " (--json: the ProjectStatus model of GET"
            " /api/v1/projects/{{project}}/status)."
        ),
        (
            "Pyta producenta projektu o jego stan teraz, bez sieci (--json: model"
            " ProjectStatus z GET /api/v1/projects/{{project}}/status)."
        ),
    ),
    "project_failed": Text(
        "Cannot run the project command",
        "Nie można wykonać polecenia projektu",
    ),
    "project_created": Text(
        "Created the project {project} in {path}.",
        "Utworzono projekt {project} w {path}.",
    ),
    "project_task_added": Text(
        "Added the task {task} to the project {project}.",
        "Dodano zadanie {task} do projektu {project}.",
    ),
    "project_task_removed": Text(
        (
            "Removed the task {task} from the project {project}; its files stay in"
            " the store."
        ),
        (
            "Usunięto zadanie {task} z projektu {project}; jego pliki zostają w"
            " magazynie."
        ),
    ),
    "project_status_line": Text(
        "{project} ({producer}): {status}, checked {checked_at}",
        "{project} ({producer}): {status}, sprawdzono {checked_at}",
    ),
    "project_status_task": Text(
        "  task {task}: {status}",
        "  zadanie {task}: {status}",
    ),
    "project_status_stale": Text(
        (
            "Note: the project's store is unavailable; this is the check of the last"
            " scan."
        ),
        (
            "Uwaga: magazyn projektu jest niedostępny; to sprawdzenie z ostatniego"
            " skanu."
        ),
    ),
    "project_download_help": Text(
        (
            "Downloads and pins the project's tasks not downloaded yet and restores"
            " missing pinned versions into the configured store its manifest names,"
            " and follows the job to its end (--json: the JobDetail model of the job"
            " as it ended, as POST /api/v1/projects/{{project}}/jobs starts it)."
        ),
        (
            "Pobiera i przypina jeszcze niepobrane zadania projektu i przywraca"
            " brakujące przypięte wersje w skonfigurowanym magazynie, który wskazuje"
            " manifest, i śledzi zadanie do końca (--json: model JobDetail zadania"
            " po jego końcu, uruchomionego jak przez POST"
            " /api/v1/projects/{{project}}/jobs)."
        ),
    ),
    "project_repin_help": Text(
        (
            "Pins one task of the project anew to the source's newer versions and"
            " follows the job to its end (--json: the JobDetail model of the job as"
            " it ended)."
        ),
        (
            "Przypina jedno zadanie projektu na nowo do nowszych wersji u źródła i"
            " śledzi zadanie do końca (--json: model JobDetail zadania po jego"
            " końcu)."
        ),
    ),
    "project_check_help": Text(
        (
            "Compares the project's pins with what the source has now, without"
            " effects, and follows the job to its end (--json: the JobDetail model of"
            " the job as it ended)."
        ),
        (
            "Porównuje przypięcia projektu z tym, co źródło ma teraz, bez skutków, i"
            " śledzi zadanie do końca (--json: model JobDetail zadania po jego"
            " końcu)."
        ),
    ),
    "project_verify_help": Text(
        (
            "Verifies the project's pinned files in the store (SHA-256, size,"
            " sidecar) without the network and follows the job to its end (--json:"
            " the JobDetail model of the job as it ended)."
        ),
        (
            "Weryfikuje przypięte pliki projektu w magazynie (SHA-256, rozmiar,"
            " sidecar) bez sieci i śledzi zadanie do końca (--json: model JobDetail"
            " zadania po jego końcu)."
        ),
    ),
    "project_tasks_help": Text(
        "Names of the project's tasks; none: every task.",
        "Nazwy zadań projektu; bez nich: wszystkie zadania.",
    ),
    "project_repin_task_help": Text(
        "Name of the task to pin anew.",
        "Nazwa zadania do ponownego przypięcia.",
    ),
    "preview_warm_help": Text(
        (
            "Prepares the first look at current versions ahead (the preview pane's"
            " thumbnail and the map's tiles at the smallest zoom) in the preview"
            " cache, at the lowest priority and without evicting previews used in"
            " the last week, and follows the job to its end (--json: the JobDetail"
            " model of the job as it ended, as POST /api/v1/previews/warm starts"
            " it). Without filters: every store's current versions."
        ),
        (
            "Przygotowuje z wyprzedzeniem pierwszy rzut oka na bieżące wersje"
            " (miniaturę panelu podglądu i kafelki mapy przy najmniejszym"
            " przybliżeniu) w pamięci podglądów, z najniższym priorytetem i bez"
            " usuwania podglądów używanych w ostatnim tygodniu, i śledzi zadanie do"
            " końca (--json: model JobDetail zadania po jego końcu, uruchomionego"
            " jak przez POST /api/v1/previews/warm). Bez filtrów: bieżące wersje"
            " wszystkich magazynów."
        ),
    ),
    "preview_warm_store_help": Text(
        "Only the current versions of this configured store.",
        "Tylko bieżące wersje tego skonfigurowanego magazynu.",
    ),
    "preview_warm_product_help": Text(
        "Only the current versions of this product (e.g. nmt).",
        "Tylko bieżące wersje tego produktu (np. nmt).",
    ),
    "preview_warm_segment_help": Text(
        "Only the current versions of this product segment (variant).",
        "Tylko bieżące wersje tego segmentu (wariantu) produktu.",
    ),
    "preview_warm_project_help": Text(
        (
            "Only the current versions the project pins, and the working files of"
            " its own data; without it no project's own data is prepared."
        ),
        (
            "Tylko bieżące wersje przypięte przez projekt i pliki robocze jego"
            " danych własnych; bez tego dane własne projektów nie są"
            " przygotowywane."
        ),
    ),
    "preview_warm_area_id_help": Text(
        "Only the current versions within an area saved via POST /api/v1/areas.",
        "Tylko bieżące wersje w obszarze zapisanym przez POST /api/v1/areas.",
    ),
    "stations_help": Text(
        "Stations of the station catalogs with the coverage of their series.",
        "Stacje z katalogów stacji z pokryciem ich szeregów.",
    ),
    "stations_list_help": Text(
        (
            "Lists stations along rivers or by name (--sort) with every variable of"
            " their series labelled (like GET /api/v1/stations, options with the"
            " same names; a repeatable parameter is a repeatable option); next"
            " page: --cursor."
        ),
        (
            "Wypisuje stacje wzdłuż rzek albo według nazwy (--sort) z etykietą"
            " każdej zmiennej ich szeregów (jak GET /api/v1/stations, opcje o tych"
            " samych nazwach; parametr powtarzalny to powtarzalna opcja); następna"
            " strona: --cursor."
        ),
    ),
    "stations_timeline_help": Text(
        (
            "Lists the stations of a dataset with each variable year by year, the"
            " Timeline (like GET /api/v1/stations/timeline: the options of"
            " 'stations list', --dataset required); next page: --cursor."
        ),
        (
            "Wypisuje stacje zbioru danych z każdą zmienną rok po roku, oś czasu"
            " (jak GET /api/v1/stations/timeline: opcje 'stations list', --dataset"
            " wymagane); następna strona: --cursor."
        ),
    ),
    "stations_show_help": Text(
        (
            "Shows the card of a station: its catalog entry and every series"
            " labelled (like GET /api/v1/stations/CODE)."
        ),
        (
            "Pokazuje kartę stacji: jej wpis w katalogu i etykiety każdego szeregu"
            " (jak GET /api/v1/stations/KOD)."
        ),
    ),
    "stations_datasets_help": Text(
        (
            "Lists the datasets with station series: their variables and the"
            " default range of their labels (like GET /api/v1/stations/datasets)."
        ),
        (
            "Wypisuje zbiory z szeregami stacji: ich zmienne i domyślny zakres"
            " etykiet (jak GET /api/v1/stations/datasets)."
        ),
    ),
    "stations_series_help": Text(
        (
            "Shows one or two variables of a station's series as a chart: each"
            " unit's value, or the least, mean and greatest value of intervals, with"
            " the gaps and markers (like GET /api/v1/stations/CODE/series)."
        ),
        (
            "Pokazuje jedną lub dwie zmienne szeregu stacji jako wykres: wartość"
            " każdej jednostki albo najmniejszą, średnią i największą wartość"
            " przedziałów, z lukami i znacznikami (jak GET"
            " /api/v1/stations/KOD/series)."
        ),
    ),
    "stations_compare_help": Text(
        (
            "Compares one variable of 2 to 5 stations over one range: each"
            " station's label and facts, and its points, gaps and markers (like"
            " GET /api/v1/stations/compare)."
        ),
        (
            "Porównuje jedną zmienną 2–5 stacji w jednym zakresie: etykietę i fakty"
            " każdej stacji oraz jej punkty, luki i znaczniki (jak GET"
            " /api/v1/stations/compare)."
        ),
    ),
    "stations_station_help": Text(
        "a station as STORE/PROVIDER/CODE (2 to 5 times)",
        "stacja jako MAGAZYN/DOSTAWCA/KOD (od 2 do 5 razy)",
    ),
    "stations_compare_dataset_help": Text(
        "dataset key of the series compared, e.g. pl.imgw.hydro_daily",
        "klucz zbioru danych porównywanych szeregów, np. pl.imgw.hydro_daily",
    ),
    "stations_compare_variable_help": Text(
        "the variable compared, e.g. Q",
        "porównywana zmienna, np. Q",
    ),
    "stations_compare_start_help": Text(
        (
            "first day of the range, e.g. 1950-11-01; by default the variable's"
            " first known day at the stations together"
        ),
        (
            "pierwszy dzień zakresu, np. 1950-11-01; domyślnie pierwszy znany dzień"
            " zmiennej na stacjach łącznie"
        ),
    ),
    "stations_compare_end_help": Text(
        (
            "last day of the range, e.g. 2025-10-31; by default the variable's last"
            " known day at the stations together"
        ),
        (
            "ostatni dzień zakresu, np. 2025-10-31; domyślnie ostatni znany dzień"
            " zmiennej na stacjach łącznie"
        ),
    ),
    "stations_code_help": Text(
        "station code as its provider gives it",
        "kod stacji, jak podaje go dostawca",
    ),
    "stations_store_help": Text(
        "store identifier",
        "identyfikator magazynu",
    ),
    "stations_provider_help": Text(
        "provider of the stations: IMGW-PIB or CHMI",
        "dostawca stacji: IMGW-PIB albo CHMI",
    ),
    "stations_dataset_help": Text(
        (
            "dataset key, e.g. pl.imgw.hydro_daily: only stations with a series of"
            " it, and only its coverage"
        ),
        (
            "klucz zbioru danych, np. pl.imgw.hydro_daily: tylko stacje z jego"
            " szeregiem i tylko jego pokrycie"
        ),
    ),
    "stations_years_help": Text(
        "range of years of the labels: 1951-2025 or one year",
        "zakres lat etykiet: 1951-2025 albo jeden rok",
    ),
    "stations_year_type_help": Text(
        "numbering of the years: hydrological or calendar",
        "numeracja lat: hydrological (hydrologiczne) albo calendar (kalendarzowe)",
    ),
    "stations_kind_help": Text(
        "station kind: hydro or meteo",
        "rodzaj stacji: hydro albo meteo",
    ),
    "stations_meteo_kind_help": Text(
        "meteo station kind: synoptic, climate or precipitation (repeatable)",
        (
            "rodzaj stacji meteorologicznej: synoptic (synoptyczna), climate"
            " (klimatologiczna) albo precipitation (opadowa) (powtarzalna)"
        ),
    ),
    "stations_active_help": Text(
        "true: active stations only, false: historical ones only",
        "true: tylko czynne stacje, false: tylko historyczne",
    ),
    "stations_river_code_help": Text(
        "hydrographic code of a river, e.g. 2138",
        "kod hydrograficzny rzeki, np. 2138",
    ),
    "stations_river_scope_help": Text(
        "exact (the river only, default) or tributaries (with its tributaries)",
        "exact (tylko rzeka, domyślnie) albo tributaries (z dopływami)",
    ),
    "stations_variable_help": Text(
        "stations with a value of the variable, e.g. Q (repeatable)",
        "stacje z wartością zmiennej, np. Q (powtarzalna)",
    ),
    "stations_chart_variable_help": Text(
        "variable of the series to draw, e.g. Q (once or twice)",
        "zmienna szeregu do narysowania, np. Q (raz albo dwa razy)",
    ),
    "stations_chart_dataset_help": Text(
        (
            "dataset key of the series, e.g. pl.imgw.hydro_daily; by default the one"
            " whose series has every variable"
        ),
        (
            "klucz zbioru danych szeregu, np. pl.imgw.hydro_daily; domyślnie ten,"
            " którego szereg ma każdą zmienną"
        ),
    ),
    "stations_start_help": Text(
        (
            "first day of the range, e.g. 1950-11-01; by default the variables'"
            " first known day"
        ),
        (
            "pierwszy dzień zakresu, np. 1950-11-01; domyślnie pierwszy znany dzień"
            " zmiennych"
        ),
    ),
    "stations_end_help": Text(
        (
            "last day of the range, e.g. 2025-10-31; by default the variables' last"
            " known day"
        ),
        (
            "ostatni dzień zakresu, np. 2025-10-31; domyślnie ostatni znany dzień"
            " zmiennych"
        ),
    ),
    "stations_max_points_help": Text(
        "the most points of a variable, at most 2000 (the default)",
        "najwięcej punktów zmiennej, najwyżej 2000 (domyślnie)",
    ),
    "stations_version_help": Text(
        (
            "the series version the chart must come from (its series.json); by"
            " default the current one"
        ),
        ("wersja szeregu, z której ma być wykres (jej series.json); domyślnie bieżąca"),
    ),
    "stations_coverage_help": Text(
        (
            "variable:state of its label, e.g. Q:continuous (repeatable; needs"
            " --dataset)"
        ),
        ("zmienna:stan jej etykiety, np. Q:continuous (powtarzalna; wymaga --dataset)"),
    ),
    "stations_min_complete_years_help": Text(
        "variable:least full years, e.g. Q:30 (repeatable; needs --dataset)",
        "zmienna:najmniej pełnych lat, np. Q:30 (powtarzalna; wymaga --dataset)",
    ),
    "stations_q_help": Text(
        (
            "search: stations whose name or river contains the text (case"
            " ignored) or whose code begins with it"
        ),
        (
            "wyszukiwanie: stacje, których nazwa albo rzeka zawiera tekst (bez"
            " względu na wielkość liter), albo których kod się nim zaczyna"
        ),
    ),
    "stations_sort_help": Text(
        "order: river (along rivers, default) or name",
        "kolejność: river (wzdłuż rzek, domyślnie) albo name (według nazwy)",
    ),
    "stations_area_id_help": Text(
        "area saved via POST /api/v1/areas",
        "obszar zapisany przez POST /api/v1/areas",
    ),
    "stations_bbox_help": Text(
        "area as a rectangle min_x,min_y,max_x,max_y in the CRS from --bbox-crs",
        "obszar jako prostokąt min_x,min_y,max_x,max_y w układzie z --bbox-crs",
    ),
    "stations_bbox_crs_help": Text(
        "CRS of --bbox, e.g. EPSG:2180 (default EPSG:4326)",
        "układ współrzędnych --bbox, np. EPSG:2180 (domyślnie EPSG:4326)",
    ),
    "stations_boundary_help": Text(
        "false: leave out the stations on the area's boundary (default true)",
        "false: pomiń stacje na granicy obszaru (domyślnie true)",
    ),
    "stations_location_help": Text(
        "location: any (default), with (a position) or none (no position)",
        "położenie: any (domyślnie), with (z położeniem) albo none (bez położenia)",
    ),
    "stations_limit_help": Text(
        "number of stations per page: 1–200 (default 50)",
        "liczba stacji na stronie: 1–200 (domyślnie 50)",
    ),
    "stations_cursor_help": Text(
        "next_cursor of the previous page of the same query",
        "next_cursor poprzedniej strony tego samego zapytania",
    ),
    "stations_failed": Text(
        "Cannot read the stations",
        "Nie można odczytać stacji",
    ),
    "stations_none": Text(
        "No stations.",
        "Brak stacji.",
    ),
    "station_datasets_none": Text(
        "No datasets with station series.",
        "Brak zbiorów z szeregami stacji.",
    ),
    "station_dataset_line": Text(
        (
            "{dataset} · {name} · {provider} · {kind} · store {store}: series"
            " {series}, {year_type} years {years}; variables: {variables}"
        ),
        (
            "{dataset} · {name} · {provider} · {kind} · magazyn {store}: szeregi"
            " {series}, lata {year_type} {years}; zmienne: {variables}"
        ),
    ),
    "station_dataset_variable": Text(
        "{key} ({unit})",
        "{key} ({unit})",
    ),
    "station_line": Text(
        "{code}  {name} · {kind} · {provider} · store {store}{river}{place}",
        "{code}  {name} · {kind} · {provider} · magazyn {store}{river}{place}",
    ),
    "station_river": Text(
        " · {river} ({code})",
        " · {river} ({code})",
    ),
    "station_on_boundary": Text(
        " · on the area's boundary",
        " · na granicy obszaru",
    ),
    "station_unlocated": Text(
        " · no location ({reason})",
        " · bez położenia ({reason})",
    ),
    "station_series": Text(
        "  {dataset} (series {series}, {year_type} years {years}): {labels}",
        "  {dataset} (szeregi {series}, lata {year_type} {years}): {labels}",
    ),
    "station_label": Text(
        "{key}: {label}",
        "{key}: {label}",
    ),
    "station_timeline_series": Text(
        "  {dataset} (series {series}, {year_type} years {years})",
        "  {dataset} (szeregi {series}, lata {year_type} {years})",
    ),
    "station_timeline_variable": Text(
        "    {key} {years}  {label}",
        "    {key} {years}  {label}",
    ),
    "station_timeline_legend": Text(
        (
            "Years: {full} full, {fraction} with gaps, {none} without a value,"
            " {unknown} not known."
        ),
        (
            "Lata: {full} pełny, {fraction} z lukami, {none} bez wartości,"
            " {unknown} nieznany."
        ),
    ),
    "stations_summary": Text(
        (
            "Stations on the page: {count}. With a location: {located} (on the"
            " area's boundary: {boundary}), without: {unlocated}, hidden by"
            " filter: {hidden}."
        ),
        (
            "Stacje na stronie: {count}. Z położeniem: {located} (na granicy"
            " obszaru: {boundary}), bez położenia: {unlocated}, ukryte filtrem:"
            " {hidden}."
        ),
    ),
    "station_title": Text(
        "{code} — {name} ({provider}, store {store})",
        "{code} — {name} ({provider}, magazyn {store})",
    ),
    "station_facts": Text(
        (
            "Kind {kind}; river {river} ({river_code}); active: {active}; since"
            " {established}; gauge zero {gauge_zero} m; river km {river_km}."
        ),
        (
            "Rodzaj {kind}; rzeka {river} ({river_code}); czynna: {active}; od"
            " {established}; zero wodowskazu {gauge_zero} m; km rzeki {river_km}."
        ),
    ),
    "station_located": Text(
        (
            "Location: {lon}, {lat} (source {source}, uncertainty {uncertainty} m,"
            " catalog {catalog})."
        ),
        (
            "Położenie: {lon}, {lat} (źródło {source}, niepewność {uncertainty} m,"
            " katalog {catalog})."
        ),
    ),
    "station_no_location": Text(
        "No location: {reason} (catalog {catalog}).",
        "Bez położenia: {reason} (katalog {catalog}).",
    ),
    "station_series_title": Text(
        "Series {dataset}, version {series}, {year_type} years {years}: {file}",
        "Szereg {dataset}, wersja {series}, lata {year_type} {years}: {file}",
    ),
    "station_variable": Text(
        "  {key} ({unit}): {label}; full years: {complete}",
        "  {key} ({unit}): {label}; pełne lata: {complete}",
    ),
    "station_attribution": Text(
        "  Licence {license}: {attribution}",
        "  Licencja {license}: {attribution}",
    ),
    "station_chart_title": Text(
        "{code}: series {dataset}, version {series}, {year_type} years: {file}",
        "{code}: szereg {dataset}, wersja {series}, lata {year_type}: {file}",
    ),
    "station_chart_values": Text(
        "Range {start} to {end} ({units}): each unit's value",
        "Zakres {start} – {end} ({units}): wartość każdej jednostki",
    ),
    "station_chart_simplified": Text(
        "Range {start} to {end} ({units}): simplified, min./mean/max. of {interval}",
        "Zakres {start} – {end} ({units}): uproszczony, min./śr./maks. z {interval}",
    ),
    "station_chart_empty": Text(
        "No unit of the series lies in the range.",
        "Żadna jednostka szeregu nie leży w zakresie.",
    ),
    "station_chart_variable": Text(
        (
            "  {key} ({unit}): {valued} of {points} points with a value, {gaps} gaps,"
            " {markers} markers"
        ),
        (
            "  {key} ({unit}): {valued} z {points} punktów z wartością, luki: {gaps},"
            " znaczniki: {markers}"
        ),
    ),
    "station_chart_gap": Text(
        "    gap {start} to {end} ({units})",
        "    luka {start} – {end} ({units})",
    ),
    "station_chart_accumulated": Text(
        "    accumulated sum {day}: {value}",
        "    suma zbiorcza {day}: {value}",
    ),
    "station_chart_extreme": Text(
        "    {kind} of the {period} {day}: {value}",
        "    {kind} – {period} {day}: {value}",
    ),
    "station_compare_title": Text(
        "Comparison of {variable} of {dataset}, {year_type} years",
        "Porównanie {variable} z {dataset}, lata {year_type}",
    ),
    "station_compare_missing": Text(
        "  no data: no variable {variable} in a series of {dataset}",
        "  brak danych: brak zmiennej {variable} w szeregu {dataset}",
    ),
    "station_marker_min": Text(
        "least value",
        "najmniejsza wartość",
    ),
    "station_marker_max": Text(
        "greatest value",
        "największa wartość",
    ),
    "station_period_winter": Text(
        "winter half-year",
        "półrocze zimowe",
    ),
    "station_period_summer": Text(
        "summer half-year",
        "półrocze letnie",
    ),
    "station_period_annual": Text(
        "year",
        "rok",
    ),
    "station_active_true": Text(
        "yes",
        "tak",
    ),
    "station_active_false": Text(
        "no",
        "nie",
    ),
    "station_reason_none": Text(
        "no source gives coordinates",
        "żadne źródło nie podaje współrzędnych",
    ),
    "station_reason_zero": Text(
        "the source gave 0,0",
        "źródło podało 0,0",
    ),
    "station_reason_outside_country": Text(
        "outside the provider's country",
        "poza krajem dostawcy",
    ),
}
