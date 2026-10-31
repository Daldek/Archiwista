"""The action log at the command line: ``archiwista log`` (plan v0.4 T8).

``action_<name>`` names each action of the log (SPEC 10.2, ``ActionName``;
the dot of a name is an underscore here), ``outcome_<outcome>`` each outcome.
"""

from archiwista.messages import Text

MESSAGES = {
    "help": Text(
        "The action log: who did what, when and from where (administrators).",
        "Dziennik działań: kto, co, kiedy i skąd zrobił (administratorzy).",
    ),
    "list_help": Text(
        (
            "Lists the action log newest first (--json: ActionPage model of GET"
            " /api/v1/log)."
        ),
        (
            "Wypisuje dziennik działań od najnowszych wpisów (--json: model ActionPage"
            " z GET /api/v1/log)."
        ),
    ),
    "export_help": Text(
        (
            "Writes every entry the filters select as JSON Lines or CSV, as GET"
            " /api/v1/log/export does, and logs the export."
        ),
        (
            "Zapisuje wszystkie wpisy wybrane filtrami jako JSON Lines albo CSV, tak"
            " jak GET /api/v1/log/export, i odnotowuje eksport w dzienniku."
        ),
    ),
    "actor_help": Text(
        "Only the entries of this person: an account id, local or -.",
        "Tylko wpisy tej osoby: identyfikator konta, local albo -.",
    ),
    "action_help": Text(
        (
            "Only this action (e.g. job.start), or every action of a group by its"
            " prefix with a dot (e.g. session.)."
        ),
        (
            "Tylko to działanie (np. job.start) albo każde działanie grupy według"
            " jej przedrostka z kropką (np. session.)."
        ),
    ),
    "outcome_help": Text(
        "Only the entries with this outcome.",
        "Tylko wpisy z tym wynikiem.",
    ),
    "target_help": Text(
        "Only the entries about this target, e.g. settings or a job id.",
        (
            "Tylko wpisy dotyczące tego obiektu, np. settings albo identyfikatora"
            " zadania."
        ),
    ),
    "since_help": Text(
        (
            "Only the entries at or after this time, ISO 8601 with a zone (e.g."
            " 2026-10-01T00:00:00+02:00)."
        ),
        (
            "Tylko wpisy od tej chwili, ISO 8601 ze strefą (np."
            " 2026-10-01T00:00:00+02:00)."
        ),
    ),
    "until_help": Text(
        "Only the entries before this time, ISO 8601 with a zone.",
        "Tylko wpisy sprzed tej chwili, ISO 8601 ze strefą.",
    ),
    "limit_help": Text(
        "Page size.",
        "Liczba wpisów na stronie.",
    ),
    "cursor_help": Text(
        "next_cursor of the previous page of the same filters.",
        "next_cursor poprzedniej strony z tymi samymi filtrami.",
    ),
    "format_help": Text(
        (
            "jsonl (JSON Lines, the default) or csv (a cell that could start a"
            " formula gets a leading ')."
        ),
        (
            "jsonl (JSON Lines, domyślnie) albo csv (komórka, która mogłaby zacząć"
            " formułę, dostaje na początku ')."
        ),
    ),
    "output_help": Text(
        (
            "file of the export, written with mode 0600 (default: standard output);"
            " an existing file is replaced"
        ),
        (
            "plik eksportu, zapisywany z trybem 0600 (domyślnie standardowe"
            " wyjście); istniejący plik zostaje zastąpiony"
        ),
    ),
    "list_line": Text(
        "{at}  {actor}: {action}, target {target}, {outcome}",
        "{at}  {actor}: {action}, obiekt {target}, {outcome}",
    ),
    "list_none": Text(
        "No entries.",
        "Brak wpisów.",
    ),
    "list_count": Text(
        "Entries: {shown} of {total}.",
        "Wpisy: {shown} z {total}.",
    ),
    "list_next": Text(
        "Older entries: --cursor {cursor}",
        "Starsze wpisy: --cursor {cursor}",
    ),
    "agent_of": Text(
        "agent of {actor}",
        "agent osoby {actor}",
    ),
    "scheduler": Text(
        "the scheduler",
        "harmonogram",
    ),
    "exported": Text(
        "Action log entries exported: {count}.",
        "Wyeksportowane wpisy dziennika działań: {count}.",
    ),
    "exported_file": Text(
        "Action log entries exported to {path}: {count}.",
        "Wyeksportowane wpisy dziennika działań do {path}: {count}.",
    ),
    "failed": Text(
        "Cannot read the action log",
        "Nie można odczytać dziennika działań",
    ),
    "outcome_ok": Text("succeeded", "udane"),
    "outcome_denied": Text("denied", "odmowa"),
    "outcome_failed": Text("failed", "nieudane"),
    "action_session_login": Text("signed in", "logowanie"),
    "action_session_login_failed": Text("failed sign-in", "nieudane logowanie"),
    "action_session_logout": Text("signed out", "wylogowanie"),
    "action_session_password": Text("password changed", "zmiana hasła"),
    "action_session_ended": Text("session ended", "zakończenie sesji"),
    "action_session_proxy_header_ignored": Text(
        "proxy header ignored", "pominięty nagłówek pośrednika"
    ),
    "action_token_issue": Text("agent token issued", "wystawienie tokenu agenta"),
    "action_token_revoke_all": Text(
        "agent tokens revoked", "unieważnienie tokenów agentów"
    ),
    "action_user_add": Text("account added", "dodanie konta"),
    "action_user_update": Text("account changed", "zmiana konta"),
    "action_user_remove": Text("account removed", "usunięcie konta"),
    "action_user_password_reset": Text("password reset", "nadanie nowego hasła"),
    "action_user_sessions_ended": Text(
        "account's sessions ended", "zakończenie sesji konta"
    ),
    "action_group_add": Text("group added", "dodanie grupy"),
    "action_group_members": Text("group members changed", "zmiana członków grupy"),
    "action_group_remove": Text("group removed", "usunięcie grupy"),
    "action_project_access": Text(
        "project sharing changed", "zmiana udostępnienia projektu"
    ),
    "action_project_create": Text("project created", "utworzenie projektu"),
    "action_project_data_dir": Text(
        "project data folder changed", "zmiana folderu danych projektu"
    ),
    "action_project_update": Text(
        "project name or description changed", "zmiana nazwy lub opisu projektu"
    ),
    "action_project_area": Text("project area changed", "zmiana obszaru projektu"),
    "action_project_store": Text("project store changed", "zmiana magazynu projektu"),
    "action_settings_update": Text("settings changed", "zmiana ustawień"),
    "action_job_start": Text("job started", "uruchomienie zadania"),
    "action_job_cancel": Text("job cancelled", "anulowanie zadania"),
    "action_job_retry": Text("job retried", "ponowienie zadania"),
    "action_permission_denied": Text("permission denied", "odmowa dostępu"),
    "action_request_refused": Text("request refused", "odmowa żądania"),
    "action_log_export": Text("log exported", "eksport dziennika"),
    "action_log_prune": Text("old entries deleted", "usunięcie starych wpisów"),
    "action_file_download": Text("file downloaded", "pobranie pliku"),
}
