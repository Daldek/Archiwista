"""Polish texts of the metadata comparison (plan v0.2, decision 10, level 1).

Every compared field of a store version has its human name,
``compare_field_<field>``; the fields of the raw sidecar keep their JSON
paths as names (Archiwista does not know the producer's fields). The rest
belongs to the sides' titles and ``archiwista compare``.
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
        # An object of a kind not compared yet (own data: step 9).
        "compare_kind_unsupported": (
            "Odwołanie „{ref}” wskazuje obiekt, którego ten Archiwista jeszcze nie"
            " porównuje."
        ),
        # Titles of the compared objects.
        "compare_title_version": "{name} — {label}",
        "compare_title_no_label": "bez etykiety",
        # ``archiwista compare`` (decision 11).
        "cli_compare_help": (
            "Porównanie metadanych dwóch obiektów (--json: model Comparison)."
        ),
        "cli_compare_ref_help": (
            "Odwołanie do obiektu przepisane z odpowiedzi API (pole ref), np."
            " version:zespol:nmt/…/plik.asc."
        ),
        "cli_compare_failed": "Nie można porównać obiektów",
        "cli_compare_side": "{side}: {title} ({ref})",
        "cli_compare_same_content": "Ta sama treść pliku (SHA-256).",
        "cli_compare_row": "{mark} {label}: {a} | {b}",
        "cli_compare_summary": "Różnice: {differs} z {total} pól.",
    }
)
