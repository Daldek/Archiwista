"""Passwords and signing in: the rules of a password (ADR-046)."""

from archiwista.messages import Text

MESSAGES = {
    "password_too_short": Text(
        "The password must have at least {minimum} characters.",
        "Hasło musi mieć co najmniej {minimum} znaków.",
    ),
    "password_too_long": Text(
        "The password may have at most {maximum} characters.",
        "Hasło może mieć najwyżej {maximum} znaków.",
    ),
    "password_account_name": Text(
        "The password cannot be the account's identifier or name.",
        "Hasło nie może być identyfikatorem ani nazwą konta.",
    ),
    "password_common": Text(
        "This password is among the most common ones; choose another one.",
        "To hasło należy do najczęściej używanych; wybierz inne.",
    ),
}
