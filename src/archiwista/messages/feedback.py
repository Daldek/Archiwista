"""Feedback reports of "Zgłoś uwagę": ``POST /feedback`` and ``/admin/feedback``."""

from archiwista.messages import Text

MESSAGES = {
    "message_blank": Text(
        "the description must not be empty",
        "opis nie może być pusty",
    ),
    "diagnostics_too_large": Text(
        "the diagnostics exceed the limit of {limit} characters of JSON",
        "dane diagnostyczne przekraczają limit {limit} znaków JSON",
    ),
}
