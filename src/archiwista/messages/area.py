"""Areas read from files (GeoJSON, GeoPackage, Shapefile archives)."""

from archiwista.messages import Text

MESSAGES = {
    "body_too_large": Text(
        (
            "The request body is larger than {limit_mb} MB, which is the maximum size"
            " of an area or its file."
        ),
        (
            "Treść żądania ma ponad {limit_mb} MB, a tyle najwyżej może mieć obszar"
            " albo jego plik."
        ),
    ),
    "archive_too_large": Text(
        (
            "The archive would be {size_mb} MB after extraction, and the limit is"
            " {limit_mb} MB — rejected before extraction."
        ),
        (
            "Archiwum po rozpakowaniu miałoby {size_mb} MB, a najwyżej {limit_mb} MB —"
            " odrzucone przed rozpakowaniem."
        ),
    ),
    "format_unknown": Text(
        (
            "Unknown area file format. Load GeoJSON, GeoPackage or a Shapefile packed"
            " into a ZIP (.shp, .shx, .dbf and .prj files)."
        ),
        (
            "Nieznany format pliku obszaru. Wczytaj GeoJSON, GeoPackage albo Shapefile"
            " spakowany do ZIP (pliki .shp, .shx, .dbf i .prj)."
        ),
    ),
    "archive_broken": Text(
        "Cannot read the ZIP archive: {detail}",
        "Nie można odczytać archiwum ZIP: {detail}",
    ),
    "archive_unsafe": Text(
        (
            'The archive contains a member "{member}" that points outside its'
            " directory — rejected before extraction."
        ),
        (
            "Archiwum zawiera człon „{member}” wychodzący poza swój katalog —"
            " odrzucone przed rozpakowaniem."
        ),
    ),
    "archive_link": Text(
        (
            'The archive contains a symbolic link "{member}" — rejected before'
            " extraction."
        ),
        (
            "Archiwum zawiera dowiązanie symboliczne „{member}” — odrzucone przed"
            " rozpakowaniem."
        ),
    ),
    "archive_encrypted": Text(
        'The archive contains an encrypted member "{member}".',
        "Archiwum zawiera zaszyfrowany człon „{member}”.",
    ),
    "archive_duplicate": Text(
        'The archive contains the member "{member}" twice.',
        "Archiwum zawiera dwa razy człon „{member}”.",
    ),
    "archive_members": Text(
        "The archive has {count} member(s), and the limit is {limit}.",
        "Archiwum ma {count} członów, a najwyżej {limit}.",
    ),
    "shapefile_missing": Text(
        "The archive does not contain a .shp file.",
        "Archiwum nie zawiera pliku .shp.",
    ),
    "shapefile_parts": Text(
        (
            'The Shapefile "{layer}" in the archive is missing the files {parts}'
            " (.shp, .shx, .dbf and .prj are required)."
        ),
        (
            "Shapefile „{layer}” w archiwum nie ma plików {parts} (potrzebne są .shp,"
            " .shx, .dbf i .prj)."
        ),
    ),
    "layers_many": Text(
        (
            "The file has several layers with geometry ({names}) — choose one (the"
            " layer parameter)."
        ),
        "Plik ma kilka warstw z geometrią ({names}) — wybierz jedną (parametr layer).",
    ),
    "layer_unknown": Text(
        'The file has no layer "{layer}" with geometry (available: {names}).',
        "Plik nie ma warstwy „{layer}” z geometrią (są: {names}).",
    ),
    "layers_none": Text(
        "The file has no layer with geometry.",
        "Plik nie ma żadnej warstwy z geometrią.",
    ),
    "crs_missing": Text(
        (
            "The file does not specify a coordinate reference system (e.g. the .prj"
            " file is missing), so it is not known where the area lies."
        ),
        (
            "Plik nie podaje układu współrzędnych (np. brak pliku .prj), więc nie"
            " wiadomo, gdzie leży obszar."
        ),
    ),
    "crs_not_named": Text(
        (
            "The GeoJSON file specifies the coordinate reference system other than by"
            ' name (e.g. as a "link" or "url" reference), and Archiwista does not'
            " download CRS definitions from the network. Specify the CRS by name (a crs"
            ' member of type "name", e.g. EPSG:2180) or save the file in WGS84'
            " (without a crs member)."
        ),
        (
            "Plik GeoJSON podaje układ współrzędnych inaczej niż nazwą (np. jako"
            " odnośnik „link” lub „url”), a Archiwista nie pobiera definicji układów z"
            " sieci. Podaj układ nazwą (człon crs typu „name”, np. EPSG:2180) albo"
            " zapisz plik w WGS84 (bez członu crs)."
        ),
    ),
    "no_polygon": Text(
        "The file contains no polygons, and an area must have a surface.",
        "Plik nie zawiera wielokątów, a obszar musi mieć powierzchnię.",
    ),
    "not_polygonal": Text(
        (
            "The file contains geometries other than polygons ({types}), and an area"
            " can consist only of polygons."
        ),
        (
            "Plik zawiera geometrie inne niż wielokąty ({types}), a obszar może"
            " składać się tylko z wielokątów."
        ),
    ),
    "read_failed": Text(
        "Cannot read the area file: {detail}",
        "Nie można odczytać pliku obszaru: {detail}",
    ),
    "read_timeout": Text(
        "Reading the area file took longer than {seconds} s and was aborted.",
        "Odczyt pliku obszaru trwał ponad {seconds} s i został przerwany.",
    ),
    "reader_crashed": Text(
        "The area file reader process ended without a response (exit code {code}).",
        (
            "Proces odczytu pliku obszaru zakończył się bez odpowiedzi (kod wyjścia"
            " {code})."
        ),
    ),
    "too_many_vertices": Text(
        (
            "The area has {vertices} vertices, but the limit is {limit}. Simplify it"
            " in a GIS program — Archiwista does not simplify geometry."
        ),
        (
            "Obszar ma {vertices} wierzchołków, a najwyżej {limit}. Uprość go w"
            " programie GIS — Archiwista nie upraszcza geometrii."
        ),
    ),
    "too_long": Text(
        (
            "The area edges total {length}°, but the limit is {limit}° — the area is"
            " too large to measure."
        ),
        (
            "Krawędzie obszaru mają łącznie {length}°, a najwyżej {limit}° — obszar"
            " jest zbyt rozległy, żeby go zmierzyć."
        ),
    ),
    "empty": Text(
        "The area has no surface.",
        "Obszar nie ma powierzchni.",
    ),
}
