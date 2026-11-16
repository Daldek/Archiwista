"""The texts of the coverage labels and store badges (SPEC 6.4, Polish plurals)."""

import pytest

from archiwista.api.models_availability import (
    StoreBadgeItem,
    coverage_text,
    other_variants_text,
)
from archiwista.messages import Lang, language, plural_form
from archiwista.services.availability import (
    NO_DATA,
    CoverageKind,
    CoverageLabel,
    StoreBadge,
)


def _label(
    kind: CoverageKind,
    *,
    campaigns: int = 1,
    percent: int | None = None,
    below_one: bool = False,
    partial_sheets: int = 0,
    missing_sheets: int = 0,
) -> CoverageLabel:
    """Return a label; the share follows the percent."""
    return CoverageLabel(
        kind=kind,
        campaigns=campaigns,
        share=None if percent is None else percent / 100,
        percent=percent,
        below_one=below_one,
        partial_sheets=partial_sheets,
        missing_sheets=missing_sheets,
    )


@pytest.mark.parametrize(
    ("count", "form"),
    [
        (0, "many"),
        (1, "one"),
        (2, "few"),
        (4, "few"),
        (5, "many"),
        (11, "many"),
        (12, "many"),
        (14, "many"),
        (21, "many"),
        (22, "few"),
        (24, "few"),
        (25, "many"),
        (102, "few"),
        (112, "many"),
    ],
)
def test_plural_form_follows_the_polish_rule(count: int, form: str) -> None:
    """1 kampania, 2-4 kampanie, 5+ kampanii; 12-14 many, 22-24 few again."""
    assert plural_form(count) == form


@pytest.mark.parametrize(
    ("label", "polish", "english"),
    [
        (_label("full", percent=100), "pełne", "complete"),
        (
            _label("full_campaigns", campaigns=2, percent=100),
            "pełne · 2 kampanie",
            "complete · 2 campaigns",
        ),
        (
            _label("full_campaigns", campaigns=5, percent=100),
            "pełne · 5 kampanii",
            "complete · 5 campaigns",
        ),
        (
            _label("full_campaigns", campaigns=22, percent=100),
            "pełne · 22 kampanie",
            "complete · 22 campaigns",
        ),
        (
            _label("partial", percent=58, partial_sheets=1),
            "częściowe · 58% · 1 ark. niepełny",
            "partial · 58% · 1 partial sheet",
        ),
        (
            _label("partial", percent=99, partial_sheets=2),
            "częściowe · 99% · 2 ark. niepełne",
            "partial · 99% · 2 partial sheets",
        ),
        (
            _label("partial", percent=0, below_one=True, partial_sheets=5),
            "częściowe · <1% · 5 ark. niepełnych",
            "partial · <1% · 5 partial sheets",
        ),
        (
            _label("partial", campaigns=0, percent=75, missing_sheets=2),
            "częściowe · 75% · 2 ark. bez pliku",
            "partial · 75% · 2 sheets without a file",
        ),
        (_label("partial"), "częściowe", "partial"),
        (NO_DATA, "brak danych", "no data"),
    ],
)
def test_coverage_text_writes_the_labels_of_spec_6_4(
    label: CoverageLabel, polish: str, english: str
) -> None:
    """Each kind with its counted words, in Polish and in English."""
    texts: dict[Lang, str] = {}
    langs: tuple[Lang, ...] = ("pl", "en")
    for lang in langs:
        with language(lang):
            texts[lang] = coverage_text(label)

    assert texts == {"pl": polish, "en": english}


@pytest.mark.parametrize(
    ("lang", "badges", "chips"),
    [
        (
            "pl",
            ["pobrane", "pobrane 5/12", "niepobrane"],
            ["+1 wariant", "+2 warianty", "+5 wariantów"],
        ),
        (
            "en",
            ["downloaded", "downloaded 5/12", "not downloaded"],
            ["+1 variant", "+2 variants", "+5 variants"],
        ),
    ],
)
def test_store_badge_and_variant_chip_texts(
    lang: Lang, badges: list[str], chips: list[str]
) -> None:
    """All units, some of them, none; and the chip of the other variants."""
    with language(lang):
        found = [
            StoreBadgeItem.of_badge(StoreBadge("zespol", units, 12)).label
            for units in (12, 5, 0)
        ]
        counted = [other_variants_text(count) for count in (1, 2, 5)]

    assert found == badges
    assert counted == chips
