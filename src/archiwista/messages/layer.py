"""Layers of years, campaigns and releases."""

from archiwista.messages import Text

MESSAGES = {
    "title_year": Text(
        "{year}",
        "{year}",
    ),
    "title_edition": Text(
        "edition {edition}",
        "wydanie {edition}",
    ),
    "title_label": Text(
        "{label}",
        "{label}",
    ),
    "title_undated": Text(
        "no year or edition",
        "bez roku i wydania",
    ),
    "title_campaign": Text(
        "{title} · campaign {campaign}",
        "{title} · kampania {campaign}",
    ),
    "title_working": Text(
        "working file",
        "plik roboczy",
    ),
    "title_snapshot": Text(
        "snapshot {label}",
        "migawka {label}",
    ),
    "subtitle_note": Text(
        "{path} · {note}",
        "{path} · {note}",
    ),
    "unknown": Text(
        (
            'Product "{product}" has no layer "{layer}" at this location; fetch'
            " the current list of layers (GET /api/v1/local-layers)."
        ),
        (
            "Produkt „{product}” nie ma w tym miejscu warstwy „{layer}”; pobierz"
            " aktualną listę warstw (GET /api/v1/local-layers)."
        ),
    ),
    "area_required": Text(
        (
            "The layer thumbnail and tiles are per area: provide area_id from the"
            " layer list."
        ),
        "Miniatura i kafle warstwy są dla obszaru: podaj area_id z listy warstw.",
    ),
    "no_frame": Text(
        (
            "The area has no planar grid (PL or CZ), so the layer has no thumbnail;"
            " use the tiles on the map."
        ),
        (
            "Obszar nie ma układu płaskiego (PL albo CZ), więc warstwa nie ma"
            " miniatury; użyj kafli na mapie."
        ),
    ),
    "tile_below_minzoom": Text(
        (
            "A layer tile at z = {z} would cover too many sheets; the layer preview"
            " starts at z = {minzoom} (zoom the map in)."
        ),
        (
            "Kafel warstwy przy z = {z} obejmowałby zbyt wiele arkuszy; podgląd"
            " warstwy zaczyna się od z = {minzoom} (przybliż mapę)."
        ),
    ),
    "tile_outside": Text(
        "Tile {z}/{x}/{y} lies outside the layer extent.",
        "Kafel {z}/{x}/{y} leży poza zasięgiem warstwy.",
    ),
    "style_unknown": Text(
        (
            'Style "{style}" is not available for this layer version; available:'
            " {styles}."
        ),
        "Styl „{style}” nie jest dostępny dla wersji tej warstwy; dostępne: {styles}.",
    ),
}
