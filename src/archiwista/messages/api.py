"""The HTTP API: refusals of a request, unknown resources and invalid parameters."""

from archiwista.messages import Text

MESSAGES = {
    "request_too_large": Text(
        "The request body exceeds the limit of {limit}.",
        "Treść żądania przekracza limit {limit}.",
    ),
    "invalid_host": Text(
        "Archiwista accepts only requests to 127.0.0.1:{port} or localhost:{port}.",
        (
            "Archiwista przyjmuje tylko żądania na adres 127.0.0.1:{port} albo"
            " localhost:{port}."
        ),
    ),
    "invalid_host_team": Text(
        "Archiwista accepts only requests to {origin}.",
        "Archiwista przyjmuje tylko żądania na adres {origin}.",
    ),
    "tls_required": Text(
        "Archiwista answers only over HTTPS: open {origin}.",
        "Archiwista odpowiada tylko przez HTTPS: otwórz {origin}.",
    ),
    "proxy_required": Text(
        ("Archiwista answers only through the team's reverse proxy, not directly."),
        (
            "Archiwista odpowiada tylko przez serwer pośredniczący zespołu, a nie"
            " bezpośrednio."
        ),
    ),
    "session_required": Text(
        (
            'No valid session. Open the address printed by "archiwista serve" or'
            ' issue a new one with the "archiwista token" command.'
        ),
        (
            "Brak ważnej sesji. Otwórz adres wypisany przez „archiwista serve” albo"
            " wystaw nowy poleceniem „archiwista token”."
        ),
    ),
    "hint_session_required": Text(
        (
            "Exchange the one-time token for a session: POST /api/v1/session"
            ' ("archiwista token" prints the address with the token).'
        ),
        (
            "Wymień jednorazowy token na sesję: POST /api/v1/session („archiwista"
            " token” wypisuje adres z tokenem)."
        ),
    ),
    "token_rejected": Text(
        (
            "The token is unknown, has expired, or has already been used. Issue a new"
            ' one with the "archiwista token" command.'
        ),
        (
            "Token jest nieznany, wygasł albo został już użyty. Wystaw nowy poleceniem"
            " „archiwista token”."
        ),
    ),
    "session_ended": Text(
        (
            "The session has ended: the account is disabled or deleted, or the owner"
            ' ended the agent sessions ("archiwista token --revoke-all"). Open a new'
            " session."
        ),
        (
            "Sesja zakończyła się: konto jest wyłączone albo usunięte, albo właściciel"
            " zakończył sesje agentów („archiwista token --revoke-all”). Otwórz nową"
            " sesję."
        ),
    ),
    "cross_site": Text(
        "A request sent from another site was rejected.",
        "Żądanie wysłane z innej strony zostało odrzucone.",
    ),
    "origin_missing": Text(
        "The browser did not provide the Origin header on a state-changing request.",
        "Przeglądarka nie podała nagłówka Origin przy żądaniu zmieniającym stan.",
    ),
    "csrf_missing": Text(
        (
            "Missing X-Archiwista-CSRF header with the session's CSRF token"
            " (csrf_token from the POST /api/v1/session response); every /api request"
            " requires it."
        ),
        (
            "Brak nagłówka X-Archiwista-CSRF z tokenem CSRF sesji (csrf_token z"
            " odpowiedzi POST /api/v1/session); wymaga go każde żądanie /api."
        ),
    ),
    "csrf_mismatch": Text(
        "The X-Archiwista-CSRF header does not match the CSRF token of this session.",
        "Nagłówek X-Archiwista-CSRF nie pasuje do tokenu CSRF tej sesji.",
    ),
    "validation_error": Text(
        "Invalid request data: {fields}.",
        "Niepoprawne dane żądania: {fields}.",
    ),
    "value_error": Text(
        "Value error, {detail}",
        "Błąd wartości, {detail}",
    ),
    "interface_missing": Text(
        "The interface files are not installed.",
        "Pliki interfejsu nie są zainstalowane.",
    ),
    "route_not_found": Text(
        "No such resource.",
        "Nie ma takiego zasobu.",
    ),
    "method_not_allowed": Text(
        "The {method} method is not available for {path}.",
        "Metoda {method} nie jest dostępna dla {path}.",
    ),
    "internal_error": Text(
        'Internal server error; details are in the "archiwista serve" log.',
        "Wewnętrzny błąd serwera; szczegóły są w dzienniku „archiwista serve”.",
    ),
    "source_problem": Text(
        "{message}. Fix: {fix}",
        "{message}. Naprawa: {fix}",
    ),
    "store_not_configured": Text(
        'There is no store "{store}" in the settings.',
        "Nie ma magazynu „{store}” w ustawieniach.",
    ),
    "store_unknown": Text(
        'There is no store "{store}" in the settings or in the index.',
        "Nie ma magazynu „{store}” w ustawieniach ani w indeksie.",
    ),
    "slot_unknown": Text(
        'The index does not know the file "{slot}" in store "{store}".',
        "Indeks nie zna pliku „{slot}” w magazynie „{store}”.",
    ),
    "version_unknown": Text(
        'The index does not know version "{version}" in store "{store}".',
        "Indeks nie zna wersji „{version}” w magazynie „{store}”.",
    ),
    "sidecar_missing": Text(
        'Version "{version}" in store "{store}" has no readable sidecar.',
        "Wersja „{version}” w magazynie „{store}” nie ma czytelnego sidecara.",
    ),
    "file_member_unknown": Text(
        'The set of "{ref}" holds no file "{member}".',
        "Zestaw „{ref}” nie zawiera pliku „{member}”.",
    ),
    "file_missing": Text(
        (
            'The file of "{ref}" is not on the disk any more; the next scan updates'
            " the index."
        ),
        "Pliku „{ref}” nie ma już na dysku; następny skan zaktualizuje indeks.",
    ),
    "file_unreadable": Text(
        (
            'The file of "{ref}" cannot be downloaded: its last scan could not read'
            " it, or the snapshot is not valid."
        ),
        (
            "Nie można pobrać pliku „{ref}”: ostatni skan nie mógł go odczytać albo"
            " migawka jest nieważna."
        ),
    ),
    "too_many_downloads": Text(
        (
            "The limit of downloads at once per person ({limit}) is reached: try again"
            " when one of yours has ended."
        ),
        (
            "Osiągnięto limit jednoczesnych pobrań na osobę ({limit}): spróbuj"
            " ponownie, gdy któreś z twoich się skończy."
        ),
    ),
    "request_unknown": Text(
        'The index does not know the files of producer job "{parent_request}".',
        "Indeks nie zna plików zadania producenta „{parent_request}”.",
    ),
    "area_unknown": Text(
        'There is no area "{area}".',
        "Nie ma obszaru „{area}”.",
    ),
    "area_and_bbox": Text(
        "Provide an area (area_id) or a rectangle (bbox), not both at once.",
        "Podaj obszar (area_id) albo prostokąt (bbox), nie oba naraz.",
    ),
    "bbox_invalid": Text(
        "bbox is four numbers: min_x,min_y,max_x,max_y.",
        "bbox to cztery liczby: min_x,min_y,max_x,max_y.",
    ),
    "years_invalid": Text(
        "years is a year or a range of years: 2023, 2020-2023, 2020- or -2023.",
        "years to rok albo zakres lat: 2023, 2020-2023, 2020- albo -2023.",
    ),
    "station_years_invalid": Text(
        "years is a year or a range of years: 2025 or 1951-2025.",
        "years to rok albo zakres lat: 2025 albo 1951-2025.",
    ),
    "coverage_filter_invalid": Text(
        (
            'A coverage filter is variable:state, e.g. Q:continuous, not "{value}";'
            " states: {states}."
        ),
        (
            "Filtr pokrycia to zmienna:stan, np. Q:continuous, a nie „{value}”;"
            " stany: {states}."
        ),
    ),
    "min_complete_years_invalid": Text(
        'A minimum of full years is variable:years, e.g. Q:30, not "{value}".',
        "Najmniejsza liczba pełnych lat to zmienna:lata, np. Q:30, a nie „{value}”.",
    ),
    "station_unknown": Text(
        'There is no station "{code}" in the station catalogs of the index.',
        "Nie ma stacji „{code}” w katalogach stacji indeksu.",
    ),
    "station_ambiguous": Text(
        'The code "{code}" names several stations: {stations}.',
        "Kod „{code}” oznacza kilka stacji: {stations}.",
    ),
    "station_ambiguous_hint": Text(
        "Name the station's store and provider (store, provider).",
        "Podaj magazyn i dostawcę stacji (store, provider).",
    ),
    "no_geo_source": Text(
        "No available data source converts the coordinates of the area.",
        "Żadne dostępne źródło danych nie przelicza współrzędnych obszaru.",
    ),
    "too_many_sheets": Text(
        (
            "The view covers about {count} sheets at scale {scale}, and the maximum is"
            " {limit} — zoom in on the map or choose a less detailed scale."
        ),
        (
            "Widok obejmuje około {count} arkuszy w skali {scale}, a najwyżej {limit}"
            " — przybliż mapę albo wybierz mniej szczegółową skalę."
        ),
    ),
    "project_store_unavailable": Text(
        (
            'Store "{store}" of project "{project}" is unavailable, and no scan'
            " has checked the project yet."
        ),
        (
            "Magazyn „{store}” projektu „{project}” jest niedostępny, a żaden skan nie"
            " sprawdził jeszcze projektu."
        ),
    ),
    "refresh_view_timeout": Text(
        "Refreshing the view exceeded {seconds} s — the result comes from the index",
        "Odświeżenie widoku przekroczyło {seconds} s — wynik pochodzi z indeksu",
    ),
}
