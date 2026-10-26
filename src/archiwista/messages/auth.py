"""Passwords and signing in: the rules of a password, sign-in refusals (ADR-046)."""

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
    "login_failed": Text(
        "The account or the password is wrong.",
        "Nieprawidłowe konto albo hasło.",
    ),
    "password_expired": Text(
        ("The temporary password has expired; ask an administrator for a new one."),
        "Hasło tymczasowe wygasło; poproś administratora o nowe.",
    ),
    "login_blocked": Text(
        (
            "Too many failed sign-ins of this account or from this computer; try"
            " again after the wait (Retry-After)."
        ),
        (
            "Zbyt wiele nieudanych logowań tego konta albo z tego komputera;"
            " spróbuj ponownie po odczekaniu (Retry-After)."
        ),
    ),
    "wrong_password": Text(
        "The current password is wrong.",
        "Obecne hasło jest nieprawidłowe.",
    ),
    "password_change_required": Text(
        (
            "Change the temporary password first (PUT /api/v1/session/password);"
            " until then the session can only sign out."
        ),
        (
            "Najpierw zmień hasło tymczasowe (PUT /api/v1/session/password); do"
            " tego czasu sesja może się tylko wylogować."
        ),
    ),
    "local_mode": Text(
        (
            "Local mode has no sign-in or passwords: open the address printed by"
            ' "archiwista serve" or "archiwista token".'
        ),
        (
            "Tryb lokalny nie ma logowania ani haseł: otwórz adres wypisany przez"
            " „archiwista serve” albo „archiwista token”."
        ),
    ),
    "proxy_session": Text(
        (
            "This session signed in through the company's reverse proxy; its"
            " password is changed there, not in Archiwista."
        ),
        (
            "Ta sesja zalogowała się przez firmowy serwer pośredniczący; hasło"
            " zmienia się tam, nie w Archiwiście."
        ),
    ),
    "proxy_login_failed": Text(
        (
            "Signing in through the company's reverse proxy failed: it names no"
            " enabled account of Archiwista. Ask an administrator."
        ),
        (
            "Logowanie przez firmowy serwer pośredniczący nie powiodło się: nie"
            " wskazuje on włączonego konta Archiwisty. Zwróć się do administratora."
        ),
    ),
    "session_unknown": Text(
        "No live session that you may end has the label {label}.",
        "Żadna trwająca sesja, którą możesz zakończyć, nie ma etykiety {label}.",
    ),
}
