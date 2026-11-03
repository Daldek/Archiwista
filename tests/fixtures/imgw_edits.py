"""Changes to an IMGWTools fixture store, made the way a download changes it.

A download adds an immutable ``<label>_<sha8>`` version directory (the data
file and its ``.meta.json`` sidecar) next to the other versions of a slot. The
helpers change a store built by ``imgwtools.testing`` after a scan; paths are
relative to the store root (IMGWTools' ``--root`` directory) with ``/``.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any

META_SUFFIX = ".meta.json"
_VERSION_DIRECTORY = re.compile(r"^.+_[0-9a-f]{8}$")


def add_version(root: Path, slot: str, *, label: str, like: str | None = None) -> str:
    """Publish a copy of a version of a slot under a new label.

    The copy has the content of the version it is made from (so the same
    ``sha8`` in its directory name) and its sidecar names the new label; for
    an archive the producer picks the current version by the source's
    ``Last-Modified``, then by ``downloaded_at`` and then by path, so the new
    one is current when it sorts after the others by path.

    Parameters
    ----------
    root : Path
        The store.
    slot : str
        The slot's directory.
    label : str
        Label of the new version (its directory is ``<label>_<sha8>``).
    like : str or None, optional
        Directory name of the version to copy; the last one by default.

    Returns
    -------
    str
        The new version's data file.
    """
    directory = root / slot
    source = directory / (like or _version_directories(directory)[-1])
    name = f"{label}_{source.name.rpartition('_')[2]}"
    target = directory / name
    shutil.copytree(source, target)
    (data,) = (path for path in target.iterdir() if not path.name.endswith(META_SUFFIX))
    sidecar = target / (data.name + META_SUFFIX)
    document = _read(sidecar)
    document["extra"]["version"]["label"] = label
    _write(sidecar, document)
    return f"{slot}/{name}/{data.name}"


def remove_version(root: Path, version: str) -> None:
    """Delete the directory of a version (the data file's parent)."""
    shutil.rmtree((root / version).parent)


def break_sidecar(root: Path, version: str) -> None:
    """Make the sidecar of a version unreadable JSON."""
    _sidecar(root, version).write_text("{not json", encoding="utf-8")


def drop_sidecar(root: Path, version: str) -> None:
    """Delete the sidecar of a version: an interrupted publication."""
    _sidecar(root, version).unlink()


def rewrite_sidecar(root: Path, version: str, **fields: object) -> None:
    """Set top-level fields of the sidecar of a version (e.g. ``schema=...``)."""
    sidecar = _sidecar(root, version)
    document = _read(sidecar)
    document.update(fields)
    _write(sidecar, document)


def _version_directories(slot: Path) -> list[str]:
    return sorted(
        path.name
        for path in slot.iterdir()
        if path.is_dir() and _VERSION_DIRECTORY.match(path.name)
    )


def _sidecar(root: Path, version: str) -> Path:
    return root / (version + META_SUFFIX)


def _read(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def _write(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")
