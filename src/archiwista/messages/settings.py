"""Validation of the settings and the basemap rules."""

from archiwista.messages import Text

MESSAGES = {
    "invalid_toml": Text(
        "Configuration file {path} is not valid TOML: {detail}",
        "Plik konfiguracji {path} nie jest poprawnym TOML: {detail}",
    ),
    "invalid_value": Text(
        'Invalid setting "{field}": {detail}',
        "Niepoprawne ustawienie „{field}”: {detail}",
    ),
    "missing": Text(
        "missing required value",
        "brak wymaganej wartości",
    ),
    "unknown_key": Text(
        "unknown setting",
        "nieznane ustawienie",
    ),
    "not_integer": Text(
        "an integer is expected",
        "oczekiwano liczby całkowitej",
    ),
    "not_boolean": Text(
        "true or false is expected",
        "oczekiwano wartości true albo false",
    ),
    "not_text": Text(
        "text is expected",
        "oczekiwano tekstu",
    ),
    "not_list": Text(
        "a list is expected",
        "oczekiwano listy",
    ),
    "too_small": Text(
        "value is less than {limit}",
        "wartość mniejsza niż {limit}",
    ),
    "too_large": Text(
        "value is greater than {limit}",
        "wartość większa niż {limit}",
    ),
    "bad_value": Text(
        "invalid value",
        "niepoprawna wartość",
    ),
    "path_not_absolute": Text(
        "the path must be absolute",
        "ścieżka musi być bezwzględna",
    ),
    "store_id_pattern": Text(
        ('identifier: lower-case letters, digits, "-" and "_", at most 32 characters'),
        "identyfikator: małe litery, cyfry, „-” i „_”, najwyżej 32 znaki",
    ),
    "store_needs_directory": Text(
        "a store needs at least one producer directory: kartograf or obserwator",
        (
            "magazyn wymaga co najmniej jednego katalogu producenta: kartograf albo"
            " obserwator"
        ),
    ),
    "empty_text": Text(
        "the value must not be empty",
        "wartość nie może być pusta",
    ),
    "duplicate_store": Text(
        'store identifier "{value}" is duplicated',
        "identyfikator magazynu „{value}” powtarza się",
    ),
    "duplicate_basemap": Text(
        'basemap name "{value}" is duplicated',
        "nazwa podkładu „{value}” powtarza się",
    ),
    "basemap_url": Text(
        "the basemap URL must start with http:// or https://",
        "adres podkładu musi zaczynać się od http:// albo https://",
    ),
    "basemap_xyz": Text(
        "the tile URL must contain {{z}}, {{x}} and {{y}}",
        "adres kafli musi zawierać {{z}}, {{x}} i {{y}}",
    ),
    "basemap_vector": Text(
        "a vector basemap points to a TileJSON URL, without {{z}}, {{x}} and {{y}}",
        "podkład wektorowy wskazuje adres TileJSON, bez {{z}}, {{x}} i {{y}}",
    ),
    "default_visibility": Text(
        "allowed values: public, private",
        "dozwolone wartości: public, private",
    ),
    "team_origin": Text(
        (
            "the address people open: https://, a host and an optional port, nothing"
            " else (no path); required with enabled = true"
        ),
        (
            "adres, który otwierają ludzie: https://, host i opcjonalny port, nic"
            " więcej (bez ścieżki); wymagany przy enabled = true"
        ),
    ),
    "team_tls_pair": Text(
        "tls_cert and tls_key go together: give both files or neither",
        "tls_cert i tls_key idą w parze: podaj oba pliki albo żaden",
    ),
    "team_proxy": Text(
        "an IP address or a network of at most {limit} addresses (IPv4 /24, IPv6 /120)",
        ("adres IP albo sieć najwyżej {limit} adresów (IPv4 /24, IPv6 /120)"),
    ),
    "team_proxy_header": Text(
        (
            "a header name (an HTTP token) other than Host, Cookie, Authorization,"
            " Origin, X-Forwarded-* and X-Archiwista-*, used with trusted_proxies"
        ),
        (
            "nazwa nagłówka (token HTTP) inna niż Host, Cookie, Authorization,"
            " Origin, X-Forwarded-* i X-Archiwista-*, razem z trusted_proxies"
        ),
    ),
    "team_proxy_autocreate": Text(
        "proxy_autocreate needs proxy_user_header",
        "proxy_autocreate wymaga proxy_user_header",
    ),
    "shared_missing": Text(
        (
            "The settings file of the Nogat tools {path}, named by {variable},"
            " does not exist"
        ),
        (
            "Plik ustawień narzędzi Nogat {path}, wskazany zmienną {variable},"
            " nie istnieje"
        ),
    ),
    "shared_unreadable": Text(
        "The settings file of the Nogat tools {path} cannot be read: {detail}",
        "Nie można odczytać pliku ustawień narzędzi Nogat {path}: {detail}",
    ),
    "shared_not_utf8": Text(
        "The settings file of the Nogat tools {path} is not UTF-8 text",
        "Plik ustawień narzędzi Nogat {path} nie jest tekstem UTF-8",
    ),
    "shared_invalid_toml": Text(
        "The settings file of the Nogat tools {path} is not valid TOML: {detail}",
        "Plik ustawień narzędzi Nogat {path} nie jest poprawnym TOML: {detail}",
    ),
    "shared_not_table": Text(
        "[{table}] of the settings file of the Nogat tools {path} is not a table",
        "[{table}] w pliku ustawień narzędzi Nogat {path} nie jest tabelą",
    ),
    "shared_directory": Text(
        (
            "{key} of [{table}] in the settings file of the Nogat tools {path} is"
            " not an absolute path: {value}"
        ),
        (
            "{key} w [{table}] pliku ustawień narzędzi Nogat {path} nie jest"
            " ścieżką bezwzględną: {value}"
        ),
    ),
    "shared_lang": Text(
        (
            "lang of [{table}] in the settings file of the Nogat tools {path} is"
            " neither pl nor en: {value}"
        ),
        (
            "lang w [{table}] pliku ustawień narzędzi Nogat {path} to ani pl,"
            " ani en: {value}"
        ),
    ),
    "shared_gui": Text(
        (
            "gui of [{table}] in the settings file of the Nogat tools {path} is not"
            ' a table of GUI addresses (e.g. hydrolog = "http://127.0.0.1:8070/"):'
            " {value}"
        ),
        (
            "gui w [{table}] pliku ustawień narzędzi Nogat {path} nie jest tabelą"
            ' adresów GUI (np. hydrolog = "http://127.0.0.1:8070/"): {value}'
        ),
    ),
    "shared_gui_address": Text(
        (
            "{name} of [{table}.gui] in the settings file of the Nogat tools {path}"
            " is not an address: {value}"
        ),
        (
            "{name} w [{table}.gui] pliku ustawień narzędzi Nogat {path} nie jest"
            " adresem: {value}"
        ),
    ),
}
