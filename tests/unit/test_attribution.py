"""The lines a product carries by the origins of its data (A-ADR-055).

Nogat's DEV §20 fixes the lines byte for byte and their order: the
attribution S, P, PS, PP, M, C, CP, G, Z (DEV-20.4), then the terms RD, RH, RK
(DEV-20.7), each line once whatever order the parts come in. A file as
published carries S alone; a version whose producer names no origin carries
its sidecar's attribution. G and Z come from a station catalog's sidecar as
the producer wrote them, recognised by their fixed text as Nogat's kit
recognises them.
"""

import json
import re
from pathlib import Path

import pytest

from archiwista import attribution
from archiwista.attribution import Attribution, Origin
from archiwista.sources import DataOrigin
from tests.fixtures.provider_lines import (
    CHMI_PROCESSED,
    CHMI_PROCESSED_VIEWS,
    CHMI_SOURCE,
    CUZK_RUIAN,
    GUGIK_PRG,
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
# G of several products, years and days, as DEV §20 joins them.
GUGIK_RANGES = (
    "Źródło: Główny Urząd Geodezji i Kartografii – GUGiK, NMT, BDOT10k (wytworzono"
    " 2020–2025, pozyskano 2026-03-24 – 2026-10-29); dane przetworzone"
)
# Nogat's kit, whose `LINES` quote DEV §20 with `<name>` for each value.
KIT_SOURCES = Path(attribution.__file__).parent / "web" / "nogat" / "nogat-sources.js"


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
        (
            "chmi_processed",
            f"{CHMI_SOURCE}. {CHMI_PROCESSED}. {CUZK_RUIAN}",
            Attribution((CHMI_SOURCE, CHMI_PROCESSED, CUZK_RUIAN)),
        ),
        (None, f"  {GUGIK} ", Attribution((GUGIK,))),
        (None, " ", Attribution()),
        (None, None, Attribution()),
    ],
)
def test_attribution_version_takes_the_origins_lines_else_the_sidecars(
    origin: DataOrigin | None, sidecar: str | None, lines: Attribution
) -> None:
    """A sidecar's own text never replaces the standard's lines; its G and Z join."""
    assert attribution.version(origin, sidecar) == lines


def test_the_fixtures_g_and_z_are_the_kits_lines_with_their_values() -> None:
    """The constants the tests compare with are DEV §20's G and Z, filled."""
    # Arrange
    source = KIT_SOURCES.read_text(encoding="utf-8")
    lines = {
        mark: json.loads(found)
        for mark, found in re.findall(r'^  (G|Z): ("[^"\n]*"),$', source, re.M)
    }

    # Act
    gugik = (
        lines["G"]
        .replace("`<products>`", "PRG")
        .replace("`<period>`", "2025")
        .replace("`<date>`", "2026-11-10")
    )
    cuzk = lines["Z"].replace("`<products>`", "RÚIAN").replace("`<date>`", "2026-11-12")

    # Assert
    assert (gugik, cuzk) == (GUGIK_PRG, CUZK_RUIAN)


def test_attribution_filled_finds_g_and_z_whatever_their_values() -> None:
    """Each once, as written, G before Z; the provider's own lines stay out."""
    # Arrange
    text = ". ".join(
        [
            CHMI_SOURCE,
            CUZK_RUIAN,
            IMGW_SOURCE,
            GUGIK_RANGES,
            GUGIK_PRG,
            CUZK_RUIAN,
            GUGIK_PRG.replace("dane przetworzone", "dane"),
        ]
    )

    # Act
    found = attribution.filled(text)

    # Assert
    assert found == Attribution((GUGIK_RANGES, GUGIK_PRG, CUZK_RUIAN))
    assert attribution.filled(". ".join([IMGW_SOURCE, IMGW_PROCESSED])) == Attribution()
    assert attribution.filled(None) == Attribution()


@pytest.mark.parametrize(
    ("provider", "catalog", "positions", "lines"),
    [
        pytest.param(
            "IMGW-PIB",
            f"{IMGW_SOURCE}. {GUGIK_PRG}",
            True,
            Attribution(
                (IMGW_SOURCE, IMGW_PROCESSED, GUGIK_PRG),
                (*PUBLIC_DATA_TERMS, IMGW_TERMS_HYDRO),
            ),
            id="imgw-located",
        ),
        pytest.param(
            "IMGW-PIB",
            f"{IMGW_SOURCE}. {GUGIK_PRG}",
            False,
            Attribution((IMGW_SOURCE, IMGW_PROCESSED, GUGIK_PRG), PUBLIC_DATA_TERMS),
            id="imgw-reason",
        ),
        pytest.param(
            "CHMI",
            f"{CHMI_SOURCE}. {CHMI_PROCESSED}. {CUZK_RUIAN}",
            True,
            Attribution((CHMI_SOURCE, CHMI_PROCESSED_VIEWS, CUZK_RUIAN)),
            id="chmi",
        ),
        pytest.param(
            "IMGW-PIB",
            IMGW_SOURCE,
            True,
            Attribution(
                (IMGW_SOURCE, IMGW_PROCESSED), (*PUBLIC_DATA_TERMS, IMGW_TERMS_HYDRO)
            ),
            id="catalog-without-borders",
        ),
    ],
)
def test_attribution_station_adds_its_catalogs_g_and_z(
    provider: str, catalog: str, positions: bool, lines: Attribution
) -> None:
    """A place, a position or the reason it has none, carries its catalog's lines."""
    assert attribution.station(provider, catalog, positions=positions) == lines


def test_attribution_merge_puts_g_and_z_after_the_fixed_lines() -> None:
    """S, P, C, CP, then G, then Z, then another provider's line, each once."""
    # Act
    merged = attribution.merge(
        [
            Attribution((CUZK_RUIAN,)),
            Attribution((GUGIK,)),
            Attribution((CHMI_SOURCE, CHMI_PROCESSED_VIEWS, CUZK_RUIAN)),
            Attribution((GUGIK_PRG,)),
            Attribution((IMGW_SOURCE, IMGW_PROCESSED, GUGIK_PRG), PUBLIC_DATA_TERMS),
        ]
    )

    # Assert
    assert merged == Attribution(
        (
            IMGW_SOURCE,
            IMGW_PROCESSED,
            CHMI_SOURCE,
            CHMI_PROCESSED_VIEWS,
            GUGIK_PRG,
            CUZK_RUIAN,
            GUGIK,
        ),
        PUBLIC_DATA_TERMS,
    )
