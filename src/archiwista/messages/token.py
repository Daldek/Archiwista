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
}
