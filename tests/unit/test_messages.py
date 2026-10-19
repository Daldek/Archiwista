"""A Polish message with the detail of a library or the system (``with_detail``)."""

import pytest

from archiwista.api.errors import service_problem
from archiwista.errors import PreviewUnavailableError
from archiwista.messages import MESSAGES, with_detail


@pytest.mark.parametrize(
    ("message", "detail", "expected"),
    [
        (
            "Nie można odczytać magazynu /dane",
            "brak dostępu",
            "Nie można odczytać magazynu /dane: brak dostępu",
        ),
        # A whole sentence stays one: its full stop moves after the detail.
        (
            "Nie można odczytać pliku.",
            "not a TIFF file",
            "Nie można odczytać pliku: not a TIFF file.",
        ),
        # A detail ending its own sentence gets no second full stop.
        (
            "Nie można odczytać pliku.",
            "TIFFReadDirectory failed.",
            "Nie można odczytać pliku: TIFFReadDirectory failed.",
        ),
        ("Nie można odczytać pliku.", None, "Nie można odczytać pliku."),
        ("Nie można odczytać pliku.", "", "Nie można odczytać pliku."),
    ],
)
def test_with_detail_never_puts_colon_after_full_stop(
    message: str, detail: str | None, expected: str
) -> None:
    """The detail follows a colon, never ``….: …``."""
    assert with_detail(message, detail) == expected


def test_preview_problem_detail_explains_reason_before_fix() -> None:
    """A file without a preview: reason, the library's detail, then the fix."""
    problem = service_problem(PreviewUnavailableError("unreadable", "not a TIFF file"))

    assert problem is not None
    reason = MESSAGES["preview_reason_unreadable"].removesuffix(".")
    assert problem["detail"] == (
        f"{reason}: not a TIFF file. {MESSAGES['preview_fix_unreadable']}"
    )
