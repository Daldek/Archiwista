"""Comparison of two objects."""

from archiwista.messages import Text

MESSAGES = {
    "field_data_date": Text(
        "Data date",
        "Data danych",
    ),
    "field_data_year": Text(
        "Data year",
        "Rok danych",
    ),
    "field_downloaded_at": Text(
        "Downloaded",
        "Pobrano",
    ),
    "field_label": Text(
        "Label",
        "Etykieta",
    ),
    "field_campaign": Text(
        "Campaign",
        "Kampania",
    ),
    "field_survey_work_id": Text(
        "Survey work notification",
        "Zgłoszenie prac",
    ),
    "field_edition": Text(
        "Edition",
        "Wydanie",
    ),
    "field_full_sheet": Text(
        "Full sheet (per producer)",
        "Arkusz pełny (wg producenta)",
    ),
    "field_coverage": Text(
        "Sheet coverage",
        "Pokrycie arkusza",
    ),
    "field_resolution": Text(
        "Resolution",
        "Rozdzielczość",
    ),
    "field_horizontal_crs": Text(
        "Horizontal CRS",
        "Układ poziomy",
    ),
    "field_vertical_crs": Text(
        "Vertical CRS",
        "Układ wysokości",
    ),
    "field_nodata": Text(
        "No data (nodata)",
        "Brak danych (nodata)",
    ),
    "field_sha256": Text(
        "SHA-256",
        "SHA-256",
    ),
    "field_size_bytes": Text(
        "Size (bytes)",
        "Rozmiar (bajty)",
    ),
    "field_license": Text(
        "License",
        "Licencja",
    ),
    "field_attribution": Text(
        "Attribution",
        "Atrybucja",
    ),
    "field_format": Text(
        "Format (GDAL driver)",
        "Format (sterownik GDAL)",
    ),
    "field_feature_count": Text(
        "Feature count (all layers)",
        "Liczba obiektów (wszystkie warstwy)",
    ),
    "field_crs": Text(
        "Coordinate system",
        "Układ współrzędnych",
    ),
    "field_extent": Text(
        "Extent (min x, min y, max x, max y)",
        "Zasięg (min x, min y, max x, max y)",
    ),
    "field_content_method": Text(
        "Content identity — method",
        "Tożsamość treści — metoda",
    ),
    "field_content_sha256": Text(
        "Content identity — SHA-256",
        "Tożsamość treści — SHA-256",
    ),
    "field_created_at": Text(
        "Snapshot created",
        "Utworzenie migawki",
    ),
    "field_author": Text(
        "Snapshot author",
        "Autor migawki",
    ),
    "field_note": Text(
        "Snapshot description",
        "Opis migawki",
    ),
    "field_modified_at": Text(
        "File modified",
        "Modyfikacja pliku",
    ),
    "field_first_seen_at": Text(
        "File first detected",
        "Pierwsze wykrycie pliku",
    ),
    "field_changed_at": Text(
        "File content last changed",
        "Ostatnia zmiana treści pliku",
    ),
    "layer_features": Text(
        'Features in layer "{layer}"',
        "Obiekty w warstwie „{layer}”",
    ),
    "file_not_found": Text(
        (
            'Project "{project}" has no file {path} in its own data — refresh the'
            " project's own data."
        ),
        (
            "Projekt „{project}” nie ma w danych własnych pliku {path} — odśwież dane"
            " własne projektu."
        ),
    ),
    "snapshot_not_found": Text(
        (
            'File {path} of project "{project}" has no snapshot {label} — refresh'
            " the project's own data."
        ),
        (
            "Plik {path} projektu „{project}” nie ma migawki {label} — odśwież dane"
            " własne projektu."
        ),
    ),
    "title_version": Text(
        "{name} — {label}",
        "{name} — {label}",
    ),
    "title_no_label": Text(
        "no label",
        "bez etykiety",
    ),
    "title_working": Text(
        "working file",
        "plik roboczy",
    ),
}
