"""Refusals for a missing right (A-ADR-029)."""

from archiwista.messages import Text

MESSAGES = {
    "session_tokens": Text(
        (
            "An agent session does not issue tokens for further sessions; the owner or"
            ' the owner\'s browser issues a token for the agent ("archiwista token").'
        ),
        (
            "Sesja agenta nie wystawia tokenów kolejnych sesji; token dla agenta"
            " wystawia właściciel („archiwista token”) albo jego przeglądarka."
        ),
    ),
    "session_password": Text(
        (
            "An agent session does not change its account's password; the person"
            " does it in their own session."
        ),
        (
            "Sesja agenta nie zmienia hasła swojego konta; zmienia je sama osoba"
            " w swojej sesji."
        ),
    ),
    "project_view": Text(
        "No access to this project.",
        "Brak dostępu do tego projektu.",
    ),
    "project_share": Text(
        "Only the project owner or an administrator can change project sharing.",
        "Udostępnienie projektu zmienia tylko jego właściciel albo administrator.",
    ),
    "users_manage": Text(
        "Managing accounts requires the administrator role.",
        "Zarządzanie kontami wymaga roli administratora.",
    ),
    "groups_manage": Text(
        "Managing groups requires the administrator role.",
        "Zarządzanie grupami wymaga roli administratora.",
    ),
    "settings_write": Text(
        "Changing settings requires the administrator role.",
        "Zmiana ustawień wymaga roli administratora.",
    ),
    "store_write": Text(
        (
            'Writing to the store requires the "zapis do magazynu" (write to store)'
            " permission (role store_writer)."
        ),
        "Zapis do magazynu wymaga uprawnienia „zapis do magazynu” (rola store_writer).",
    ),
    "project_write": Text(
        (
            "Only the project owner or an administrator can create snapshots and make"
            " changes to the project."
        ),
        "Migawkę i zmiany projektu robi tylko jego właściciel albo administrator.",
    ),
    "project_create": Text(
        "A project is created by a person or their agent, not by the scheduler.",
        "Projekt zakłada osoba albo jej agent, nie harmonogram.",
    ),
    "store_scan": Text(
        (
            "Scanning a store, outlining its units and checking its links require"
            " the administrator role; the server also scans on its own schedule."
        ),
        (
            "Skan magazynu, obrysy jednostek i sprawdzenie dowiązań wymagają roli"
            " administratora; serwer skanuje też sam, według harmonogramu."
        ),
    ),
    "job_cancel": Text(
        "Only whoever started a job or an administrator can cancel it.",
        "Zadanie anuluje tylko ten, kto je uruchomił, albo administrator.",
    ),
    "job_log": Text(
        (
            "The log of this job also covers files of projects you do not see; only"
            " someone who sees all of them can read it."
        ),
        (
            "Dziennik tego zadania dotyczy też plików projektów, których nie widzisz;"
            " czyta go tylko ten, kto widzi je wszystkie."
        ),
    ),
}
