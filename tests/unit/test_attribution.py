"""The lines a product carries by the origins of its data (A-ADR-055).

Nogat's DEV §20 fixes the lines byte for byte and their order: the
attribution S, P, PS, PP, M, C, CP (DEV-20.4), then the terms RD, RH, RK
(DEV-20.7), each line once whatever order the parts come in. A file as
published carries S alone; a version whose producer names no origin carries
its sidecar's attribution.
"""

import pytest

from archiwista import attribution
from archiwista.attribution import Attribution, Origin
from archiwista.sources import DataOrigin
from tests.fixtures.provider_lines import (
    CHMI_PROCESSED,
    CHMI_PROCESSED_VIEWS,
    CHMI_SOURCE,
    IMGW_PROCESSED,
    IMGW_SOURCE,
    IMGW_TERMS_HYDRO,
    IMGW_TERMS_PMAXTP,
    IMGW_TERMS_PUBLIC_DATA,
    PMAXTP_MONOGRAPH,
    PMAXTP_PROCESSED,
    PMAXTP_SOURCE,
)

GUGIK = "Główny Urząd Geodezji i Kartografii"
PUBLIC_DATA_TERMS = (IMGW_TERMS_PUBLIC_DATA,)


@pytest.mark.parametrize(
    ("origin", "lines"),
    [
        ("imgw_file", Attribution((IMGW_SOURCE,), PUBLIC_DATA_TERMS)),
        (
            "imgw_processed",
            Attribution((IMGW_SOURCE, IMGW_PROCESSED), PUBLIC_DATA_TERMS),
        ),
        (
            "imgw_stations",
            Attribution(
                (IMGW_SOURCE, IMGW_PROCESSED),
                (*PUBLIC_DATA_TERMS, IMGW_TERMS_HYDRO),
            ),
        ),
        (
            "pmaxtp",
            Attribution(
                (PMAXTP_SOURCE, PMAXTP_PROCESSED, PMAXTP_MONOGRAPH),
                (IMGW_TERMS_PMAXTP,),
            ),
        ),
        ("chmi_file", Attribution((CHMI_SOURCE,))),
        ("chmi_processed", Attribution((CHMI_SOURCE, CHMI_PROCESSED))),
        ("chmi_views", Attribution((CHMI_SOURCE, CHMI_PROCESSED_VIEWS))),
    ],
)
def test_attribution_of_one_origin_gives_the_lines_its_terms_require(
    origin: Origin, lines: Attribution
) -> None:
    """S alone for a file as published; PS, PP and M for PMAXTP; no terms for ČHMÚ."""
    assert attribution.of([origin]) == lines


def test_attribution_of_many_origins_gives_each_line_once_in_order() -> None:
    """Origins repeated and in any order, one unknown: DEV-20.4, then DEV-20.7."""
    # Act
    lines = attribution.of(
        [
            "chmi_views",
            "pmaxtp",
            None,
            "chmi_processed",
            "imgw_stations",
            "imgw_file",
            "chmi_file",
            "imgw_processed",
            "pmaxtp",
        ]
    )

    # Assert
    assert lines.attribution == (
        IMGW_SOURCE,
        IMGW_PROCESSED,
        PMAXTP_SOURCE,
        PMAXTP_PROCESSED,
        PMAXTP_MONOGRAPH,
        CHMI_SOURCE,
        CHMI_PROCESSED,
        CHMI_PROCESSED_VIEWS,
    )
    assert lines.terms_notice == (
        IMGW_TERMS_PUBLIC_DATA,
        IMGW_TERMS_HYDRO,
        IMGW_TERMS_PMAXTP,
    )


def test_attribution_merge_puts_a_sidecars_line_after_the_standards() -> None:
    """Each line once; another provider's line follows the standard's lines."""
    # Act
    merged = attribution.merge(
        [
            Attribution((GUGIK,)),
            Attribution((CHMI_SOURCE, CHMI_PROCESSED)),
            Attribution((IMGW_SOURCE,), PUBLIC_DATA_TERMS),
            Attribution((IMGW_SOURCE, IMGW_PROCESSED), PUBLIC_DATA_TERMS),
            Attribution((GUGIK,)),
        ]
    )

    # Assert
    assert merged == Attribution(
        (IMGW_SOURCE, IMGW_PROCESSED, CHMI_SOURCE, CHMI_PROCESSED, GUGIK),
        PUBLIC_DATA_TERMS,
    )


@pytest.mark.parametrize(
    ("origin", "sidecar", "lines"),
    [
        (
            "imgw_processed",
            "Źródłem pochodzenia danych jest IMGW-PIB.",
            Attribution((IMGW_SOURCE, IMGW_PROCESSED), PUBLIC_DATA_TERMS),
        ),
        (None, f"  {GUGIK} ", Attribution((GUGIK,))),
        (None, " ", Attribution()),
        (None, None, Attribution()),
    ],
)
def test_attribution_version_takes_the_origins_lines_else_the_sidecars(
    origin: DataOrigin | None, sidecar: str | None, lines: Attribution
) -> None:
    """A sidecar's own text never replaces the standard's lines of a known origin."""
    assert attribution.version(origin, sidecar) == lines
