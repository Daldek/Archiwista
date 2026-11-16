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
    "readme_unpacked": Text(
        "unpacked from {archive}, SHA-256 checksum of the ZIP: {sha256}",
        "rozpakowany z {archive}, suma SHA-256 pliku ZIP: {sha256}",
    ),
    "readme_zip_kept": Text(
        "ZIP copied as it is: it does not hold exactly one raster file",
        "ZIP skopiowany bez zmian: nie zawiera dokładnie jednego pliku rastrowego",
    ),
    "readme_xyz": Text(
        (
            "the XYZ file holds no coordinate system: in QGIS set {crs}{heights};"
            " points missing from the grid are nodata"
        ),
        (
            "plik XYZ nie zawiera układu współrzędnych: w QGIS ustaw {crs}{heights};"
            " punkty brakujące w siatce to nodata"
        ),
    ),
    "readme_xyz_heights": Text(" (height system {crs})", " (układ wysokości {crs})"),
    "readme_xyz_unknown": Text(
        (
            "the XYZ file holds no coordinate system and the store names none:"
            " set it in QGIS; points missing from the grid are nodata"
        ),
        (
            "plik XYZ nie zawiera układu współrzędnych, a magazyn go nie podaje:"
            " ustaw go w QGIS; punkty brakujące w siatce to nodata"
        ),
    ),
    "readme_sources": Text(
        "Data sources and terms of use", "Źródła danych i warunki korzystania"
    ),
    "readme_no_sources": Text(
        "The store names no attribution for these files.",
        "Magazyn nie podaje atrybucji dla tych plików.",
    ),
}
