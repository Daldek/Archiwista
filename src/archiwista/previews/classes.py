"""Class tables of class rasters: CORINE Land Cover and HSG (plan v0.2, step 5a3).

A class raster's preview colours its values and names them in its legend
(decision 5): from the file's palette when it has one, else from the table
of its product (``TABLE_OF_PRODUCT``: CORINE, HSG). The names are Polish
(texts of the interface); the codes and colours are the producers'.

- ``clc``: CORINE Land Cover, level 3 (44 classes) with the standard
  colours of the nomenclature. The Copernicus raster stores the class's
  position in the nomenclature (``GRID_CODE`` 1–44; 48 is nodata), a raster
  made from the vector data stores the code itself (111–523): both are
  known.
- ``hsg``: hydrologic soil groups A–D as Kartograf derives them from
  SoilGrids (``soil hsg``: 1 = A … 4 = D, 0 = nodata).

Only the standard library: the server builds legends from these tables.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

type Rgb = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class ClassEntry:
    """One class of a table.

    Attributes
    ----------
    code : str
        The producer's code, e.g. ``"311"`` or ``"A"``.
    label : str
        Polish name for a legend, with the code.
    color : Rgb
        Colour when the file has no palette.
    """

    code: str
    label: str
    color: Rgb


# CORINE Land Cover level 3: code, Polish name, standard colour; in the order
# of the nomenclature (the raster's GRID_CODE is the position, from 1).
_CLC: tuple[tuple[str, str, Rgb], ...] = (
    ("111", "Zabudowa miejska zwarta", (230, 0, 77)),
    ("112", "Zabudowa miejska luźna", (255, 0, 0)),
    ("121", "Tereny przemysłowe lub handlowe", (204, 77, 242)),
    ("122", "Tereny komunikacyjne drogowe i kolejowe", (204, 0, 0)),
    ("123", "Porty", (230, 204, 204)),
    ("124", "Lotniska", (230, 204, 230)),
    ("131", "Miejsca eksploatacji odkrywkowej", (166, 0, 204)),
    ("132", "Zwałowiska i hałdy", (166, 77, 0)),
    ("133", "Budowy", (255, 77, 255)),
    ("141", "Miejskie tereny zielone", (255, 166, 255)),
    ("142", "Tereny sportowe i wypoczynkowe", (255, 230, 255)),
    ("211", "Grunty orne poza zasięgiem urządzeń nawadniających", (255, 255, 168)),
    ("212", "Grunty orne stale nawadniane", (255, 255, 0)),
    ("213", "Pola ryżowe", (230, 230, 0)),
    ("221", "Winnice", (230, 128, 0)),
    ("222", "Sady i plantacje", (242, 166, 77)),
    ("223", "Gaje oliwne", (230, 166, 0)),
    ("231", "Łąki i pastwiska", (230, 230, 77)),
    ("241", "Uprawy jednoroczne współwystępujące z uprawami trwałymi", (255, 230, 166)),
    ("242", "Złożone systemy upraw i działek", (255, 230, 77)),
    (
        "243",
        "Tereny zajęte głównie przez rolnictwo z dużym udziałem roślinności naturalnej",
        (230, 204, 77),
    ),
    ("244", "Tereny rolniczo-leśne", (242, 204, 166)),
    ("311", "Lasy liściaste", (128, 255, 0)),
    ("312", "Lasy iglaste", (0, 166, 0)),
    ("313", "Lasy mieszane", (77, 255, 0)),
    ("321", "Murawy i pastwiska naturalne", (204, 242, 77)),
    ("322", "Wrzosowiska i zakrzewienia", (166, 255, 128)),
    ("323", "Roślinność sklerofilowa", (166, 230, 77)),
    ("324", "Lasy i roślinność krzewiasta w stanie zmian", (166, 242, 0)),
    ("331", "Plaże, wydmy i piaski", (230, 230, 230)),
    ("332", "Odsłonięte skały", (204, 204, 204)),
    ("333", "Roślinność rozproszona", (204, 255, 204)),
    ("334", "Pogorzeliska", (0, 0, 0)),
    ("335", "Lodowce i wieczne śniegi", (166, 230, 204)),
    ("411", "Bagna śródlądowe", (166, 166, 255)),
    ("412", "Torfowiska", (77, 77, 255)),
    ("421", "Bagna nadmorskie", (204, 204, 255)),
    ("422", "Saliny", (230, 230, 255)),
    ("423", "Obszary pływów morskich", (166, 166, 230)),
    ("511", "Cieki", (0, 204, 242)),
    ("512", "Zbiorniki wodne", (128, 242, 230)),
    ("521", "Laguny przybrzeżne", (0, 255, 166)),
    ("522", "Estuaria", (166, 255, 230)),
    ("523", "Morza i oceany", (230, 242, 255)),
)
# Hydrologic soil groups (Kartograf ``soil hsg``): value, group, Polish name.
_HSG: tuple[tuple[int, str, str, Rgb], ...] = (
    (1, "A", "duża infiltracja, gleby piaszczyste, mały spływ", (255, 255, 178)),
    (
        2,
        "B",
        "umiarkowana infiltracja, gleby gliniaste, umiarkowany spływ",
        (254, 204, 92),
    ),
    (3, "C", "mała infiltracja, gliny ilaste, duży spływ", (253, 141, 60)),
    (4, "D", "bardzo mała infiltracja, gleby ilaste, bardzo duży spływ", (227, 26, 28)),
)


def _clc_table() -> dict[int, ClassEntry]:
    table: dict[int, ClassEntry] = {}
    for position, (code, name, color) in enumerate(_CLC, start=1):
        entry = ClassEntry(code, f"{code} {name}", color)
        table[position] = entry
        table[int(code)] = entry
    return table


def _hsg_table() -> dict[int, ClassEntry]:
    return {
        value: ClassEntry(group, f"Grupa {group}: {name}", color)
        for value, group, name, color in _HSG
    }


CLASS_TABLES: Mapping[str, Mapping[int, ClassEntry]] = MappingProxyType(
    {
        "clc": MappingProxyType(_clc_table()),
        "hsg": MappingProxyType(_hsg_table()),
    }
)
# The class table of a product (``SourceSegment.product``): a raster of the
# product is a class raster even without a palette (decision 5).
TABLE_OF_PRODUCT: Mapping[str, str] = MappingProxyType({"corine": "clc", "hsg": "hsg"})


def class_entry(table: str | None, value: int) -> ClassEntry | None:
    """Return the class of a raster value in a table, if the table has it."""
    if table is None:
        return None
    return CLASS_TABLES.get(table, {}).get(value)
