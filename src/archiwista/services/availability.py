"""The availability at the source for every interface (plan of 2026-10-25, A2).

``check`` answers a request for what the source has for an area and a
product: the report the index keeps for them while it is younger than
``REPORT_TTL`` and the request does not ``force`` a new question, else the
``availability`` job that asks the source (a new one, or an active one that
asks the same question; ADR-035). ``stored`` returns the last report without
the network. ``POST /availability``, ``GET /availability`` and ``archiwista
availability`` call them.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from archiwista.auth import Principal
from archiwista.errors import NotFoundError, UnsupportedError
from archiwista.index import AreaRecord, IndexQueries, StoredAvailability
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import message
from archiwista.services.commands import actions
from archiwista.sources.registry import PluginRegistry

# How long a kept report answers for the source: Kartograf's metadata cache
# keeps an answer of the source as long (SPEC 6.3), so a check within it
# would mostly read the same answers again.
REPORT_TTL = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class AreaAvailability:
    """The last report of an area and a product, with the area it is about."""

    area: AreaRecord
    stored: StoredAvailability


def check(
    queries: IndexQueries,
    registry: PluginRegistry,
    jobs: JobSupervisor,
    *,
    area_id: str,
    product: str,
    producer: str,
    force: bool,
    actor: Principal,
) -> AreaAvailability | JobRecord:
    """Return the area's fresh report of a product, else the job that asks the source.

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index: the area and its reports.
    registry : PluginRegistry
        Producer plugins: the products the producer checks.
    jobs : JobSupervisor
        Started supervisor of the ``availability`` job.
    area_id : str
        An area the index keeps (``POST /areas``).
    product : str
        A product of the producer's ``availability_products``.
    producer : str
        Producer id.
    force : bool
        Ask the source even when a report younger than ``REPORT_TTL`` is kept.
    actor : Principal
        Who asks: the job's actor.

    Returns
    -------
    AreaAvailability or JobRecord
        The kept report when it is fresh and ``force`` is off; else the job,
        queued or running (also one of another request that it joined).

    Raises
    ------
    NotFoundError
        The index keeps no area ``area_id``.
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available.
    UnsupportedError
        The producer offers no commands (reason ``no_commands``), or checks
        no availability of ``product`` (``no_availability``,
        ``details.allowed``).
    OfflineModeError
        A job is needed and offline mode is on; nothing is recorded.
    """
    record = _area(queries, area_id)
    products = actions(registry, producer).availability_products()
    if product not in products:
        raise UnsupportedError(
            message(
                "availability.product_unsupported",
                producer=producer,
                product=product,
                allowed=", ".join(products),
            ),
            reason="no_availability",
            details={"allowed": list(products)},
        )
    if not force:
        found = queries.availability(area_id, product, producer=producer)
        if found is not None and datetime.now(UTC) - found.checked_at < REPORT_TTL:
            return AreaAvailability(record, found)
    params = {
        "area_id": area_id,
        "producer": producer,
        "product": product,
        "force": force,
    }
    return jobs.submit("availability", params=params, actor=actor)


def stored(
    queries: IndexQueries, *, area_id: str, product: str, producer: str
) -> AreaAvailability:
    """Return the last report of an area and a product, without the network.

    Raises
    ------
    NotFoundError
        The index keeps no area ``area_id``, or no report of its ``product``
        by ``producer``.
    """
    record = _area(queries, area_id)
    found = queries.availability(area_id, product, producer=producer)
    if found is None:
        raise NotFoundError(
            message(
                "availability.none", area=area_id, product=product, producer=producer
            )
        )
    return AreaAvailability(record, found)


def _area(queries: IndexQueries, area_id: str) -> AreaRecord:
    """Return a kept area or refuse with ``NotFoundError``."""
    record = queries.area(area_id)
    if record is None:
        raise NotFoundError(message("api.area_unknown", area=area_id))
    return record
