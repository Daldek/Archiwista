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
        "a store needs at least one producer directory: kartograf or imgw",
        "magazyn wymaga co najmniej jednego katalogu producenta: kartograf albo imgw",
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
}
