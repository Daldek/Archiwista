"""Survey control points: coordinates measured, never computed by PROJ.

A control point checks that what Archiwista draws is where it is on the
ground (decision 4 of the v0.2 plan, SPEC 13 v0.2 criterion 2). Its
reference coordinates come from the survey authority, so the transformation
under test never computes the values it is compared with. Distances are
measured with ``pyproj.Geod`` on the WGS84 ellipsoid, WGS84 taken as ETRS89:
the two differ by about 0.9 m in 2026, within the 2 m tolerance.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ControlPoint:
    """A survey control point with its S-JTSK and ETRS89 coordinates.

    Parameters
    ----------
    number : str
        Number of the point on its trigonometric list (``ZTLTL``).
    cadastral_area : str
        Cadastral area (katastrální území) of the point.
    sjtsk_y, sjtsk_x : float
        S-JTSK ``Y`` and ``X`` in metres, as published (positive).
    lat, lon : float
        ETRS89 latitude and longitude in degrees.
    method : str
        How the ETRS89 coordinates were determined.
    service : str
        The map service that published the point.
    layer : str
        The service layer holding the point.
    object_id : int
        ``OBJECTID`` of the point in the layer.
    recorded : str
        Date of the recorded answer (ISO 8601).
    recording : str
        Where the recorded answer is kept.
    """

    number: str
    cadastral_area: str
    sjtsk_y: float
    sjtsk_x: float
    lat: float
    lon: float
    method: str
    service: str
    layer: str
    object_id: int
    recorded: str
    recording: str

    @property
    def epsg5514(self) -> tuple[float, float]:
        """``(x, y)`` in EPSG:5514 (Krovak East North): S-JTSK ``(-Y, -X)``."""
        return (-self.sjtsk_y, -self.sjtsk_x)

    @property
    def etrs89(self) -> tuple[float, float]:
        """``(lon, lat)`` in ETRS89, x (east) first like coordinate operations."""
        return (self.lon, self.lat)


# Trigonometric point 3722 on the Polish-Czech border (Český Těšín).
POINT_3722 = ControlPoint(
    number="3722",
    cadastral_area="Mosty u Českého Těšína",
    sjtsk_y=449_334.63,
    sjtsk_x=1_111_919.25,
    lat=49.7587324167,
    lon=18.58895625,
    method="GNSS, static",
    service="https://ags.cuzk.gov.cz/arcgis/rest/services/BodovaPole/MapServer",
    layer="2 (Bod ZPBP určený v ETRS89)",
    object_id=2096,
    recorded="2026-10-16",
    recording=(
        "Kartograf: tests/fixtures/cz/survey_control/real_2026_10_16/"
        "layer_2_tesin_r1000_o0.json"
    ),
)
