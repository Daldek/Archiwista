"""Texts shared by every area."""

from archiwista.messages import Text

MESSAGES = {
    "with_detail": Text(
        "{message}: {detail}",
        "{message}: {detail}",
    ),
    "with_detail_sentence": Text(
        "{message:sentence}: {detail}{end}",
        "{message:sentence}: {detail}{end}",
    ),
}
