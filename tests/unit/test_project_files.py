"""The project file on the disk: its lock, atomic writes and area files (A-ADR-049).

A held lock is waited for, then refused with its owner, and never removed;
a failed write leaves the file whole and nothing beside it; writers of two
processes lose no change; the area file is written once per content and
read back only with the bytes the project file records.
"""

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from archiwista.errors import (
    ProjectAreaError,
    ProjectFileError,
    ProjectFileWriteError,
    ProjectLockedError,
)
from archiwista.index import AreaRecord
from archiwista.projects import (
    LOCK_NAME,
    LOCK_OWNER,
    PROJECT_FILE,
    AreaRef,
    ProjectDocument,
    change_project_file,
    read_project_area,
    read_project_file,
    write_area_file,
)
from archiwista.sandbox import process_owner
from archiwista.sources import GeoJSONGeometry

DOCUMENT = ProjectDocument(
    name="Raba",
    description="",
    created_at=datetime(2026, 10, 31, 12, 4, 11, tzinfo=UTC),
    created_by="local",
)
SQUARE: GeoJSONGeometry = {
    "type": "Polygon",
    "coordinates": [
        [[19.0, 50.0], [19.1, 50.0], [19.1, 50.1], [19.0, 50.1], [19.0, 50.0]]
    ],
}
AREA = AreaRecord(
    id="5f2b9c0e7d41a3b6",
    source="drawn",
    geometry=SQUARE,
    created_at=datetime(2026, 10, 31, 12, 0, tzinfo=UTC),
    area_km2=79.6,
    countries=("PL",),
    name="Raba",
)
# Two processes each adding groups through the lock.
ADD_GROUPS = """
import sys
from pathlib import Path

from archiwista.projects import change_project_file

directory, prefix = Path(sys.argv[1]), sys.argv[2]
for index in range(20):
    group = {"name": f"{prefix}-{index}", "origin": {"kind": "local", "selections": []},
             "pins": []}
    change_project_file(directory, lambda raw: raw["groups"].append(group), wait_s=60)
"""


def _project(directory: Path) -> bytes:
    change_project_file(directory, create=DOCUMENT)
    return (directory / PROJECT_FILE).read_bytes()


def _hold_lock(directory: Path, owner: str) -> Path:
    lock = directory / LOCK_NAME
    lock.mkdir()
    (lock / LOCK_OWNER).write_text(f"{owner} 2026-10-31T12:00:00Z\n", encoding="utf-8")
    return lock


def test_project_files_change_creates_the_file_once(tmp_path: Path) -> None:
    """A new file is written once; creating it again is ``project_exists``."""
    _project(tmp_path)

    with pytest.raises(ProjectFileError) as raised:
        change_project_file(tmp_path, create=DOCUMENT)

    assert raised.value.details["reason"] == "project_exists"
    assert read_project_file(tmp_path) == DOCUMENT
    assert sorted(item.name for item in tmp_path.iterdir()) == [PROJECT_FILE]


def test_project_files_change_waits_for_a_held_lock_then_names_its_owner(
    tmp_path: Path,
) -> None:
    """Another writer's lock is waited for, refused with its owner and kept."""
    before = _project(tmp_path)
    lock = _hold_lock(tmp_path, "other-host_4242")
    started = time.monotonic()

    with pytest.raises(ProjectLockedError) as raised:
        change_project_file(tmp_path, lambda raw: raw.update(name="X"), wait_s=0.3)

    assert time.monotonic() - started >= 0.3
    assert raised.value.code == "conflict"
    assert raised.value.details == {
        "reason": "project_locked",
        "lock": str(lock),
        "owner": "other-host_4242",
        "owner_ended": False,
    }
    assert str(lock) in (raised.value.hint or "")
    assert (lock / LOCK_OWNER).is_file()
    assert (tmp_path / PROJECT_FILE).read_bytes() == before


def test_project_files_change_names_a_lock_of_an_ended_process_and_keeps_it(
    tmp_path: Path,
) -> None:
    """A lock left by a process of this computer that ended is said so, not removed."""
    _project(tmp_path)
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()
    host = process_owner().rsplit("_", 1)[0]
    lock = _hold_lock(tmp_path, f"{host}_{ended.pid}")

    with pytest.raises(ProjectLockedError) as raised:
        change_project_file(tmp_path, lambda raw: raw.update(name="X"), wait_s=0.1)

    assert raised.value.details["owner_ended"] is True
    assert raised.value.message.key == "project.file_locked_ended"  # type: ignore[attr-defined]
    assert lock.is_dir()


def test_project_files_change_after_a_released_lock_succeeds(tmp_path: Path) -> None:
    """A change removes its own lock, so the next one finds none."""
    _project(tmp_path)

    change_project_file(tmp_path, lambda raw: raw.update(name="A"))
    change_project_file(tmp_path, lambda raw: raw.update(name="B"))

    assert read_project_file(tmp_path).name == "B"
    assert not (tmp_path / LOCK_NAME).exists()


def test_project_files_failed_replace_leaves_the_old_file_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure in ``os.replace`` leaves the file, no temporary file and no lock."""
    before = _project(tmp_path)

    def failing(source: object, target: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", failing)
    with pytest.raises(ProjectFileWriteError) as raised:
        change_project_file(tmp_path, lambda raw: raw.update(name="X"))
    monkeypatch.undo()

    assert raised.value.code == "io_error"
    assert raised.value.details["reason"] == "project_file_write_failed"
    assert (tmp_path / PROJECT_FILE).read_bytes() == before
    assert sorted(item.name for item in tmp_path.iterdir()) == [PROJECT_FILE]


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes a read-only directory")
def test_project_files_change_in_a_read_only_directory_is_a_write_failure(
    tmp_path: Path,
) -> None:
    """A read-only share is ``project_file_write_failed``, the file untouched."""
    before = _project(tmp_path)
    tmp_path.chmod(0o555)
    try:
        with pytest.raises(ProjectFileWriteError) as raised:
            change_project_file(tmp_path, lambda raw: raw.update(name="X"))
    finally:
        tmp_path.chmod(0o755)

    assert raised.value.details["reason"] == "project_file_write_failed"
    assert (tmp_path / PROJECT_FILE).read_bytes() == before


def test_project_files_change_refuses_an_invalid_file_and_leaves_it(
    tmp_path: Path,
) -> None:
    """Archiwista never writes over a file it cannot read."""
    path = tmp_path / PROJECT_FILE
    path.write_text('{"schema": "archiwista-project/1", "name": ""}', encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(ProjectFileError) as raised:
        change_project_file(tmp_path, lambda raw: raw.update(name="X"))

    assert raised.value.details["reason"] == "invalid_project_file"
    assert raised.value.details["pointer"] == "/name"
    assert path.read_bytes() == before
    assert not (tmp_path / LOCK_NAME).exists()


@pytest.mark.parametrize(
    ("content", "rule"),
    [
        (b"\xef\xbb\xbf{}", "invalid_json"),
        (b'{"schema": NaN}', "invalid_json"),
        (b"[" * 100_000, "invalid_json"),
        (b"[]", "object"),
        (b" " * (32 * 1024**2 + 1), "too_large"),
    ],
)
def test_project_files_read_refuses_a_file_that_is_no_json_object(
    tmp_path: Path, content: bytes, rule: str
) -> None:
    """A file with a byte-order mark, ``NaN``, too deep, no object or too large."""
    (tmp_path / PROJECT_FILE).write_bytes(content)

    with pytest.raises(ProjectFileError) as raised:
        read_project_file(tmp_path)

    assert raised.value.details["pointer"] == ""
    assert raised.value.details["rule"] == rule


def test_project_files_two_processes_adding_groups_lose_none(tmp_path: Path) -> None:
    """Two processes each adding 20 groups through the lock keep all 40."""
    _project(tmp_path)

    writers = [
        subprocess.Popen([sys.executable, "-c", ADD_GROUPS, str(tmp_path), prefix])
        for prefix in ("a", "b")
    ]
    codes = [writer.wait(timeout=120) for writer in writers]

    assert codes == [0, 0]
    names = {group.name for group in read_project_file(tmp_path).groups}
    assert names == {f"{prefix}-{index}" for prefix in "ab" for index in range(20)}
    assert not (tmp_path / LOCK_NAME).exists()


def test_project_files_write_area_file_keeps_an_identical_file(tmp_path: Path) -> None:
    """The area is a FeatureCollection of one feature, written once per content."""
    ref = write_area_file(tmp_path, AREA)
    written = tmp_path / ref.path
    stamp = written.stat().st_mtime_ns
    inode = written.stat().st_ino

    again = write_area_file(tmp_path, AREA)

    assert again == ref == AreaRef(path=f"obszary/{AREA.id}.geojson", sha256=ref.sha256)
    assert (written.stat().st_mtime_ns, written.stat().st_ino) == (stamp, inode)
    collection = json.loads(written.read_text(encoding="utf-8"))
    assert collection["type"] == "FeatureCollection"
    (feature,) = collection["features"]
    assert feature["geometry"] == SQUARE
    assert feature["properties"] == {
        "name": "Raba",
        "source": "drawn",
        "area_km2": 79.6,
        "countries": ["PL"],
    }
    assert read_project_area(tmp_path, ref) == SQUARE


def test_project_files_read_project_area_names_a_missing_or_changed_file(
    tmp_path: Path,
) -> None:
    """No file is ``missing``; other bytes are ``changed`` and not used."""
    ref = write_area_file(tmp_path, AREA)
    other = AreaRef(path="obszary/0000000000000000.geojson", sha256=ref.sha256)
    (tmp_path / ref.path).write_text(
        (tmp_path / ref.path).read_text(encoding="utf-8").replace("19.1", "19.2"),
        encoding="utf-8",
    )

    with pytest.raises(ProjectAreaError) as missing:
        read_project_area(tmp_path, other)
    with pytest.raises(ProjectAreaError) as changed:
        read_project_area(tmp_path, ref)

    assert missing.value.state == "missing"
    assert changed.value.state == "changed"


def test_project_files_read_project_area_refuses_a_link_out_of_the_project(
    tmp_path: Path,
) -> None:
    """An area file that is a link leaving the project directory is ``invalid``."""
    project = tmp_path / "raba"
    project.mkdir()
    ref = write_area_file(tmp_path, AREA)
    (project / "obszary").mkdir()
    (project / ref.path).symlink_to(tmp_path / ref.path)

    with pytest.raises(ProjectAreaError) as raised:
        read_project_area(project, ref)

    assert raised.value.state == "invalid"
