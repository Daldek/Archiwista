"""Starting the server on the loopback address."""

from archiwista.messages import Text

MESSAGES = {
    "host_refused": Text(
        (
            "Refusing to start on address {host}: without team mode Archiwista listens"
            " only on {loopback}."
        ),
        (
            "Odmowa uruchomienia na adresie {host}: bez trybu zespołu Archiwista"
            " nasłuchuje wyłącznie na {loopback}."
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
    "launch_link": Text(
        "Open Archiwista",
        "Otwórz Archiwistę",
    ),
}
