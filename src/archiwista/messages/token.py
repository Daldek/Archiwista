"""Agent session tokens."""

from archiwista.messages import Text

MESSAGES = {
    "failed": Text(
        "Cannot issue the token",
        "Nie można wystawić tokenu",
    ),
    "issued": Text(
        (
            "One-time agent session address (label {label}), valid for {minutes} min"
            " (until {time}). Pass it to the agent or open it in a browser; an agent"
            " session lasts at most {hours} h."
        ),
        (
            "Jednorazowy adres sesji agenta (etykieta {label}), ważny {minutes} min"
            " (do {time}). Przekaż go agentowi albo otwórz w przeglądarce; sesja agenta"
            " trwa najwyżej {hours} h."
        ),
    ),
    "revoked": Text(
        (
            "Agent sessions ended; unused agent tokens revoked: {count}. A new agent"
            ' session requires a new token ("archiwista token").'
        ),
        (
            "Sesje agentów zakończone; unieważnione niewykorzystane tokeny agentów:"
            " {count}. Nowa sesja agenta wymaga nowego tokenu („archiwista token”)."
        ),
    ),
    "user_required": Text(
        (
            "Team mode has no local owner for the agent to act for: name its account"
            ' ("archiwista token --user ID").'
        ),
        (
            "Tryb zespołowy nie ma właściciela lokalnego, w którego imieniu działałby"
            " agent: podaj jego konto („archiwista token --user ID”)."
        ),
    ),
    "user_disabled": Text(
        "The account {id} is disabled: no agent acts for it.",
        "Konto {id} jest wyłączone: żaden agent nie działa w jego imieniu.",
    ),
    "user_with_revoke_all": Text(
        (
            "--revoke-all ends the sessions of every agent and takes no --user; to"
            ' end one account\'s sessions use "archiwista users end-sessions ID".'
        ),
        (
            "--revoke-all kończy sesje wszystkich agentów i nie przyjmuje --user;"
            " sesje jednego konta kończy „archiwista users end-sessions ID”."
        ),
    ),
}
