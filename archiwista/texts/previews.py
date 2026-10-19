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
        # Objects by reference (decision 10).
        "ref_invalid": (
            "„{ref}” nie jest odwołaniem do obiektu: version:<magazyn>:<ścieżka>,"
            " file:<projekt>:<ścieżka> albo snapshot:<projekt>:<etykieta>:<ścieżka>."
        ),
        "ref_kind_unsupported": (
            "Odwołanie „{ref}” wskazuje obiekt, którego ten Archiwista nie podgląda."
        ),
        # Kinds and states of a preview.
        "preview_kind_raster": "raster",
        "preview_kind_image": "obraz",
        "preview_kind_vector": "wektor",
        "preview_kind_points": "chmura punktów",
        "preview_kind_archive": "archiwum",
        "preview_kind_document": "dokument",
        "preview_kind_auxiliary": "plik pomocniczy",
        "preview_kind_unknown": "nierozpoznany plik",
        "preview_state_ready": "gotowy",
        "preview_state_needs_build": "wymaga zbudowania",
        "preview_state_building": "w budowie",
        "preview_state_unavailable": "niedostępny",
        "preview_state_failed": "nieudany",
        # Previews over HTTP (step 6).
        "api_title_invalid_ref": "Niepoprawne odwołanie",
        "api_title_preview_unavailable": "Podgląd niedostępny",
        "api_title_preview_not_ready": "Podgląd nie jest gotowy",
        "api_title_preview_busy": "Podglądy zajęte",
        "api_title_preview_timeout": "Przekroczony czas podglądu",
        "preview_unavailable_detail": "{message} {fix}",
        "preview_not_ready_build": (
            "Kafle mapy tego pliku wymagają zbudowania podglądu („Zbuduj podgląd”)."
        ),
        "preview_not_ready_job": (
            "Podgląd tego pliku jest w budowie (zadanie {job}); kafle mapy będą"
            " dostępne po jej zakończeniu."
        ),
        "preview_tile_outside": (
            "Kafel {z}/{x}/{y} leży poza zasięgiem pliku albo poza zakresem"
            " powiększeń {minzoom}–{maxzoom}."
        ),
        "preview_tile_range": "Przy z = {z} wartość musi być od 0 do {last}.",
        "preview_style_unknown": (
            "Styl „{style}” nie jest dostępny dla tego pliku; dostępne: {styles}."
        ),
        "preview_layer_unknown": "Plik nie ma warstwy „{layer}”; warstwy: {layers}.",
        "preview_none": "brak",
        "preview_size_invalid": "Rozmiar miniatury to 128, 256, 512 albo 1024 px.",
        "preview_crs_invalid": "Układ współrzędnych podaje się jako EPSG:<kod>.",
        "preview_numbers_invalid": (
            "Podaj {count} liczby oddzielone przecinkami, najpierw mniejsze."
        ),
        # ``archiwista preview`` (decision 11).
        "cli_preview_help": (
            "Opis podglądu obiektu (--json: model PreviewInfo), miniatura do pliku"
            " PNG (--output) albo budowa podglądu na pierwszym planie (--build)."
        ),
        "cli_preview_ref_help": (
            "Odwołanie do obiektu przepisane z odpowiedzi API (pole ref), np."
            " version:zespol:nmt/…/plik.asc."
        ),
        "cli_preview_style_help": (
            "Styl miniatury zapisywanej przez --output; domyślnie styl domyślny pliku."
        ),
        "cli_preview_size_help": (
            "Bok miniatury zapisywanej przez --output w pikselach (domyślnie 512)."
        ),
        "cli_preview_output_help": (
            "Zapisuje miniaturę do pliku PNG tym samym procesem renderującym"
            " i przez tę samą pamięć podglądów co serwer."
        ),
        "cli_preview_build_help": (
            "Buduje podgląd (lokalny COG) na pierwszym planie, także pliku ponad"
            " progi budowy automatycznej, i podaje opis po budowie."
        ),
        "cli_preview_failed": "Nie można przygotować podglądu",
        "cli_preview_title": "{ref}: {kind}, podgląd {state}",
        "cli_preview_reason": "Powód: {message} {fix}",
        "cli_preview_styles": "Style: {styles} (domyślny: {default})",
        "cli_preview_map": (
            "Na mapie: powiększenia {minzoom}–{maxzoom}, zasięg {bounds}"
        ),
        "cli_preview_job": "Budowa: zadanie {job} ({state})",
        "cli_preview_written": "Zapisano miniaturę {path} ({size} px, styl {style}).",
        "cli_preview_build_started": "Budowa podglądu: zadanie {job}.",
        "cli_preview_build_progress": (
            "Budowa podglądu: {current}/{total} (zbudowane {built}, z pamięci"
            " {cached}, nieudane {failed})."
        ),
        "cli_preview_build_notice": "Budowa podglądu: {message}",
        "cli_preview_build_cancelling": "Przerywam budowę podglądu (zadanie {job})…",
        "cli_preview_build_failed": "Budowa podglądu (zadanie {job}) {state}: {detail}",
        # Jobs run in the foreground of a command (``jobs/foreground.py``).
        "job_foreground_waiting": (
            "Czekam na zakończenie zadania {job} ({kind}) innego procesu"
            " Archiwisty; potem uruchomię własne."
        ),
    }
)
