"""A store of IMGW-PIB half-year characteristics and monthly series (A-ADR-051).

``obserwator.testing`` builds no store with them: its archives
``polr_{H,Q,T}_2024.zip`` and ``mies_2024.zip`` hold one station's one year,
both halves of it equal. This writes archives of the layout IMGW-PIB
publishes (CP1250 CSV in ZIP: ``polr_<P>_<year>.zip`` of 18 columns,
``mies_<year>.zip`` of 10) for the stations of the fixtures' station list, and
Obserwator's own ``sync_store`` downloads them through the stood-in source
(``obserwator_http.standin_source``) and builds their series into a copy of
``complete``, whose daily series and station catalog stay as they are.

Raba Górna (``RABA``) has the daily series, the monthly series of the
hydrological years 2023 and 2024 (March 2024 missing) and the half-year
characteristics of 2020 to 2024. Its Q (``RABA_Q``) holds each case of the
annual chart: 2020 the winter maximum above the summer one and the summer
minimum below the winter one (two occurrences, 18 and 19 August), 2021 no
value in either half, 2022 equal maxima in both halves (one winter
occurrence and two summer ones), 2023 the summer missing and the winter
maximum published without a day (``2023-03``), 2024 the winter absent. Its H
has both halves every year, its T no value. Stacja Bez Q (``WITHOUT_Q``) has
monthly H and T but no monthly Q; Stacja Bez Miejsca (``HALF_YEARS_ONLY``)
has the half-year characteristics of Q only, 2023 without the summer.
"""

import io
import shutil
import zipfile
from collections.abc import Iterable
from pathlib import Path

from obserwator import sync_store

from tests.fixtures.obserwator_http import standin_source

HALF_YEAR = "pl.imgw.hydro_semiannual"
MONTHLY = "pl.imgw.hydro_monthly"
RABA = "149190310"
WITHOUT_Q = "149190311"
HALF_YEARS_ONLY = "149190312"
HALF_YEARS = range(2020, 2025)
MONTH_YEARS = range(2023, 2025)

type When = tuple[int, ...]
# A row of a half-year archive: station, hydrological year, period (13 winter,
# 14 summer, 15 year), quantity, statistic (1 min, 2 mean, 3 max), value, and
# the first and last time of the extreme (year, month, day, hour, minute; as
# many fields as published).
type HalfYearRow = tuple[str, int, int, str, int, str, When | None, When | None]

_NAMES = {
    RABA: ("Raba Górna", "Raba"),
    WITHOUT_Q: ("Stacja Bez Q", "Raba"),
    HALF_YEARS_ONLY: ("Stacja Bez Miejsca", "Raba"),
}
# IMGW-PIB's codes of a missing value, by quantity.
_MISSING = {"H": "9999", "Q": "99999.999", "T": "99.9"}
# The hydrological year's mean, the only annual value IMGW-PIB publishes.
_MEAN = 2

RABA_Q: tuple[HalfYearRow, ...] = (
    (RABA, 2020, 13, "Q", 3, "223", (2020, 3, 2, 12, 0), (2020, 3, 2, 12, 0)),
    (RABA, 2020, 14, "Q", 3, "103", (2020, 10, 29, 6, 0), (2020, 10, 29, 6, 0)),
    (RABA, 2020, 13, "Q", 1, "40.5", (2020, 1, 5, 6, 0), (2020, 1, 5, 6, 0)),
    (RABA, 2020, 14, "Q", 1, "32.7", (2020, 8, 18, 6, 0), (2020, 8, 18, 6, 0)),
    (RABA, 2020, 14, "Q", 1, "32.7", (2020, 8, 19, 6, 0), (2020, 8, 19, 6, 0)),
    (RABA, 2021, 13, "Q", 3, _MISSING["Q"], None, None),
    (RABA, 2021, 14, "Q", 3, _MISSING["Q"], None, None),
    (RABA, 2021, 13, "Q", 1, _MISSING["Q"], None, None),
    (RABA, 2021, 14, "Q", 1, _MISSING["Q"], None, None),
    (RABA, 2022, 13, "Q", 3, "150", (2022, 2, 10, 6, 0), (2022, 2, 10, 6, 0)),
    (RABA, 2022, 14, "Q", 3, "150", (2022, 6, 5, 6, 0), (2022, 6, 5, 6, 0)),
    (RABA, 2022, 14, "Q", 3, "150", (2022, 6, 6, 6, 0), (2022, 6, 6, 6, 0)),
    (RABA, 2022, 13, "Q", 1, "20", (2021, 12, 1, 6, 0), (2021, 12, 1, 6, 0)),
    (RABA, 2022, 14, "Q", 1, "21", (2022, 9, 1, 6, 0), (2022, 9, 1, 6, 0)),
    (RABA, 2023, 13, "Q", 3, "180", (2023, 3), None),
    (RABA, 2023, 13, "Q", 1, "25", (2023, 1, 1, 6, 0), (2023, 1, 1, 6, 0)),
    (RABA, 2023, 14, "Q", 3, _MISSING["Q"], None, None),
    (RABA, 2023, 14, "Q", 1, _MISSING["Q"], None, None),
    (RABA, 2024, 14, "Q", 3, "90", (2024, 7, 9, 6, 0), (2024, 7, 9, 6, 0)),
    (RABA, 2024, 14, "Q", 1, "10", (2024, 9, 9, 6, 0), (2024, 9, 9, 6, 0)),
)


def half_year_rows() -> list[HalfYearRow]:
    """Return every row of the half-year archives of 2020 to 2024."""
    rows: list[HalfYearRow] = list(RABA_Q)
    for year in HALF_YEARS:
        rows.append((RABA, year, 15, "Q", _MEAN, "60", None, None))
        winter = (year, 2, 1, 6, 0)
        summer = (year, 7, 1, 6, 0)
        rows += [
            (RABA, year, 13, "H", 3, str(240 + year % 10), winter, winter),
            (RABA, year, 14, "H", 3, str(250 + year % 10), summer, summer),
            (RABA, year, 13, "H", 1, str(110 + year % 10), winter, winter),
            (RABA, year, 14, "H", 1, str(100 + year % 10), summer, summer),
            (RABA, year, 13, "T", 3, _MISSING["T"], None, None),
            (RABA, year, 14, "T", 3, _MISSING["T"], None, None),
        ]
        summer_q = _MISSING["Q"] if year == 2023 else str(70 + year % 10)
        rows += [
            (HALF_YEARS_ONLY, year, 13, "Q", 3, str(60 + year % 10), winter, winter),
            (HALF_YEARS_ONLY, year, 14, "Q", 3, summer_q, summer, summer),
            (HALF_YEARS_ONLY, year, 13, "Q", 1, str(5 + year % 10), winter, winter),
            (HALF_YEARS_ONLY, year, 14, "Q", 1, str(4 + year % 10), summer, summer),
        ]
    return rows


def archives() -> dict[str, bytes]:
    """Return the half-year and monthly archives, by server path."""
    found: dict[str, bytes] = {}
    rows = half_year_rows()
    for year in HALF_YEARS:
        for quantity in ("H", "Q", "T"):
            lines = [
                _half_year_line(row)
                for row in rows
                if row[1] == year and row[3] == quantity
            ]
            name = f"polr_{quantity}_{year}"
            path = f"dane_hydrologiczne/polroczne_i_roczne/{year}/{name}.zip"
            found[path] = _zipped(f"{name}.csv", lines)
    for year in MONTH_YEARS:
        name = f"mies_{year}"
        path = f"dane_hydrologiczne/miesieczne/{year}/{name}.zip"
        found[path] = _zipped(f"{name}.csv", _monthly_lines(year))
    return found


def monthly_value(
    code: str, quantity: str, year: int, month: int, statistic: int
) -> str:
    """Return a monthly value as published: the missing code where there is none.

    ``month`` is the month of the hydrological year (1 is November) and
    ``statistic`` 1, 2 or 3 (minimum, mean, maximum). March 2024 (month 5 of
    2024) is missing at every station, and Stacja Bez Q has no Q.
    """
    if (year, month) == (2024, 5) or (code, quantity) == (WITHOUT_Q, "Q"):
        return _MISSING[quantity]
    base = {"H": 100.0, "Q": 1.0, "T": 2.0}[quantity]
    step = {"H": 3.0, "Q": 0.5, "T": 0.25}[quantity]
    spread = {"H": 10.0, "Q": 1.0, "T": 0.5}[quantity]
    value = base + month * step + (statistic - 2) * spread + (year - 2023)
    return f"{value:g}"


def build_statistics_store(root: Path, complete: Path) -> Path:
    """Copy ``complete`` to ``root`` and sync the archives into it with Obserwator.

    Raises
    ------
    AssertionError
        A series was not built anew.
    """
    shutil.copytree(complete, root)
    with standin_source() as source:
        source.archives.update(archives())
        reports = [
            sync_store(root, datasets=[HALF_YEAR], years=HALF_YEARS),
            sync_store(root, datasets=[MONTHLY], years=MONTH_YEARS),
        ]
    statuses = [series.status for report in reports for series in report.series]
    assert statuses == ["new", "new"], [r.series for r in reports]
    return root


def _half_year_line(row: HalfYearRow) -> str:
    code, year, period, quantity, statistic, value, first, last = row
    name, river = _NAMES[code]
    times = [*_time_fields(first), *_time_fields(last)]
    cells = [code, name, river, str(year), str(period), quantity, str(statistic)]
    return ",".join([*cells, value, *times])


def _time_fields(when: When | None) -> list[str]:
    """Five fields of a time: year, month, day, hour, minute; empty past those given."""
    given = [str(part) for part in when or ()]
    return given + [""] * (5 - len(given))


def _monthly_lines(year: int) -> list[str]:
    lines: list[str] = []
    for code in (RABA, WITHOUT_Q):
        name, river = _NAMES[code]
        for month in range(1, 13):
            calendar = month + 10 if month <= 2 else month - 2
            for statistic in (1, 2, 3):
                values = [
                    monthly_value(code, quantity, year, month, statistic)
                    for quantity in ("H", "Q", "T")
                ]
                cells = [code, name, river, str(year), str(month), str(statistic)]
                lines.append(",".join([*cells, *values, str(calendar)]))
    return lines


def _zipped(member: str, lines: Iterable[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "\n".join(lines).encode("cp1250"))
    return buffer.getvalue()
