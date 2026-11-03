"""Local coverage of an area."""

from archiwista.messages import Text

MESSAGES = {
    "coverage_percent": Text(
        "locally {percent}% of the area",
        "lokalnie {percent}% obszaru",
    ),
    "coverage_below_one": Text(
        "locally <1% of the area",
        "lokalnie <1% obszaru",
    ),
    "coverage_no_planar_crs": Text(
        "locally no percentage: country without a planar CRS",
        "lokalnie bez procentu: kraj bez układu płaskiego",
    ),
    "coverage_empty_area": Text(
        "locally no percentage: area without a surface",
        "lokalnie bez procentu: obszar bez powierzchni",
    ),
}
