"""Store marker file names of the Nogat producers (DEV-19.12).

Every producer's store root holds a marker ``<tool>-store.json`` (schema
``<tool>-store/1``). A tool judges another tool's store by this file name
alone and imports nothing from it (DEV-19.12, DEV-19.14): so do Archiwista's
adapters when they refuse a foreign directory, and the settings when they
refuse a store nested in another one. The list is the one of Nogat's
DEV §19.
"""

from collections.abc import Mapping
from types import MappingProxyType

STORE_MARKERS: Mapping[str, str] = MappingProxyType(
    {
        "kartograf": "kartograf-store.json",
        "imgw": "imgw-store.json",
    }
)
"""Marker file name by producer id."""


def foreign_markers(producer: str) -> tuple[str, ...]:
    """Return the marker file names of every producer but ``producer``."""
    return tuple(name for key, name in STORE_MARKERS.items() if key != producer)
