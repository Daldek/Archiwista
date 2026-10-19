"""Polish texts of the metadata comparison (plan v0.2, decision 10, level 1).

Every compared field of a store version, an own file or a snapshot has its
human name, ``compare_field_<field>``; the fields of the raw sidecar keep
their JSON paths as names (Archiwista does not know the producer's fields)
and a layer's row is named by ``compare_layer_features``. The rest belongs to
objects not found, the sides' titles and ``archiwista compare``.
"""

from types import MappingProxyType

COMPARE_MESSAGES = MappingProxyType(
    {
        # Fields of a store version, from the index.
        "compare_field_data_date": "Data danych",
        "compare_field_data_year": "Rok danych",
        "compare_field_downloaded_at": "Pobrano",
        "compare_field_label": "Etykieta",
        "compare_field_campaign": "Kampania",
        "compare_field_survey_work_id": "Zgłoszenie prac",
        "compare_field_edition": "Wydanie",
        "compare_field_full_sheet": "Arkusz pełny (wg producenta)",
        "compare_field_coverage": "Pokrycie arkusza",
        "compare_field_resolution": "Rozdzielczość",
        "compare_field_horizontal_crs": "Układ poziomy",
        "compare_field_vertical_crs": "Układ wysokości",
        "compare_field_nodata": "Brak danych (nodata)",
        "compare_field_sha256": "SHA-256",
        "compare_field_size_bytes": "Rozmiar (bajty)",
        "compare_field_license": "Licencja",
        "compare_field_attribution": "Atrybucja",
        # Fields of an own file or a snapshot, from the index (``size_bytes``
        # is named above).
        "compare_field_format": "Format (sterownik GDAL)",
        "compare_field_feature_count": "Liczba obiektów (wszystkie warstwy)",
        "compare_field_crs": "Układ współrzędnych",
        "compare_field_extent": "Zasięg (min x, min y, max x, max y)",
        "compare_field_content_method": "Tożsamość treści — metoda",
        "compare_field_content_sha256": "Tożsamość treści — SHA-256",
        "compare_field_created_at": "Utworzenie migawki",
        "compare_field_author": "Autor migawki",
        "compare_field_note": "Opis migawki",
        "compare_field_modified_at": "Modyfikacja pliku",
        "compare_field_first_seen_at": "Pierwsze wykrycie pliku",
        "compare_field_changed_at": "Ostatnia zmiana treści pliku",
        "compare_layer_features": "Obiekty w warstwie „{layer}”",
        # Own data not found (an invisible project is not found either).
        "compare_file_not_found": (
            "Projekt „{project}” nie ma w danych własnych pliku {path} — odśwież"
            " dane własne projektu."
        ),
        "compare_snapshot_not_found": (
            "Plik {path} projektu „{project}” nie ma migawki {label} — odśwież"
            " dane własne projektu."
        ),
        # Titles of the compared objects.
        "compare_title_version": "{name} — {label}",
        "compare_title_no_label": "bez etykiety",
        "compare_title_working": "plik roboczy",
        # ``archiwista compare`` (decision 11).
        "cli_compare_help": (
            "Porównanie metadanych dwóch obiektów (--json: model Comparison)."
        ),
        "cli_compare_ref_help": (
            "Odwołanie do obiektu przepisane z odpowiedzi API (pole ref), np."
            " version:zespol:nmt/…/plik.asc."
        ),
        "cli_compare_schema": "Schemat warstw (zmiany z A na B):",
        "cli_compare_layer_only_a": "  warstwa tylko w A: {layer}",
        "cli_compare_layer_only_b": "  warstwa tylko w B: {layer}",
        "cli_compare_layer": "  warstwa {layer}:",
        "cli_compare_field_added": "    + pole {name} ({type})",
        "cli_compare_field_removed": "    - pole {name} ({type})",
        "cli_compare_field_changed": "    ~ pole {name}: {type_a} → {type_b}",
        "cli_compare_failed": "Nie można porównać obiektów",
        "cli_compare_true": "tak",
        "cli_compare_false": "nie",
        "cli_compare_side": "{side}: {title} ({ref})",
        "cli_compare_same_content": "Ta sama treść pliku (SHA-256).",
        "cli_compare_row": "{mark} {label}: {a} | {b}",
        "cli_compare_summary": "Różnice: {differs} z {total} pól.",
    }
)
