"""Polish texts of the previews (plan v0.2, decisions 3, 5 and 6).

Every reason a file has no preview (``PreviewReason``) has a description,
``preview_reason_<code>``, and a fix, ``preview_fix_<code>``; every style
(``StyleName``) has its name, ``preview_style_<style>``. The rest belongs to
the render pool and the ``preview`` job.
"""

from types import MappingProxyType

PREVIEW_MESSAGES = MappingProxyType(
    {
        # Why a file has no preview, and what to do about it.
        "preview_reason_no_georeference": (
            "Plik nie ma georeferencji, więc nie trafi na mapę (plik świata obok"
            " nie wystarcza)."
        ),
        "preview_fix_no_georeference": (
            "Zapisz plik jako GeoTIFF z układem współrzędnych, np. w QGIS"
            " (Eksportuj › Zapisz jako)."
        ),
        "preview_reason_no_crs": (
            "Plik nie ma układu współrzędnych (np. Shapefile bez pliku .prj), więc"
            " nie trafi na mapę."
        ),
        "preview_fix_no_crs": (
            "Dodaj układ współrzędnych (plik .prj) albo zapisz plik ponownie z układem."
        ),
        "preview_reason_auxiliary_file": (
            "To plik pomocniczy innego pliku (np. plik świata .jgw)."
        ),
        "preview_fix_auxiliary_file": "Podgląd jest przy pliku, któremu ten służy.",
        "preview_reason_archive_members_only": (
            "Archiwum ZIP: widać tylko listę plików w środku."
        ),
        "preview_fix_archive_members_only": (
            "Rozpakuj archiwum, żeby obejrzeć jego pliki w QGIS."
        ),
        "preview_reason_document_no_preview": "Dokument nie ma podglądu w Archiwiście.",
        "preview_fix_document_no_preview": (
            "Otwórz plik ze ścieżki do skopiowania w programie, który go obsługuje."
        ),
        "preview_reason_unsupported_format": (
            "Archiwista nie pokazuje podglądu tego formatu pliku."
        ),
        "preview_fix_unsupported_format": (
            "Otwórz plik w QGIS albo w programie, który go obsługuje."
        ),
        "preview_reason_too_large": "Plik jest za duży na podgląd w Archiwiście.",
        "preview_fix_too_large": (
            "Duży raster: użyj „Zbuduj podgląd”. Inny plik otwórz w QGIS."
        ),
        "preview_reason_missing_file": "Pliku tej wersji nie ma na dysku.",
        "preview_fix_missing_file": (
            "Odśwież magazyn; jeśli plik usunięto, pobierz wersję ponownie Kartografem."
        ),
        "preview_reason_store_unavailable": (
            "Magazyn jest odłączony, a w pamięci podglądów nie ma tego podglądu."
        ),
        "preview_fix_store_unavailable": (
            "Podłącz magazyn (np. udział sieciowy) i spróbuj ponownie."
        ),
        "preview_reason_transform_unavailable": (
            "Brak przypiętej operacji przeliczenia z układu pliku do układu mapy,"
            " więc plik nie trafi na mapę."
        ),
        "preview_fix_transform_unavailable": (
            "Miniatura jest dostępna; na mapę plik trafi z wersją Kartografa,"
            " która ma operację dla tego układu."
        ),
        "preview_reason_unreadable": "Nie można odczytać pliku.",
        "preview_fix_unreadable": (
            "Sprawdź plik w QGIS; może być uszkodzony albo niekompletny."
        ),
        "preview_reason_timeout": "Przygotowanie podglądu trwało za długo.",
        "preview_fix_timeout": (
            "Spróbuj ponownie za kilka minut; dla dużego pliku użyj „Zbuduj podgląd”."
        ),
        "preview_reason_memory_limit": (
            "Przygotowanie podglądu przekroczyło limit pamięci."
        ),
        "preview_fix_memory_limit": (
            "Spróbuj ponownie za kilka minut; dla dużego pliku użyj „Zbuduj podgląd”."
        ),
        "preview_reason_changed_since_scan": "Plik zmienił się od ostatniego skanu.",
        "preview_fix_changed_since_scan": (
            "Odśwież dane własne projektu („Odśwież”) i otwórz podgląd ponownie."
        ),
        # Styles of the previews.
        "preview_style_hillshade": "cieniowanie",
        "preview_style_hypsometry": "hipsometria",
        "preview_style_rgb": "kolory (RGB)",
        "preview_style_gray": "skala szarości",
        "preview_style_classes": "klasy",
        "preview_style_features": "obiekty",
        "preview_style_elevation": "wysokość",
        # Render pool.
        "preview_busy": (
            "Kolejka podglądów jest pełna; spróbuj ponownie za {seconds} s."
        ),
        "preview_closed": "Archiwista kończy pracę; podglądy są chwilowo niedostępne.",
        "preview_timeout": (
            "Przygotowanie podglądu przekroczyło limit czasu ({seconds} s)."
        ),
        "preview_timeout_recent": (
            "Przygotowanie tego podglądu niedawno przekroczyło limit czasu;"
            " Archiwista spróbuje ponownie po {minutes} min."
        ),
        # The ``preview`` job.
        "job_kind_preview": "budowa podglądów",
        "preview_build_timeout": (
            "Budowa podglądu przekroczyła limit czasu ({minutes} min)."
        ),
        "preview_build_too_large": (
            "Plik przekracza progi budowy automatycznej (2 GB pliku, 1 Gpx"
            " i 8 GB po rozpakowaniu); zbuduj podgląd przyciskiem „Zbuduj podgląd”."
        ),
        "preview_build_unresolved": "Nie można zbudować podglądu „{ref}”: {detail}",
        "preview_build_unknown_ref": "nieznany rodzaj odwołania.",
    }
)
