"""A project's export: its ``README.txt`` (written in Polish) and its ZIP."""

from archiwista.messages import Text

MESSAGES = {
    "zip_missing": Text(
        'The export "{name}" has no ZIP file: write it again with a ZIP.',
        "Eksport „{name}” nie ma pliku ZIP: zapisz go ponownie z plikiem ZIP.",
    ),
    "readme_title": Text(
        'Export "{name}" of the project "{project}", written {written} by Archiwista.',
        "Eksport „{name}” projektu „{project}”, zapisany {written} przez Archiwistę.",
    ),
    "readme_intro": Text(
        (
            "Each folder holds the data of one category in their original formats,"
            " copied from the store; the files are yours to change. Below: every"
            " file with what is known of it."
        ),
        (
            "Każdy folder zawiera dane jednej kategorii w ich oryginalnych"
            " formatach, skopiowane z magazynu; pliki można zmieniać. Poniżej: każdy"
            " plik z tym, co o nim wiadomo."
        ),
    ),
    "readme_empty": Text(
        "The export holds no files: no pinned version was present.",
        "Eksport nie zawiera plików: żadna przypięta wersja nie była dostępna.",
    ),
    "readme_product": Text("product: {product}", "produkt: {product}"),
    "readme_year": Text("year: {year}", "rok: {year}"),
    "readme_label": Text("version: {label}", "wersja: {label}"),
    "readme_crs": Text(
        "coordinate reference system: {crs}", "układ współrzędnych: {crs}"
    ),
    "readme_vertical": Text("height system: {crs}", "układ wysokości: {crs}"),
    "readme_size": Text("size: {size} B", "rozmiar: {size} B"),
    "readme_sha256": Text("SHA-256 checksum: {sha256}", "suma SHA-256: {sha256}"),
    "readme_sets": Text("set: {sets}", "zestaw: {sets}"),
    "readme_companions": Text(
        "companion files: {files}", "pliki towarzyszące: {files}"
    ),
    "readme_sources": Text("Data sources", "Źródła danych"),
    "readme_no_sources": Text(
        "The store names no attribution for these files.",
        "Magazyn nie podaje atrybucji dla tych plików.",
    ),
}
