"""The lines the data providers' terms require with every product (A-ADR-055).

Nogat's standard (DEV §20, ECO-060, ECO-065) lists them: the source of
IMGW-PIB's data (S) and, once they were processed in any way, the mark of
processing (P); PMAXTP's source, mark and monograph (PS, PP, M); ČHMÚ's credit
with its licence (C) and the mark of processing (CP), which never says how
(ECO-071); GUGiK's (G) and ČÚZK's (Z) with the products and days of their
data; and the links to the IMGW-PIB terms that
apply (RD, RH for station positions of the hydrological service, RK), never a
summary of them. A product names the origins of its data and ``of`` gives
their lines in the standard's order, each once: ``attribution`` (DEV-20.4) and
``terms_notice`` (DEV-20.7). The texts are the ``legal`` area of the catalog
(``archiwista.messages.legal``), the one place that holds them.

G and Z are the station catalog's own (DEV-20.9, DEV-20.11): Obserwator checks
every position of its catalogs against the state borders it packages, PRG of
GUGiK and RÚIAN of ČÚZK, and names them in the attribution of the catalog's
sidecar with the products and days of those files. ``catalog`` finds each by
its fixed text and carries it as written, so a product that gives a station's
place, a position or the reason it has none, carries the lines of the catalog
it comes from (``station``), and a version whose sidecar names them carries
them too (``version``); Archiwista never writes a product or a day itself.

Archiwista shows a stored file as it is (a file of IMGW-PIB as published
carries S alone) and processes everything else: Obserwator's series and
station catalogs are processed forms, and Archiwista's labels, tables, charts,
annual extremes and hand-offs process them further.

A line of an older product „Dane ČHMÚ zostały przetworzone (…)”, whatever its
words in parentheses, is CP (DEV-20.4): ``merge`` and ``version`` carry the
canonical line instead, once.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

from archiwista.errors import SourceStateError
from archiwista.messages import message
from archiwista.sources import DataOrigin, DataOriginAdapter
from archiwista.sources.registry import PluginRegistry

# The keys of the attribution lines in the order of DEV-20.4, and of the
# terms notice in the order of DEV-20.7. G and Z, whose values a producer
# fills (``_filled``), follow the fixed lines in that order.
_ATTRIBUTION = (
    "legal.imgw_source",
    "legal.imgw_processed",
    "legal.pmaxtp_source",
    "legal.pmaxtp_processed",
    "legal.pmaxtp_monograph",
    "legal.chmu_source",
    "legal.chmu_processed",
)
_TERMS = (
    "legal.imgw_terms_public_data",
    "legal.imgw_terms_hydro",
    "legal.imgw_terms_pmaxtp",
)
# The lines of each origin, attribution and terms together.
_LINES: dict[DataOrigin, tuple[str, ...]] = {
    "imgw_file": (
        "legal.imgw_source",
        "legal.imgw_terms_public_data",
    ),
    "imgw_processed": (
        "legal.imgw_source",
        "legal.imgw_processed",
        "legal.imgw_terms_public_data",
    ),
    "imgw_stations": (
        "legal.imgw_source",
        "legal.imgw_processed",
        "legal.imgw_terms_public_data",
        "legal.imgw_terms_hydro",
    ),
    "pmaxtp": (
        "legal.pmaxtp_source",
        "legal.pmaxtp_processed",
        "legal.pmaxtp_monograph",
        "legal.imgw_terms_pmaxtp",
    ),
    "chmu_file": ("legal.chmu_source",),
    "chmu_processed": ("legal.chmu_source", "legal.chmu_processed"),
}
# The station providers of Obserwator's catalogs, as the index names them.
_IMGW = "IMGW-PIB"
_CHMU = "CHMU"
# A value of G and Z while their patterns are built; no line holds it.
_HOLE = "\x00"
# What a value of G and Z may hold: products, a year or two, a day or two.
_VALUE = r"[^()]+?"


@cache
def _filled() -> tuple[re.Pattern[str], ...]:
    """Return the patterns of G and Z, in the order of DEV-20.4.

    Each is the line's fixed text around any values, as Nogat's kit
    recognises the lines (``nogat-sources.js``).
    """
    templates = (
        message("legal.gugik_source", products=_HOLE, period=_HOLE, date=_HOLE),
        message("legal.cuzk_source", products=_HOLE, date=_HOLE),
    )
    return tuple(
        re.compile(_VALUE.join(re.escape(part) for part in str(text).split(_HOLE)))
        for text in templates
    )


@dataclass(frozen=True, slots=True)
class Attribution:
    """The lines a product carries: ``attribution``, then ``terms_notice``.

    Both are empty for a product without data of a provider whose terms are
    known (and without a sidecar's attribution).
    """

    attribution: tuple[str, ...] = ()
    terms_notice: tuple[str, ...] = ()

    def lines(self) -> tuple[str, ...]:
        """Return every line in the order a product shows them."""
        return self.attribution + self.terms_notice

    def fields(self) -> dict[str, Any]:
        """Return the ``attribution`` and ``terms_notice`` fields of an answer."""
        return {
            "attribution": list(self.attribution),
            "terms_notice": list(self.terms_notice),
        }


def of(origins: Iterable[DataOrigin | None]) -> Attribution:
    """Return the lines of a product made of data of these origins.

    ``None`` (data no provider's terms are known for) adds nothing.
    """
    keys = {key for origin in origins if origin is not None for key in _LINES[origin]}
    return Attribution(
        tuple(str(message(key)) for key in _ATTRIBUTION if key in keys),
        tuple(str(message(key)) for key in _TERMS if key in keys),
    )


def merge(parts: Iterable[Attribution]) -> Attribution:
    """Return the lines of a product made of several: each line once, in order.

    The lines of the standard keep its order, G and Z after the fixed ones;
    any other line (a sidecar's attribution of another provider) follows them
    in the order first seen. An older CP is the canonical one.
    """
    found = list(parts)
    return Attribution(
        _ordered(
            (line for part in found for line in part.attribution),
            _ATTRIBUTION,
            _filled(),
        ),
        _ordered((line for part in found for line in part.terms_notice), _TERMS),
    )


def filled(text: str | None) -> Attribution:
    """Return the G and Z lines a producer's attribution holds, each once.

    ``text`` is the attribution of a version's sidecar (``license.attribution``),
    where Obserwator joins the lines of its station catalog: each G and Z is
    found by its fixed text and kept as written, with the producer's products
    and days. Any other text stays out; the version's origin gives its lines.
    """
    found = (
        match.group(0)
        for pattern in _filled()
        for match in pattern.finditer(text or "")
    )
    return Attribution(_ordered(found, (), _filled()))


def station(provider: str, catalog: str | None, *, positions: bool) -> Attribution:
    """Return the lines of a product that gives a station with its place.

    The lines of the station's data (``station_origin``) and the G and Z of
    the catalog it comes from: the catalog's place of a station, a position or
    the reason it has none, is checked against the state borders those lines
    credit.

    Parameters
    ----------
    provider : str
        The station's provider: ``IMGW-PIB`` or ``CHMU``.
    catalog : str or None
        The attribution of the sidecar of the catalog version the station
        was read from; ``None`` without one.
    positions : bool
        Whether the product shows or returns the station's position.
    """
    return merge([of([station_origin(provider, positions=positions)]), filled(catalog)])


def station_origin(provider: str, *, positions: bool) -> DataOrigin | None:
    """Return the origin of a station's data in Archiwista's tables and charts.

    Parameters
    ----------
    provider : str
        The station's provider: ``IMGW-PIB`` or ``CHMU``.
    positions : bool
        Whether the product shows or returns station positions, which the
        IMGW-PIB catalog takes from the hydrological service (H).
    """
    if provider == _IMGW:
        return "imgw_stations" if positions else "imgw_processed"
    if provider == _CHMU:
        return "chmu_processed"
    return None


def series_origin(provider: str) -> DataOrigin | None:
    """Return the origin of a station's series values handed off as data.

    The values the producer reads, written in another format (and, for
    annual maxima, found in the half-year characteristics).
    """
    if provider == _IMGW:
        return "imgw_processed"
    if provider == _CHMU:
        return "chmu_processed"
    return None


def version(origin: DataOrigin | None, sidecar: str | None) -> Attribution:
    """Return the lines of a stored version shown or copied as it is.

    The lines of its origin with the G and Z its sidecar names (a station
    catalog's); without an origin, the attribution its sidecar gives (a
    producer whose providers' terms Archiwista does not know), an older CP
    as the canonical one.
    """
    if origin is not None:
        return merge([of([origin]), filled(sidecar)])
    formula = (sidecar or "").strip()
    return Attribution((_canonical(formula),) if formula else ())


def text(attribution: Sequence[str], terms_notice: Sequence[str]) -> list[str]:
    """Return an answer's lines for a person on the command line.

    A title, then every line as it is (Polish in either language); nothing
    when the answer has none.
    """
    lines = [*attribution, *terms_notice]
    if not lines:
        return []
    return [str(message("cli.provider_lines")), *(f"  {line}" for line in lines)]


class Origins:
    """The origin of versions' data, by each producer's ``DataOriginAdapter``."""

    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry
        self._adapters: dict[str, DataOriginAdapter | None] = {}

    def of(self, producer: str, path: str, segment: str | None) -> DataOrigin | None:
        """Return the origin of a version, ``None`` when its producer names none.

        A producer that is not available names none.
        """
        if producer not in self._adapters:
            try:
                found = self._registry.adapter(producer)
            except SourceStateError:
                found = None
            self._adapters[producer] = (
                found if isinstance(found, DataOriginAdapter) else None
            )
        adapter = self._adapters[producer]
        return None if adapter is None else adapter.data_origin(path, segment)


def _canonical(line: str) -> str:
    """Return the line, or CP for a ČHMÚ processing line of an older product.

    The older line is CP with words in parentheses after it, which named what
    was done (before Nogat ECO-071).
    """
    canonical = str(message("legal.chmu_processed"))
    if line.startswith(f"{canonical} (") and line.endswith(")") and "\n" not in line:
        return canonical
    return line


def _ordered(
    lines: Iterable[str],
    keys: tuple[str, ...],
    patterns: tuple[re.Pattern[str], ...] = (),
) -> tuple[str, ...]:
    """Return the lines once each: the standard's in its order, then the rest.

    An older CP counts as the canonical one. The lines of ``keys`` come first,
    then those ``patterns`` match in the patterns' order, then any other line
    in the order first seen.
    """
    rank = {str(message(key)): index for index, key in enumerate(keys)}

    def place(line: str) -> int:
        if line in rank:
            return rank[line]
        matched = (
            index for index, pattern in enumerate(patterns) if pattern.fullmatch(line)
        )
        return len(rank) + next(matched, len(patterns))

    return tuple(sorted(dict.fromkeys(map(_canonical, lines)), key=place))
