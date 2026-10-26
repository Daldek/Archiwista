"""Starting the server: on the loopback address, or in team mode (ADR-046)."""

from archiwista.messages import Text

MESSAGES = {
    "host_refused": Text(
        (
            "Refusing to start on address {host}: Archiwista listens beyond"
            " {loopback} only in team mode, with sign-in and TLS."
        ),
        (
            "Odmowa uruchomienia na adresie {host}: poza {loopback} Archiwista"
            " nasłuchuje tylko w trybie zespołu, z logowaniem i TLS."
        ),
    ),
    "hint_host_refused": Text(
        (
            "Leave out --host, or turn team mode on in the table [team] of"
            ' config.toml (USAGE, "Team server").'
        ),
        (
            "Pomiń --host albo włącz tryb zespołu w tabeli [team] pliku config.toml"
            " (USAGE, „Team server”)."
        ),
    ),
    "host_not_address": Text(
        "In team mode --host is an IP address of this computer, not {host}.",
        "W trybie zespołu --host to adres IP tego komputera, a nie {host}.",
    ),
    "hint_host_address": Text(
        (
            "Give an IPv4 or IPv6 address, e.g. 0.0.0.0 with TLS in the server, or"
            " the address a reverse proxy connects to."
        ),
        (
            "Podaj adres IPv4 albo IPv6, np. 0.0.0.0 przy TLS w serwerze albo"
            " adres, z którym łączy się serwer pośredniczący."
        ),
    ),
    "tls_required": Text(
        (
            "Team mode needs TLS: in the server (tls_cert and tls_key) or in a"
            " reverse proxy named in trusted_proxies."
        ),
        (
            "Tryb zespołu wymaga TLS: w serwerze (tls_cert i tls_key) albo w"
            " serwerze pośredniczącym wpisanym w trusted_proxies."
        ),
    ),
    "hint_tls_required": Text(
        (
            "Set tls_cert and tls_key in [team], or run Archiwista behind Caddy or"
            " nginx with TLS and set trusted_proxies."
        ),
        (
            "Ustaw tls_cert i tls_key w [team] albo uruchom Archiwistę za Caddy"
            " lub nginx z TLS i ustaw trusted_proxies."
        ),
    ),
    "tls_unusable": Text(
        "The TLS files cannot be used: certificate {cert}, key {key}",
        "Nie można użyć plików TLS: certyfikat {cert}, klucz {key}",
    ),
    "hint_tls_unusable": Text(
        (
            "Give the certificate chain and its private key, without a passphrase,"
            ' as PEM files; "archiwista doctor" checks them.'
        ),
        (
            "Podaj łańcuch certyfikatów i jego klucz prywatny, bez hasła, jako"
            " pliki PEM; sprawdza je „archiwista doctor”."
        ),
    ),
    "tls_key_encrypted": Text(
        (
            "the private key is encrypted; the server reads it without a passphrase,"
            " protected by the permissions of its file"
        ),
        (
            "klucz prywatny jest zaszyfrowany; serwer czyta go bez hasła, chroniony"
            " uprawnieniami pliku"
        ),
    ),
    "proxy_bind_wildcard": Text(
        (
            "Behind a reverse proxy, without TLS in the server, Archiwista does not"
            " listen on every address ({host})."
        ),
        (
            "Za serwerem pośredniczącym, bez TLS w serwerze, Archiwista nie"
            " nasłuchuje na wszystkich adresach ({host})."
        ),
    ),
    "hint_proxy_bind_wildcard": Text(
        (
            "Give --host the address the proxy connects to, e.g. 127.0.0.1 for a"
            " proxy on this computer."
        ),
        (
            "Podaj w --host adres, z którym łączy się serwer pośredniczący, np."
            " 127.0.0.1 dla serwera na tym komputerze."
        ),
    ),
    "proxy_bind_not_loopback": Text(
        (
            "Every trusted proxy is on this computer, so Archiwista listens on a"
            " loopback address, not on {host}."
        ),
        (
            "Każdy zaufany serwer pośredniczący jest na tym komputerze, więc"
            " Archiwista nasłuchuje na adresie pętli zwrotnej, a nie na {host}."
        ),
    ),
    "hint_proxy_bind_not_loopback": Text(
        "Use --host 127.0.0.1, or name the proxy's own address in trusted_proxies.",
        (
            "Użyj --host 127.0.0.1 albo wpisz własny adres serwera pośredniczącego"
            " w trusted_proxies."
        ),
    ),
    "failed": Text(
        "Cannot start Archiwista",
        "Nie można uruchomić Archiwisty",
    ),
    "port_unavailable": Text(
        "Cannot listen on {host}:{port}",
        "Nie można nasłuchiwać na {host}:{port}",
    ),
    "started": Text(
        (
            "Archiwista is running. Open in a browser:\n  {url}\nThe address contains"
            ' a one-time token valid for {minutes} min; "archiwista token" issues'
            " another one. To stop: Ctrl+C."
        ),
        (
            "Archiwista działa. Otwórz w przeglądarce:\n  {url}\nAdres zawiera"
            " jednorazowy token ważny {minutes} min; kolejny wystawia „archiwista"
            " token”. Zatrzymanie: Ctrl+C."
        ),
    ),
    "started_team": Text(
        (
            "Archiwista is running in team mode at:\n  {origin}\nIt listens on"
            " {address}; people sign in at that address. To stop: Ctrl+C."
        ),
        (
            "Archiwista działa w trybie zespołu pod adresem:\n  {origin}\nNasłuchuje"
            " na {address}; ludzie logują się pod tym adresem. Zatrzymanie: Ctrl+C."
        ),
    ),
    "launch_link": Text(
        "Open Archiwista",
        "Otwórz Archiwistę",
    ),
}
