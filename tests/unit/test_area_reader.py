"""GeoJSON decoded before GDAL opens it: CRS by name only (SPEC 10.1)."""

import json
from pathlib import Path

import pytest
from shapely.geometry import mapping

from archiwista.area_reader import UPLOAD_NAME, AreaFileError, main, read_area
from archiwista.messages import MESSAGES
from tests.fixtures.area_files import geojson_file, square_wgs84

_LINK = '{"type": "link", "properties": {"href": "http://127.0.0.1:9/crs"}}'
_NAME = '{"type": "name", "properties": {"name": "EPSG:4326"}}'


def _write_upload(directory: Path, content: bytes) -> Path:
    (directory / UPLOAD_NAME).write_bytes(content)
    return directory


def _square_collection(crs_members: str) -> bytes:
    """Return the WGS84 square as a collection with raw ``crs`` members."""
    features = json.dumps(json.loads(geojson_file(mapping(square_wgs84())))["features"])
    text = f'{{"type": "FeatureCollection", {crs_members}, "features": {features}}}'
    return text.encode("utf-8")


@pytest.mark.parametrize(
    "crs_members",
    [
        f'"crs": {_LINK}, "crs": {_NAME}',
        f'"crs": {_NAME}, "crs": {_LINK}',
        '"crs": {"type": "link", "type": "name", "properties": {"name": "x"}}',
    ],
)
def test_area_reader_read_area_repeated_member_cannot_hide_link(
    tmp_path: Path, crs_members: str
) -> None:
    """A repeated ``crs`` or ``type`` member still refuses a link, whichever wins."""
    # Arrange
    directory = _write_upload(tmp_path, _square_collection(crs_members))

    # Act
    with pytest.raises(AreaFileError) as refused:
        read_area(directory)

    # Assert
    assert refused.value.code == "area_unreadable"
    assert refused.value.detail == MESSAGES["area_crs_not_named"]


def test_area_reader_read_area_text_not_utf8_still_read(tmp_path: Path) -> None:
    """A byte that is not UTF-8 in an attribute does not refuse the file."""
    # Arrange: "Łódź" in Windows-1250, as old exports write it.
    content = geojson_file(mapping(square_wgs84())).replace(
        b'"properties": {}', b'"properties": {"name": "\xa3\xf3d\x9f"}'
    )
    directory = _write_upload(tmp_path, content)

    # Act
    answer = read_area(directory)

    # Assert
    assert (answer["format"], answer["crs"], answer["features"]) == (
        "geojson",
        "EPSG:4326",
        1,
    )


@pytest.mark.parametrize(
    "content",
    [b'{"type": "FeatureCollection", "features": [', b'{"a": ' + b"[" * 200_000],
    ids=["broken", "too_deep"],
)
def test_area_reader_main_json_not_decoded_answers_unreadable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes
) -> None:
    """Broken or too deeply nested JSON is a refusal, not a crash of the reader."""
    # Arrange
    directory = _write_upload(tmp_path, content)

    # Act
    code = main([str(directory)])

    # Assert
    answer = json.loads(capsys.readouterr().out)
    assert code == 0
    assert answer["error"] == "area_unreadable"
    prefix = MESSAGES["area_read_failed"].split("{", 1)[0]
    assert answer["detail"].startswith(prefix)
