"""The availability at the source: the refusals of a request and of a stored report."""

from archiwista.messages import Text

MESSAGES = {
    "product_unsupported": Text(
        (
            'The source {producer} checks no availability of "{product}"; it checks:'
            " {allowed}."
        ),
        "Źródło {producer} nie sprawdza dostępności „{product}”; sprawdza: {allowed}.",
    ),
    "none": Text(
        'Area "{area}" has no report of the availability of "{product}" by {producer}.',
        "Obszar „{area}” nie ma raportu dostępności „{product}” od {producer}.",
    ),
}
