"""Legends of the preview styles (plan v0.2, step 5a3; ``PreviewInfo.legend``).

``legend(probe, style)`` describes what the colours of a preview mean,
from the file's probe alone (``info.json``), so the server builds it
without opening the file:

- ``gradient`` for a colour ramp over values (``hypsometry``,
  ``elevation``): the range shown — ``rescale`` when asked for, else the
  2nd and 98th percentile of the first band — with the values' unit
  (``probe.unit``) and the ramp's colours from the lowest value up;
- ``classes`` for class rasters (``classes``): every value of the palette
  (``probe.palette``: the values the probe found in the file) with its
  colour and Polish name (``probe.class_table``: CORINE, HSG; without a
  table the value itself);
- nothing for the other styles (``rgb``, ``gray``, ``hillshade``).

Only the standard library and the class tables: the server imports this.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from archiwista.previews.classes import class_entry
from archiwista.previews.types import JsonObject, PreviewProbe

type LegendKind = Literal["gradient", "classes"]

# The colour ramp of values from the lowest shown (0) to the highest (1):
# a hypsometric tint, green lowlands to brown and pale heights.
RAMP: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, (46, 125, 72)),
    (0.25, (150, 196, 107)),
    (0.5, (242, 226, 140)),
    (0.75, (196, 138, 82)),
    (1.0, (246, 241, 235)),
)
# What a style's legend shows.
LEGEND_KINDS: Mapping[str, LegendKind] = MappingProxyType(
    {"hypsometry": "gradient", "elevation": "gradient", "classes": "classes"}
)


def legend(
    probe: PreviewProbe,
    style: str,
    *,
    rescale: tuple[float, float] | None = None,
) -> JsonObject | None:
    """Return the legend of a file's preview in a style.

    Parameters
    ----------
    probe : PreviewProbe
        The file's probe.
    style : str
        The style shown.
    rescale : tuple of float or None, optional
        Range of a ramp asked for instead of the file's 2–98% (``rescale``
        of a tile request).

    Returns
    -------
    dict or None
        ``{"kind": "gradient", "min", "max", "unit", "colors"}`` or
        ``{"kind": "classes", "items": [{"value", "color", "label"}]}``
        (colours ``#rrggbb``); ``None`` for a style without a legend or a
        probe without what it needs.
    """
    kind = LEGEND_KINDS.get(style)
    if kind == "gradient":
        limits = rescale if rescale is not None else _percentiles(probe)
        if limits is None:
            return None
        low, high = limits
        return {
            "kind": "gradient",
            "min": float(low),
            "max": float(high),
            "unit": probe.unit,
            "colors": [_hex(color) for _, color in RAMP],
        }
    if kind == "classes":
        items: list[JsonObject] = []
        for entry in probe.palette:
            if entry.color[3] == 0:  # transparent: no class
                continue
            found = class_entry(probe.class_table, entry.value)
            items.append(
                {
                    "value": entry.value,
                    "color": _hex(entry.color[:3]),
                    "label": str(entry.value) if found is None else found.label,
                }
            )
        return {"kind": "classes", "items": items} if items else None
    return None


def _percentiles(probe: PreviewProbe) -> tuple[float, float] | None:
    if not probe.stats:
        return None
    first = probe.stats[0]
    return first.p2, first.p98


def _hex(color: tuple[int, ...]) -> str:
    red, green, blue = color[:3]
    return f"#{red:02x}{green:02x}{blue:02x}"
