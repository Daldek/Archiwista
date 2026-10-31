"""Problems of a store or of own data, as the interface lists them."""

from archiwista.messages import Text

MESSAGES = {
    "missing_sidecar": Text(
        "File without a sidecar: {path}",
        "Plik bez sidecara: {path}",
    ),
    "invalid_sidecar": Text(
        "Unreadable file sidecar: {path}",
        "Nieczytelny sidecar pliku: {path}",
    ),
    "imgw_missing_sidecar": Text(
        (
            "Version directory without a sidecar, a download in progress or an"
            " interrupted one (it is not a version): {path}"
        ),
        (
            "Katalog wersji bez sidecara, pobieranie w toku albo przerwane (to nie"
            " jest wersja): {path}"
        ),
    ),
    "unknown_schema": Text(
        "File in a schema this version does not read: {path}",
        "Plik w schemacie, którego ta wersja nie czyta: {path}",
    ),
    "unknown_segment": Text(
        "Directory not recognized by the {producer} plugin: {path}",
        "Katalog nierozpoznany przez wtyczkę {producer}: {path}",
    ),
    "legacy_campaigns": Text(
        (
            "The kampanie/ directory from an older version of the {producer} package"
            " (0.7.x), unreadable: {path}"
        ),
        (
            "Katalog kampanie/ ze starszej wersji pakietu {producer} (0.7.x),"
            " nieczytany: {path}"
        ),
    ),
    "stale_incoming": Text(
        "Leftover of an interrupted download older than 24 h: {path}",
        "Pozostałość przerwanego pobierania starsza niż 24 h: {path}",
    ),
    "link_mismatch": Text(
        "The link has different content than its sidecar states: {path}",
        "Dowiązanie ma inną treść, niż podaje jego sidecar: {path}",
    ),
    "orphan_sidecar": Text(
        "The link sidecar points to a missing version {version}: {path}",
        "Sidecar dowiązania wskazuje brakującą wersję {version}: {path}",
    ),
    "missing_pin": Text(
        (
            "The pinned file does not exist in the store: {version} (project"
            ' "{project}", group {group})'
        ),
        (
            "Przypięty plik nie istnieje w magazynie: {version} (projekt „{project}”,"
            " grupa {group})"
        ),
    ),
    "pin_sha256_mismatch": Text(
        (
            "The pinned version has different content in the store (SHA-256):"
            ' {version} (project "{project}", group {group})'
        ),
        (
            "Przypięta wersja ma w magazynie inną treść (SHA-256): {version} (projekt"
            " „{project}”, grupa {group})"
        ),
    ),
    "invalid_project_file": Text(
        "Invalid project file: {detail}",
        "Niepoprawny plik projektu: {detail}",
    ),
    "unsupported_project_schema": Text(
        "The project file is of a newer format ({schema}): {path}",
        "Plik projektu ma nowszy format ({schema}): {path}",
    ),
    "unknown_store": Text(
        "Unknown project store of {producer}: {store_dir}",
        "Magazyn projektu nieznany ({producer}): {store_dir}",
    ),
    "area_missing": Text(
        "The project's area file does not exist: {path}",
        "Plik obszaru projektu nie istnieje: {path}",
    ),
    "area_changed": Text(
        (
            "The project's area file holds other bytes than the project file"
            " records: {path}"
        ),
        "Plik obszaru projektu ma inną treść, niż zapisano w pliku projektu: {path}",
    ),
    "area_invalid": Text(
        (
            "The project's area file is no polygon of GeoJSON in WGS84 within the"
            " limits: {path}"
        ),
        (
            "Plik obszaru projektu nie jest wielokątem GeoJSON w WGS84 w granicach"
            " limitów: {path}"
        ),
    ),
    "other": Text(
        "Store problem ({code}): {path}",
        "Problem magazynu ({code}): {path}",
    ),
    "own_folder_unreadable": Text(
        "Cannot read the data directory: {path}",
        "Nie można odczytać folderu danych: {path}",
    ),
    "own_folder_invalid": Text(
        "The data folder {path} is not read: {reason}",
        "Folder danych {path} nie jest czytany: {reason}",
    ),
    "own_folder_too_large": Text(
        (
            "The data folder exceeds the scanning limit (files, entries, directories,"
            " snapshots, or depth); the index may not cover all data: {path}"
        ),
        (
            "Folder danych przekracza limit skanowania (plików, wpisów, katalogów,"
            " migawek lub głębokości); indeks może nie obejmować wszystkich danych:"
            " {path}"
        ),
    ),
    "own_file_unreadable": Text(
        "Cannot read file {path} ({reason})",
        "Nie można odczytać pliku {path} ({reason})",
    ),
    "invalid_snapshot": Text(
        "Snapshot without a valid migawka.json description: {path}",
        "Migawka bez poprawnego opisu migawka.json: {path}",
    ),
    "unknown_snapshot_schema": Text(
        "Snapshot in an unknown format {reason}: {path}",
        "Migawka w nieznanym formacie {reason}: {path}",
    ),
    "snapshot_modified": Text(
        "The snapshot files differ from its description (size or checksum): {path}",
        "Pliki migawki różnią się od jej opisu (rozmiar albo suma kontrolna): {path}",
    ),
    "stale_snapshot_incoming": Text(
        "Leftover of an interrupted snapshot older than 24 hours: {path}",
        "Pozostałość przerwanej migawki starsza niż 24 godziny: {path}",
    ),
    "path_outside_root": Text(
        "A symbolic link points outside the data folder: {path}",
        "Dowiązanie symboliczne wychodzi poza folder danych: {path}",
    ),
}
