"""Queries of the local index with invalid parameters."""

from archiwista.messages import Text

MESSAGES = {
    "invalid_cursor": Text(
        "The cursor does not match this query — fetch the list from the first page.",
        "Kursor nie pasuje do tego zapytania — pobierz listę od pierwszej strony.",
    ),
    "invalid_limit": Text(
        "The limit must be a number from 1 to {limit}.",
        "Limit musi być liczbą od 1 do {limit}.",
    ),
    "invalid_years": Text(
        "The year range is reversed: from {start} to {end}.",
        "Zakres lat jest odwrócony: od {start} do {end}.",
    ),
    "invalid_area": Text(
        (
            "The area must be a GeoJSON polygon (Polygon or MultiPolygon) in WGS84"
            " coordinates."
        ),
        (
            "Obszar musi być wielokątem GeoJSON (Polygon albo MultiPolygon) we"
            " współrzędnych WGS84."
        ),
    ),
    "invalid_bbox": Text(
        "The map view must be a rectangle min_lon, min_lat, max_lon, max_lat in WGS84.",
        "Widok mapy musi być prostokątem min_lon, min_lat, max_lon, max_lat w WGS84.",
    ),
    "invalid_grid": Text(
        "The aggregation grid must have from 1 to {limit} columns.",
        "Siatka agregacji musi mieć od 1 do {limit} kolumn.",
    ),
    "outline_not_finite": Text(
        "Converting the footprint from {crs} to WGS84 did not yield finite coordinates",
        (
            "Przeliczenie obrysu z układu {crs} do WGS84 nie dało skończonych"
            " współrzędnych"
        ),
    ),
    "invalid_own_state": Text(
        'Unknown file state "{state}" — allowed: {allowed}.',
        "Nieznany stan pliku „{state}” — dozwolone: {allowed}.",
    ),
    "invalid_river_code": Text(
        "The river's hydrographic code must not be empty.",
        "Kod hydrograficzny rzeki nie może być pusty.",
    ),
    "coverage_without_dataset": Text(
        (
            "A coverage filter needs a dataset: a label belongs to the series of"
            " one dataset."
        ),
        (
            "Filtr pokrycia wymaga zbioru danych: etykieta dotyczy szeregu jednego"
            " zbioru."
        ),
    ),
}
