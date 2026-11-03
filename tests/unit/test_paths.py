"""Indexed paths inside their root and private local data (SPEC 10.1)."""

import os
import stat
from pathlib import Path

import pytest

from archiwista.errors import PathOutsideRootError
from archiwista.paths import open_real_file, private_directory, resolve_indexed_path

posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX modes")


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """Create a store root with one version file and a file outside it."""
    root = tmp_path / "store"
    version = root / "nmt" / "versions" / "a_2023_f3015407"
    version.mkdir(parents=True)
    (version / "a.asc").write_text("data", "utf-8")
    (tmp_path / "outside.txt").write_text("outside", "utf-8")
    return root


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.txt",
        "nmt/../../outside.txt",
        "nmt\\..\\..\\outside.txt",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "nmt/a\x00.asc",
        "",
    ],
)
def test_paths_resolve_indexed_path_rejects_escape(store: Path, relative: str) -> None:
    """Absolute paths, ``..`` and NUL never reach the file system."""
    with pytest.raises(PathOutsideRootError):
        resolve_indexed_path(store, relative)


def test_paths_resolve_indexed_path_rejects_symlink_leaving_root(
    store: Path, tmp_path: Path
) -> None:
    """A link inside the store that points outside it is refused."""
    os.symlink(tmp_path / "outside.txt", store / "nmt" / "a.asc")
    os.symlink(tmp_path, store / "nmt" / "parent")

    with pytest.raises(PathOutsideRootError):
        resolve_indexed_path(store, "nmt/a.asc")
    with pytest.raises(PathOutsideRootError):
        resolve_indexed_path(store, "nmt/parent/outside.txt")


def test_paths_resolve_indexed_path_follows_link_inside_root(store: Path) -> None:
    """A standard path linked to a version resolves to the version's file."""
    target = store / "nmt" / "versions" / "a_2023_f3015407" / "a.asc"
    os.symlink(target, store / "nmt" / "a.asc")

    resolved = resolve_indexed_path(store, "nmt/a.asc")

    assert resolved == target.resolve()


def test_paths_open_real_file_reads_what_a_link_inside_root_resolved_to(
    store: Path,
) -> None:
    """The real path of a standard path linked inside the store opens and reads."""
    target = store / "nmt" / "versions" / "a_2023_f3015407" / "a.asc"
    os.symlink(target, store / "nmt" / "a.asc")
    resolved = resolve_indexed_path(store, "nmt/a.asc")

    with os.fdopen(open_real_file(resolved), "rb") as opened:
        read = opened.read()

    assert read == b"data"


@pytest.mark.skipif(os.name != "posix", reason="POSIX links and FIFOs")
@pytest.mark.parametrize("swapped", ["file", "directory", "fifo"])
def test_paths_open_real_file_refuses_what_was_swapped_in_after_the_check(
    store: Path, tmp_path: Path, swapped: str
) -> None:
    """A link in the file's or a directory's place, or a FIFO, is refused at once."""
    resolved = resolve_indexed_path(store, "nmt/versions/a_2023_f3015407/a.asc")
    if swapped == "file":
        resolved.unlink()
        resolved.symlink_to(tmp_path / "outside.txt")
    elif swapped == "directory":
        elsewhere = tmp_path / "elsewhere"
        resolved.parent.rename(elsewhere)
        resolved.parent.symlink_to(elsewhere, target_is_directory=True)
    else:
        resolved.unlink()
        os.mkfifo(resolved)

    with pytest.raises(PathOutsideRootError):
        open_real_file(resolved)


@posix_only
def test_paths_private_directory_created_closed_to_others(tmp_path: Path) -> None:
    """A new data directory is the owner's alone even under a permissive umask."""
    os.umask(0o022)

    created = private_directory(tmp_path / "data" / "jobs")

    assert stat.S_IMODE(created.stat().st_mode) == 0o700


@posix_only
def test_paths_private_directory_closes_existing_open_one(tmp_path: Path) -> None:
    """Data left readable by an older version is closed to ``0700``; files stay."""
    existing = tmp_path / "data"
    existing.mkdir(mode=0o755)
    existing.chmod(0o755)
    (existing / "index.sqlite").write_bytes(b"")

    private_directory(existing)

    assert stat.S_IMODE(existing.stat().st_mode) == 0o700
    assert (existing / "index.sqlite").exists()
