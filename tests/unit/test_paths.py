"""Indexed paths resolved inside their store or project root (SPEC 10.1)."""

import os
from pathlib import Path

import pytest

from archiwista.errors import PathOutsideRootError
from archiwista.paths import resolve_indexed_path


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
