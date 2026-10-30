"""Previews: why a file has none, fixes, states, builds and tiles."""

from archiwista.messages import Text

MESSAGES = {
    "reason_no_georeference": Text(
        (
            "The file has no georeference, so it will not appear on the map (a world"
            " file next to it is not enough)."
        ),
        (
            "Plik nie ma georeferencji, więc nie trafi na mapę (plik świata obok nie"
            " wystarcza)."
        ),
    ),
    "fix_no_georeference": Text(
        (
            "Save the file as a GeoTIFF with a coordinate system, e.g. in QGIS (Export"
            " › Save As)."
        ),
        (
            "Zapisz plik jako GeoTIFF z układem współrzędnych, np. w QGIS (Eksportuj ›"
            " Zapisz jako)."
        ),
    ),
    "reason_no_crs": Text(
        (
            "The file has no coordinate system (e.g. a Shapefile without a .prj file),"
            " so it will not appear on the map."
        ),
        (
            "Plik nie ma układu współrzędnych (np. Shapefile bez pliku .prj), więc nie"
            " trafi na mapę."
        ),
    ),
    "fix_no_crs": Text(
        (
            "Add a coordinate system (a .prj file) or save the file again with a"
            " coordinate system."
        ),
        "Dodaj układ współrzędnych (plik .prj) albo zapisz plik ponownie z układem.",
    ),
    "reason_auxiliary_file": Text(
        "This is an auxiliary file of another file (e.g. a world file .jgw).",
        "To plik pomocniczy innego pliku (np. plik świata .jgw).",
    ),
    "fix_auxiliary_file": Text(
        "The preview is attached to the file that this one serves.",
        "Podgląd jest przy pliku, któremu ten służy.",
    ),
    "reason_archive_members_only": Text(
        "ZIP archive: only the list of files inside is shown.",
        "Archiwum ZIP: widać tylko listę plików w środku.",
    ),
    "fix_archive_members_only": Text(
        "Extract the archive to view its files in QGIS.",
        "Rozpakuj archiwum, żeby obejrzeć jego pliki w QGIS.",
    ),
    "reason_document_no_preview": Text(
        "The document has no preview in Archiwista.",
        "Dokument nie ma podglądu w Archiwiście.",
    ),
    "fix_document_no_preview": Text(
        (
            'Download it with "Pobierz plik" (Download file) and open it in a program'
            " that supports it, or open it from the path to copy."
        ),
        (
            "Pobierz go przyciskiem „Pobierz plik” i otwórz w programie, który go"
            " obsługuje, albo otwórz go ze ścieżki do skopiowania."
        ),
    ),
    "reason_unsupported_format": Text(
        "Archiwista does not show a preview of this file format.",
        "Archiwista nie pokazuje podglądu tego formatu pliku.",
    ),
    "fix_unsupported_format": Text(
        "Open the file in QGIS or in a program that supports it.",
        "Otwórz plik w QGIS albo w programie, który go obsługuje.",
    ),
    "reason_too_large": Text(
        "The file is too large for a preview in Archiwista.",
        "Plik jest za duży na podgląd w Archiwiście.",
    ),
    "fix_too_large": Text(
        (
            'Large raster: use "Zbuduj podgląd" (Build preview). Open any other file'
            " in QGIS."
        ),
        "Duży raster: użyj „Zbuduj podgląd”. Inny plik otwórz w QGIS.",
    ),
    "reason_missing_file": Text(
        "The file is not on disk.",
        "Pliku nie ma na dysku.",
    ),
    "fix_missing_file": Text(
        (
            "Refresh the store or the project's own data; download a version removed"
            " from the store again with Kartograf."
        ),
        (
            "Odśwież magazyn albo dane własne projektu; wersję usuniętą z magazynu"
            " pobierz ponownie Kartografem."
        ),
    ),
    "reason_store_unavailable": Text(
        "The store is disconnected, and this preview is not in the preview cache.",
        "Magazyn jest odłączony, a w pamięci podglądów nie ma tego podglądu.",
    ),
    "fix_store_unavailable": Text(
        "Connect the store (e.g. a network share) and try again.",
        "Podłącz magazyn (np. udział sieciowy) i spróbuj ponownie.",
    ),
    "reason_transform_unavailable": Text(
        (
            "There is no pinned transformation operation from the file's coordinate"
            " system to the map's coordinate system, so the file will not appear on the"
            " map."
        ),
        (
            "Brak przypiętej operacji przeliczenia z układu pliku do układu mapy, więc"
            " plik nie trafi na mapę."
        ),
    ),
    "fix_transform_unavailable": Text(
        (
            "The thumbnail is available; the file will appear on the map with a"
            " Kartograf version that has an operation for this coordinate system."
        ),
        (
            "Miniatura jest dostępna; na mapę plik trafi z wersją Kartografa, która ma"
            " operację dla tego układu."
        ),
    ),
    "reason_unreadable": Text(
        "The file cannot be read.",
        "Nie można odczytać pliku.",
    ),
    "fix_unreadable": Text(
        "Check the file in QGIS; it may be damaged or incomplete.",
        "Sprawdź plik w QGIS; może być uszkodzony albo niekompletny.",
    ),
    "reason_timeout": Text(
        "Preparing the preview took too long.",
        "Przygotowanie podglądu trwało za długo.",
    ),
    "fix_timeout": Text(
        (
            'Try again in a few minutes; for a large file, use "Zbuduj podgląd"'
            " (Build preview)."
        ),
        "Spróbuj ponownie za kilka minut; dla dużego pliku użyj „Zbuduj podgląd”.",
    ),
    "reason_memory_limit": Text(
        "Preparing the preview exceeded the memory limit.",
        "Przygotowanie podglądu przekroczyło limit pamięci.",
    ),
    "fix_memory_limit": Text(
        (
            'Try again in a few minutes; for a large file, use "Zbuduj podgląd"'
            " (Build preview)."
        ),
        "Spróbuj ponownie za kilka minut; dla dużego pliku użyj „Zbuduj podgląd”.",
    ),
    "reason_changed_since_scan": Text(
        "The file has changed since the last scan.",
        "Plik zmienił się od ostatniego skanu.",
    ),
    "fix_changed_since_scan": Text(
        (
            'Refresh the project\'s own data (the "Odśwież" button) and open the'
            " preview again."
        ),
        "Odśwież dane własne projektu („Odśwież”) i otwórz podgląd ponownie.",
    ),
    "style_hillshade": Text(
        "hillshade",
        "cieniowanie",
    ),
    "style_hypsometry": Text(
        "hypsometry",
        "hipsometria",
    ),
    "style_rgb": Text(
        "colors (RGB)",
        "kolory (RGB)",
    ),
    "style_gray": Text(
        "grayscale",
        "skala szarości",
    ),
    "style_classes": Text(
        "classes",
        "klasy",
    ),
    "style_features": Text(
        "features",
        "obiekty",
    ),
    "style_elevation": Text(
        "elevation",
        "wysokość",
    ),
    "busy": Text(
        "The preview queue is full; try again in {seconds} s.",
        "Kolejka podglądów jest pełna; spróbuj ponownie za {seconds} s.",
    ),
    "closed": Text(
        "Archiwista is shutting down; previews are temporarily unavailable.",
        "Archiwista kończy pracę; podglądy są chwilowo niedostępne.",
    ),
    "renderer_not_started": Text(
        (
            "The preview process could not be started on this computer, so no"
            " preview can be prepared now."
        ),
        (
            "Nie udało się uruchomić procesu podglądu na tym komputerze, więc teraz"
            " nie można przygotować żadnego podglądu."
        ),
    ),
    "renderer_not_started_hint": Text(
        "The cause is in the server's log; try again once it is fixed.",
        "Przyczyna jest w dzienniku serwera; spróbuj ponownie po jej usunięciu.",
    ),
    "timeout": Text(
        "Preparing the preview exceeded the time limit ({seconds} s).",
        "Przygotowanie podglądu przekroczyło limit czasu ({seconds} s).",
    ),
    "timeout_recent": Text(
        (
            "Preparing this preview recently exceeded the time limit; Archiwista will"
            " try again in {minutes} min."
        ),
        (
            "Przygotowanie tego podglądu niedawno przekroczyło limit czasu; Archiwista"
            " spróbuje ponownie po {minutes} min."
        ),
    ),
    "build_timeout": Text(
        "Building the preview exceeded the time limit ({minutes} min).",
        "Budowa podglądu przekroczyła limit czasu ({minutes} min).",
    ),
    "build_too_large": Text(
        (
            "The file exceeds the automatic build thresholds (2 GB file, 1 Gpx and 8"
            ' GB after decompression); build the preview with the "Zbuduj podgląd"'
            " (Build preview) button."
        ),
        (
            "Plik przekracza progi budowy automatycznej (2 GB pliku, 1 Gpx i 8 GB po"
            " rozpakowaniu); zbuduj podgląd przyciskiem „Zbuduj podgląd”."
        ),
    ),
    "build_unresolved": Text(
        'Cannot build the preview "{ref}": {detail}',
        "Nie można zbudować podglądu „{ref}”: {detail}",
    ),
    "build_unknown_ref": Text(
        "unknown reference kind.",
        "nieznany rodzaj odwołania.",
    ),
    "kind_raster": Text(
        "raster",
        "raster",
    ),
    "kind_image": Text(
        "image",
        "obraz",
    ),
    "kind_vector": Text(
        "vector",
        "wektor",
    ),
    "kind_points": Text(
        "point cloud",
        "chmura punktów",
    ),
    "kind_archive": Text(
        "archive",
        "archiwum",
    ),
    "kind_document": Text(
        "document",
        "dokument",
    ),
    "kind_auxiliary": Text(
        "auxiliary file",
        "plik pomocniczy",
    ),
    "kind_unknown": Text(
        "unrecognized file",
        "nierozpoznany plik",
    ),
    "state_ready": Text(
        "ready",
        "gotowy",
    ),
    "state_needs_build": Text(
        "needs building",
        "wymaga zbudowania",
    ),
    "state_building": Text(
        "building",
        "w budowie",
    ),
    "state_unavailable": Text(
        "unavailable",
        "niedostępny",
    ),
    "state_failed": Text(
        "failed",
        "nieudany",
    ),
    "unavailable_detail": Text(
        "{message} {fix}",
        "{message} {fix}",
    ),
    "not_ready_build": Text(
        (
            'The map tiles of this file require building a preview ("Zbuduj podgląd"'
            " (Build preview))."
        ),
        "Kafle mapy tego pliku wymagają zbudowania podglądu („Zbuduj podgląd”).",
    ),
    "not_ready_job": Text(
        (
            "The preview of this file is being built (job {job}); map tiles will be"
            " available when it finishes."
        ),
        (
            "Podgląd tego pliku jest w budowie (zadanie {job}); kafle mapy będą"
            " dostępne po jej zakończeniu."
        ),
    ),
    "not_ready_building": Text(
        (
            "The preview of this file is being built; map tiles will be available when"
            " it finishes."
        ),
        (
            "Podgląd tego pliku jest w budowie; kafle mapy będą dostępne po jej"
            " zakończeniu."
        ),
    ),
    "tile_outside": Text(
        (
            "Tile {z}/{x}/{y} lies outside the file's extent or outside the zoom range"
            " {minzoom}–{maxzoom}."
        ),
        (
            "Kafel {z}/{x}/{y} leży poza zasięgiem pliku albo poza zakresem powiększeń"
            " {minzoom}–{maxzoom}."
        ),
    ),
    "tile_range": Text(
        "For z = {z} the value must be from 0 to {last}.",
        "Przy z = {z} wartość musi być od 0 do {last}.",
    ),
    "style_unknown": Text(
        'Style "{style}" is not available for this file; available: {styles}.',
        "Styl „{style}” nie jest dostępny dla tego pliku; dostępne: {styles}.",
    ),
    "layer_unknown": Text(
        'The file has no layer "{layer}"; layers: {layers}.',
        "Plik nie ma warstwy „{layer}”; warstwy: {layers}.",
    ),
    "none": Text(
        "none",
        "brak",
    ),
    "size_invalid": Text(
        "The thumbnail size is 128, 256, 512 or 1024 px.",
        "Rozmiar miniatury to 128, 256, 512 albo 1024 px.",
    ),
    "crs_invalid": Text(
        "Give the coordinate reference system as EPSG:<code>.",
        "Układ współrzędnych podaje się jako EPSG:<kod>.",
    ),
    "numbers_invalid": Text(
        "Enter {count} numbers separated by commas, the smaller ones first.",
        "Podaj {count} liczby oddzielone przecinkami, najpierw mniejsze.",
    ),
}
