"""Polish texts of the local layers (plan v0.2, decision 7, step 11).

Titles of the layers of a product (a data year, an edition, a label, a
campaign), the refusals of their thumbnails and map tiles, and the texts of
``archiwista layers``.
"""

from types import MappingProxyType

LAYER_MESSAGES = MappingProxyType(
    {
        # Titles of a layer: its year, edition or label, and its campaign.
        "layer_title_year": "{year}",
        "layer_title_edition": "wydanie {edition}",
        "layer_title_label": "{label}",
        "layer_title_undated": "bez roku i wydania",
        "layer_title_campaign": "{title} · kampania {campaign}",
        # Images of a layer over HTTP.
        "layer_unknown": (
            "Produkt „{product}” nie ma w tym miejscu warstwy „{layer}”; pobierz"
            " aktualną listę warstw (GET /api/v1/local-layers)."
        ),
        "layer_area_required": (
            "Miniatura i kafle warstwy są dla obszaru: podaj area_id z listy warstw."
        ),
        "layer_no_frame": (
            "Obszar nie ma układu płaskiego (PL albo CZ), więc warstwa nie ma"
            " miniatury; użyj kafli na mapie."
        ),
        "layer_tile_below_minzoom": (
            "Kafel warstwy przy z = {z} obejmowałby zbyt wiele arkuszy; podgląd"
            " warstwy zaczyna się od z = {minzoom} (przybliż mapę)."
        ),
        "layer_tile_outside": "Kafel {z}/{x}/{y} leży poza zasięgiem warstwy.",
        "layer_style_unknown": (
            "Styl „{style}” nie jest dostępny dla wersji tej warstwy; dostępne:"
            " {styles}."
        ),
        # ``archiwista layers`` (decision 11).
        "cli_layers_help": (
            "Warstwy lat, kampanii i wydań produktu w magazynie (--json: model"
            " LayerSet), z obszarem po odświeżeniu jego slotów; --thumbnail"
            " zapisuje miniaturę warstwy do pliku PNG."
        ),
        "cli_layers_store_help": "Identyfikator magazynu z ustawień.",
        "cli_layers_product_help": "Produkt, np. nmt.",
        "cli_layers_area_help": (
            "Identyfikator obszaru (POST /api/v1/areas); bez niego tylko liczby"
            " wersji w całym magazynie."
        ),
        "cli_layers_segment_help": "Tylko ten segment (wariant) produktu.",
        "cli_layers_group_help": (
            "year (domyślnie): warstwa na rok danych; campaign: rok dzielony"
            " na kampanie."
        ),
        "cli_layers_thumbnail_help": (
            "Klucz warstwy (pole key) do zapisania jej miniatury przez --output."
        ),
        "cli_layers_size_help": ("Bok miniatury warstwy w pikselach (domyślnie 512)."),
        "cli_layers_output_help": (
            "Plik PNG miniatury warstwy, rysowanej tym samym procesem renderującym"
            " i przez tę samą pamięć podglądów co serwer."
        ),
        "cli_layers_output_required": "--thumbnail wymaga --output PLIK.png.",
        "cli_layers_failed": "Nie można odczytać warstw",
        "cli_layers_written": (
            "Zapisano miniaturę warstwy {layer} do {path} ({size} px, styl {style})."
        ),
        "cli_layers_heading": ("{store} · {product}: {count} warstw, obszar {area}"),
        "cli_layers_whole_store": "cały magazyn",
        "cli_layers_stale": "Odpowiedź z indeksu bez odświeżenia: {reason}.",
        "cli_layers_layer": (
            "{key}  {title} · {subtitle} · wersje {versions}, jednostki {units}"
        ),
        "cli_layers_formats": "    formaty: {formats}",
        "cli_layers_coverage": "    {label}",
        "cli_layers_preview": ("    podglądy: {ready}/{total} ({state}){job}"),
        "cli_layers_preview_job": ", zadanie {job}",
    }
)
