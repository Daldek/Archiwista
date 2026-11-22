"""Names of the files handed to a person (Nogat DEV-19.21, ECO-083)."""

import pytest

from archiwista.file_names import download_name, name_slug


@pytest.mark.parametrize(
    ("text", "slug"),
    [
        ("Nowy Sącz — Q, maksima roczne", "nowy-sacz-q-maksima-roczne"),
        ("Łódź Żółć", "lodz-zolc"),
        ("NMT · 2020", "nmt-2020"),
        ("raba_2024.v2", "raba-2024-v2"),
        ("  --Raba--  ", "raba"),
        ("— · —", ""),
    ],
)
def test_a_persons_text_is_lower_case_ascii_with_one_dash_between_words(
    text: str, slug: str
) -> None:
    """As the kit's nameSlug: diacritics and ł folded, other runs one ``-``."""
    assert name_slug(text) == slug


def test_a_download_is_the_tool_the_content_and_its_qualifiers() -> None:
    """``archiwista_<content>_<qualifiers>.<extension>``; an empty part is left out."""
    assert (
        download_name("export", "raba", "raba-2024", extension="zip")
        == "archiwista_export_raba_raba-2024.zip"
    )
    assert download_name("comparison", "", "nmt-2024", extension="csv") == (
        "archiwista_comparison_nmt-2024.csv"
    )
