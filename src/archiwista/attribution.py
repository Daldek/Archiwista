"""The lines the data providers' terms require with every product (A-ADR-055).

Nogat's standard (DEV §20, ECO-060) lists them: the source of IMGW-PIB's data
(S) and, once they were processed in any way, the mark of processing (P), with
the hydrological service named for station positions taken from it (H);
PMAXTP's source, mark and monograph (PS, PP, M); ČHMÚ's credit with its licence
(C) and what was done (CP); and the IMGW-PIB terms of use (N) followed by the
terms that apply (RD, RH, RK). A product names the origins of its data and
``of`` gives their lines in the standard's order, each once: ``attribution``
(DEV-20.4) and ``terms_notice`` (DEV-20.7). The texts are the ``legal`` area
of the catalog (``archiwista.messages.legal``), the one place that holds them.

Archiwista shows a stored file as it is (a file of IMGW-PIB as published
carries S alone) and processes everything else: Obserwator's series and
station catalogs are processed forms, and Archiwista's labels, tables, charts,
annual extremes and hand-offs process them further.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from archiwista.errors import SourceStateError
from archiwista.messages import message
from archiwista.sources import DataOrigin, DataOriginAdapter
from archiwista.sources.registry import PluginRegistry

# A product's origin: a version's (``DataOrigin``), or ČHMÚ data in
# Archiwista's own tables and charts of stations.
type Origin = DataOrigin | Literal["chmi_views"]

# The keys of the attribution lines in the order of DEV-20.4, and of the
# terms notice in the order of DEV-20.7.
_ATTRIBUTION = (
    "legal.imgw_source",
    "legal.imgw_processed",
    "legal.imgw_hydro",
    "legal.pmaxtp_source",
    "legal.pmaxtp_processed",
    "legal.pmaxtp_monograph",
    "legal.chmi_source",
    "legal.chmi_processed",
    "legal.chmi_processed_views",
)
_TERMS = (
    "legal.imgw_terms",
    "legal.imgw_terms_public_data",
    "legal.imgw_terms_hydro",
    "legal.imgw_terms_pmaxtp",
)
# The lines of each origin, attribution and terms together.
_LINES: dict[Origin, tuple[str, ...]] = {
    "imgw_file": (
        "legal.imgw_source",
        "legal.imgw_terms",
        "legal.imgw_terms_public_data",
    ),
    "imgw_processed": (
        "legal.imgw_source",
        "legal.imgw_processed",
        "legal.imgw_terms",
        "legal.imgw_terms_public_data",
    ),
    "imgw_stations": (
        "legal.imgw_source",
        "legal.imgw_processed",
        "legal.imgw_hydro",
        "legal.imgw_terms",
        "legal.imgw_terms_public_data",
        "legal.imgw_terms_hydro",
    ),
    "pmaxtp": (
        "legal.pmaxtp_source",
        "legal.pmaxtp_processed",
        "legal.pmaxtp_monograph",
        "legal.imgw_terms",
        "legal.imgw_terms_pmaxtp",
    ),
    "chmi_file": ("legal.chmi_source",),
    "chmi_processed": ("legal.chmi_source", "legal.chmi_processed"),
    "chmi_views": ("legal.chmi_source", "legal.chmi_processed_views"),
}
# The station providers of Obserwator's catalogs, as the index names them.
_IMGW = "IMGW-PIB"
_CHMI = "CHMI"


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


def of(origins: Iterable[Origin | None]) -> Attribution:
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

    The lines of the standard keep its order; any other line (a sidecar's
    attribution of another provider) follows them in the order first seen.
    """
    found = list(parts)
    return Attribution(
        _ordered((line for part in found for line in part.attribution), _ATTRIBUTION),
        _ordered((line for part in found for line in part.terms_notice), _TERMS),
    )


def station_origin(provider: str, *, positions: bool) -> Origin | None:
    """Return the origin of a station's data in Archiwista's tables and charts.

    Parameters
    ----------
    provider : str
        The station's provider: ``IMGW-PIB`` or ``CHMI``.
    positions : bool
        Whether the product shows or returns station positions, which the
        IMGW-PIB catalog takes from the hydrological service (H).
    """
    if provider == _IMGW:
        return "imgw_stations" if positions else "imgw_processed"
    if provider == _CHMI:
        return "chmi_views"
    return None


def series_origin(provider: str) -> Origin | None:
    """Return the origin of a station's series values handed off as data.

    The values the producer reads, written in another format (and, for
    annual maxima, found in the half-year characteristics).
    """
    if provider == _IMGW:
        return "imgw_processed"
    if provider == _CHMI:
        return "chmi_processed"
    return None


def version(origin: DataOrigin | None, sidecar: str | None) -> Attribution:
    """Return the lines of a stored version shown or copied as it is.

    The lines of its origin; without one, the attribution its sidecar gives
    (a producer whose providers' terms Archiwista does not know).
    """
    if origin is not None:
        return of([origin])
    formula = (sidecar or "").strip()
    return Attribution((formula,) if formula else ())


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


def _ordered(lines: Iterable[str], keys: tuple[str, ...]) -> tuple[str, ...]:
    """Return the lines once each: the standard's in its order, then the rest."""
    rank = {str(message(key)): index for index, key in enumerate(keys)}
    first = len(rank)
    return tuple(sorted(dict.fromkeys(lines), key=lambda line: rank.get(line, first)))
