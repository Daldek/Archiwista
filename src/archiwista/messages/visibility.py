"""Names of the visibilities of a project."""

from archiwista.messages import Text

MESSAGES = {
    "public": Text(
        "public (everyone)",
        "publiczny (wszyscy)",
    ),
    "users": Text(
        "selected people",
        "wybrane osoby",
    ),
    "group": Text(
        "members of selected groups",
        "członkowie wybranych grup",
    ),
    "private": Text(
        "private (owner only)",
        "prywatny (tylko właściciel)",
    ),
}
