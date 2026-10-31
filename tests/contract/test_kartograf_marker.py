"""The adapter's probe is Kartograf's own judgement of a store (``store_state``).

``kartograf.testing`` builds the stores and ``kartograf.init_store`` is the
command ``kartograf store init`` (DEV-19.13): the probe agrees with what the
writer does with a directory, and maps its verdicts and refusals to the
reasons of ``SourceState`` (ADR-031, erratum 1).
"""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import kartograf
import pytest
from kartograf.testing import PL_SEGMENT, FixtureStore, build_fixture_store

from archiwista.adapter.kartograf import SCHEMAS, load
from archiwista.adapter.kartograf.adapter import KartografAdapter
from archiwista.messages import message
from archiwista.sources import SourceContext, SourceState
from archiwista.sources.markers import STORE_MARKERS

MARKER = STORE_MARKERS["kartograf"]
MARKER_SCHEMA = "kartograf-store/1"


@pytest.fixture
def adapter(tmp_path: Path) -> KartografAdapter:
    """Kartograf adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "kartograf"))
    assert isinstance(created, KartografAdapter)
    return created


@pytest.fixture
def built(tmp_path: Path) -> FixtureStore:
    """Kartograf's fixture store, marked by the writer that built it."""
    return build_fixture_store(tmp_path / "data")


@pytest.fixture
def root(built: FixtureStore) -> Path:
    """Root of the fixture store."""
    return built.root


def _verdict(state: SourceState) -> tuple[str, str | None]:
    return state.status, state.reason


def test_marker_name_and_schema_are_what_kartograf_writes(tmp_path: Path) -> None:
    """The constants of the adapter are the file and the schema of ``init_store``."""
    # Act
    written = kartograf.init_store(tmp_path / "new").marker

    # Assert
    assert written.name == MARKER
    assert json.loads(written.read_text("utf-8"))["schema"] == MARKER_SCHEMA
    assert MARKER_SCHEMA in SCHEMAS


def test_marker_probe_accepts_the_store_kartograf_builds(
    adapter: KartografAdapter, root: Path
) -> None:
    """A store with its marker is available and has nothing to add."""
    # Act
    state = adapter.probe(root)

    # Assert
    assert (root / MARKER).is_file()
    assert (state.status, state.reason, state.detail, state.hint) == (
        "available",
        None,
        None,
        None,
    )


def test_marker_probe_refuses_a_store_without_marker_until_init_store_ran(
    adapter: KartografAdapter, root: Path
) -> None:
    """The layout without its marker is refused with the command that marks it."""
    # Arrange
    (root / MARKER).unlink()

    # Act
    refused = adapter.probe(root)
    marked = kartograf.init_store(root)
    healed = adapter.probe(root)

    # Assert
    assert _verdict(refused) == ("incompatible", "no_marker")
    assert refused.detail == message("source.no_marker", marker=MARKER)
    assert refused.hint == message("fix.store_init", path=str(root))
    assert marked.created
    assert healed.status == "available"


def test_marker_hint_is_a_command_that_marks_the_store(
    adapter: KartografAdapter, root: Path, tmp_path: Path
) -> None:
    """The command of the hint, run as written, makes the store available."""
    # Arrange: a path that needs quoting
    spaced = root.rename(tmp_path / "my store")
    (spaced / MARKER).unlink()
    hint = adapter.probe(spaced).hint
    assert hint is not None
    command = shlex.split(hint.removeprefix("run once: "))
    assert command[:3] == ["kartograf", "store", "init"]

    # Act
    done = subprocess.run(
        [sys.executable, "-m", "kartograf", *command[1:]],
        capture_output=True,
        text=True,
        check=False,
    )

    # Assert
    assert done.returncode == 0, done.stderr
    assert adapter.probe(spaced).status == "available"


def test_marker_probe_accepts_known_segments_without_a_file(
    adapter: KartografAdapter, tmp_path: Path
) -> None:
    """Directories of known segments and no file below them are no layout yet."""
    # Arrange
    new = tmp_path / "new-store"
    (new / PL_SEGMENT / "versions").mkdir(parents=True)

    # Act
    state = adapter.probe(new)
    marked = kartograf.init_store(new)

    # Assert
    assert _verdict(state) == ("available", None)
    assert marked.created  # Kartograf takes it for a new store, too


def test_marker_probe_does_not_take_a_staging_directory_for_a_layout(
    adapter: KartografAdapter, tmp_path: Path
) -> None:
    """What a writer is still staging does not make the directory a store."""
    # Arrange
    new = tmp_path / "new-store"
    staging = new / PL_SEGMENT / "versions" / ".incoming" / "token"
    staging.mkdir(parents=True)
    (staging / "N-34-130-D-d-2-4.asc").write_bytes(b"x")

    # Act
    state = adapter.probe(new)
    marked = kartograf.init_store(new)

    # Assert
    assert _verdict(state) == ("available", None)
    assert marked.created


def test_marker_probe_refuses_a_marker_of_another_schema(
    adapter: KartografAdapter, root: Path
) -> None:
    """A marker that is not ``kartograf-store/1`` is refused in Kartograf's words."""
    # Arrange
    (root / MARKER).write_text(json.dumps({"schema": "kartograf-store/2"}), "utf-8")

    # Act
    refused = adapter.probe(root)

    # Assert
    assert _verdict(refused) == ("incompatible", "unsupported_marker")
    assert refused.detail is not None and MARKER_SCHEMA in refused.detail
    assert refused.hint is None
    with pytest.raises(kartograf.InvalidLayoutError):
        kartograf.init_store(root)  # Kartograf's own writer refuses it, too


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"tool": "kartograf"}'])
def test_marker_probe_refuses_a_marker_that_is_no_store_document(
    adapter: KartografAdapter, root: Path, content: str
) -> None:
    """A marker that is not JSON, not an object or has no schema is unsupported."""
    # Arrange
    (root / MARKER).write_text(content, "utf-8")

    # Act
    refused = adapter.probe(root)

    # Assert
    assert _verdict(refused) == ("incompatible", "unsupported_marker")
    assert refused.detail is not None and MARKER in refused.detail
    with pytest.raises(kartograf.InvalidLayoutError):
        kartograf.init_store(root)


def test_marker_probe_refuses_the_root_of_an_imgw_store(
    adapter: KartografAdapter, root: Path
) -> None:
    """The marker of another tool makes the root foreign, as Kartograf says."""
    # Arrange
    (root / "imgw-store.json").write_text('{"schema": "imgw-store/1"}', "utf-8")

    # Act
    refused = adapter.probe(root)

    # Assert
    assert _verdict(refused) == ("incompatible", "foreign_store")
    assert refused.detail is not None and "imgw-store.json" in refused.detail
    with pytest.raises(kartograf.ConflictError) as raised:
        kartograf.init_store(root)
    assert raised.value.reason == "nested_store"  # a store never holds another


def test_marker_probe_refuses_an_imgw_root_that_has_no_other_file(
    adapter: KartografAdapter, tmp_path: Path
) -> None:
    """A root with the marker of IMGW and nothing else is foreign, not new."""
    # Arrange
    foreign = tmp_path / "imgw"
    foreign.mkdir()
    (foreign / "imgw-store.json").write_text("{}", "utf-8")

    # Act
    refused = adapter.probe(foreign)

    # Assert
    assert _verdict(refused) == ("incompatible", "foreign_store")


def test_marker_probe_accepts_an_empty_directory(
    adapter: KartografAdapter, tmp_path: Path
) -> None:
    """An empty directory is a new store: its first write creates the marker."""
    # Arrange
    empty = tmp_path / "empty"
    empty.mkdir()

    # Act
    state = adapter.probe(empty)
    marked = kartograf.init_store(empty)

    # Assert
    assert _verdict(state) == ("available", None)
    assert marked.created
    assert adapter.probe(empty).status == "available"


def test_marker_probe_refuses_the_parent_of_a_store(
    adapter: KartografAdapter, built: FixtureStore, tmp_path: Path
) -> None:
    """The directory above a store holds another store: Kartograf's nested store."""
    # Act
    parent = adapter.probe(tmp_path)

    # Assert
    assert _verdict(parent) == ("incompatible", "foreign_store")
    assert parent.detail is not None and str(built.root) in parent.detail
    assert parent.hint is None
    assert adapter.probe(built.root).status == "available"


def test_marker_probe_refuses_a_directory_with_other_files_as_not_a_store(
    adapter: KartografAdapter, tmp_path: Path
) -> None:
    """Other files and no layout: Kartograf's writer refuses it (``not_empty``)."""
    # Arrange
    (tmp_path / "notes.txt").write_text("mine", "utf-8")

    # Act
    refused = adapter.probe(tmp_path)

    # Assert
    assert _verdict(refused) == ("incompatible", "not_a_store")
    assert refused.detail == message("source.kartograf_not_store", marker=MARKER)
    with pytest.raises(kartograf.ConflictError):
        kartograf.init_store(tmp_path)


def test_marker_probe_reports_an_unreadable_marker_as_an_error(
    adapter: KartografAdapter, root: Path
) -> None:
    """A marker that cannot be read is a failure of the system, not of a schema."""
    # Arrange
    if os.geteuid() == 0:
        pytest.skip("root reads every file")
    marker = root / MARKER
    marker.chmod(0)

    # Act
    try:
        state = adapter.probe(root)
    finally:
        marker.chmod(0o644)

    # Assert
    assert state.status == "error"
    assert state.reason is None
    assert state.detail is not None and "Permission denied" in state.detail
