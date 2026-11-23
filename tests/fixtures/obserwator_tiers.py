"""A store of Obserwator 3.2.0's tiers, captures, hourly series and groundwater.

``obserwator.testing`` builds ČHMÚ's groundwater (variant ``groundwater``, its
ADR-032: the bore ``BORE`` and the spring ``SPRING`` with their daily and weekly
series, the bore's operational month of ``cz.chmu.groundwater_recent`` and the
``characteristic`` files of both) but no data of the tiers (its ADR-030,
ADR-031). ``build_tiers_store`` copies that store and adds, with Obserwator's
public writers and no request leaving the process:

* IMGW-PIB's telemetry (``pl.imgw.hydro_telemetry``, tier ``telemetry``) of
  September and October 2026, written by ``write_archive``, for Raba's gauge
  (``RABA``): H every hour of September but the six hours ``HOURLY_GAP`` and of 1
  to 10 October; Q every hour of 1 September and of 1 October only;
* one answer of hydro-back captured at 03:00 UTC of 12 October
  (``pl.imgw.hydro_operational``, tier ``operational``, private) with the H of 10
  and 11 October, spooled by ``obserwator.captures.write_spool`` into a state
  directory of the store's own and sealed by ``sync_store`` into the capture
  version of its day;
* the hourly series ``SUBDAILY`` built by ``build_series``, one version per month
  (Obserwator ADR-031): the slots ``series:pl.imgw.hydro_subdaily:2026-09`` and
  ``…:2026-10``. Its H runs from the first hour of September to the last of
  11 October with the one gap ``HOURLY_GAP``; its Q from the first hour of
  1 September to the last of 1 October, every hour between them a gap.
"""

import io
import json
import shutil
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from obserwator import DownloadResult, archive_files, build_series, sync_store
from obserwator import write_archive as write_obserwator_archive
from obserwator.captures import write_spool
from obserwator.providers.base import Answer

from tests.fixtures.obserwator_http import standin_source
from tests.fixtures.obserwator_roots import data_root, raw_root

RABA = "149190310"
BORE = "0-203-1-VP0624"
SPRING = "0-203-1-PP0744"
TELEMETRY = "pl.imgw.hydro_telemetry"
OPERATIONAL = "pl.imgw.hydro_operational"
SUBDAILY = "pl.imgw.hydro_subdaily"
WEEKLY = "cz.chmu.groundwater_weekly"
GROUNDWATER_DAILY = "cz.chmu.groundwater_daily"
RECENT = "cz.chmu.groundwater_recent"
CHARACTERISTIC = "cz.chmu.groundwater_characteristic"
MONTHS = ("2026-09", "2026-10")
# The hours of 15 September without H, both ends included.
HOURLY_GAP = (
    datetime(2026, 9, 15, 6, tzinfo=UTC),
    datetime(2026, 9, 15, 11, tzinfo=UTC),
)
# When hydro-back's answer came, and the first of its 48 hours.
CAPTURED_AT = datetime(2026, 10, 12, 3, tzinfo=UTC)
_CAPTURE_START = datetime(2026, 10, 10, tzinfo=UTC)
_HOURS = 48
# IMGW-PIB's telemetry codes of the water level and of the discharge.
_LEVEL, _DISCHARGE = "B00020S", "B00050S"
_PUBLISHED = "Mon, 16 Nov 2026 10:26:00 GMT"


def build_tiers_store(root: Path, groundwater: Path) -> Path:
    """Copy ``groundwater`` to ``root`` and add the tiers and the hourly series.

    Obserwator's state directory (its spool of captures) is ``<root>-state``
    while the store is built, so no spool of another test is sealed here.

    Raises
    ------
    AssertionError
        The capture was not sealed or a month of the series was not built.
    """
    shutil.copytree(groundwater, root)
    raw = raw_root(root)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("OBSERWATOR_STATE_DIR", str(root.with_name(f"{root.name}-state")))
        for archive in archive_files(TELEMETRY, years=[2026], months=[9, 10]):
            content = _telemetry(archive.month or 0)
            write_obserwator_archive(
                raw,
                archive=archive,
                response=DownloadResult(
                    content, archive.url, None, _PUBLISHED, len(content)
                ),
            )
        assert write_spool(_answer()) is not None
        with standin_source():
            report = sync_store(raw, datasets=[OPERATIONAL])
        assert [item.status for item in report.items] == ["new"], report
        series = build_series(
            data_root(root),
            raw_root=raw,
            dataset=SUBDAILY,
            start=date(2026, 9, 1),
            end=date(2026, 10, 31),
        )
    built = [
        (None if item.version is None else item.version.parent.parent.name, item.status)
        for item in series.months or ()
    ]
    assert built == [(month, "new") for month in MONTHS], series
    return root


def _telemetry(month: int) -> bytes:
    """Return the telemetry archive of a month of 2026, as IMGW-PIB zips it."""
    days = range(1, 31) if month == 9 else range(1, 11)
    gap_start, gap_end = HOURLY_GAP
    rows: list[str] = []
    for day in days:
        for hour in range(24):
            moment = datetime(2026, month, day, hour, tzinfo=UTC)
            if not gap_start <= moment <= gap_end:
                rows.append(f"{RABA};{_LEVEL};{moment:%Y-%m-%d %H:%M};{100 + hour}")
    rows += [
        f"{RABA};{_DISCHARGE};2026-{month:02d}-01 {hour:02d}:00;1,5"
        for hour in range(24)
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(f"{_LEVEL}_2026_{month:02d}.csv", "\r\n".join(rows))
    return buffer.getvalue()


def _answer() -> Answer:
    """Return hydro-back's answer of 12 October: the H of 10 and 11 October."""
    body = {
        "operational": [
            {
                "date": f"{_CAPTURE_START + timedelta(hours=step):%Y-%m-%dT%H:%M:%SZ}",
                "value": 200 + step,
            }
            for step in range(_HOURS)
        ]
    }
    return Answer(
        url=(
            "https://hydro-back.imgw.pl/station/hydro/status/data"
            f"?id={RABA}&hoursInterval={_HOURS}"
        ),
        received_at=CAPTURED_AT,
        status=200,
        content=json.dumps(body).encode(),
        dataset=OPERATIONAL,
    )
