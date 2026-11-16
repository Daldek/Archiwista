"""Local memory of unit outlines that Kartograf's offline footprints read."""

from pathlib import Path

import pytest
from kartograf import BBox

from archiwista.adapter.kartograf.unit_cache import UnitBBoxCache

TERYT = ("teryt", "1465")
KU = ("ku", "623164")


def test_unit_cache_missing_file_reads_empty_without_creating_it(
    tmp_path: Path,
) -> None:
    """Reading a cache that was never written creates no file or directory."""
    cache = UnitBBoxCache(tmp_path / "cache" / "unit_bboxes.sqlite")

    found = (TERYT in cache, len(cache), list(cache))

    assert found == (False, 0, [])
    assert not (tmp_path / "cache").exists()


def test_unit_cache_outlines_written_once_are_read_by_another_instance(
    tmp_path: Path,
) -> None:
    """Outlines stored by one job are read later by another, then forgotten."""
    path = tmp_path / "unit_bboxes.sqlite"
    writer = UnitBBoxCache(path)
    writer[TERYT] = BBox(560_000.0, 240_000.0, 580_000.0, 260_000.0, "EPSG:2180")
    writer[KU] = BBox(-470_000.0, -1_130_000.0, -460_000.0, -1_120_000.0, "EPSG:5514")
    writer.close()

    reader = UnitBBoxCache(path)
    outline = reader[TERYT]
    del reader[KU]

    assert outline == BBox(560_000.0, 240_000.0, 580_000.0, 260_000.0, "EPSG:2180")
    assert list(reader) == [TERYT]
    with pytest.raises(KeyError):
        del reader[KU]
    reader.close()
