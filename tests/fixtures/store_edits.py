"""Changes to a generated store, made the way Kartograf makes them.

A download adds an immutable ``<label>_<sha8>`` version directory next to
the slot's other versions and points the standard path at it: a hard link
with a sidecar naming the version (``extra.link_target``). Tests use these
helpers to change a store after a scan; paths are relative to the store root
(Kartograf's ``--output`` directory) with ``/``.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

META_SUFFIX = ".meta.json"


def add_version(
    root: Path,
    link: str,
    *,
    label: str,
    downloaded_at: str = "2026-10-18T12:00:00+00:00",
    relink: bool = True,
) -> str:
    """Write a new version of the slot whose standard path is ``link``.

    The new version is the current one (named by the link sidecar) with one
    more byte of content, so it gets its own ``sha256``; its sidecar is the
    current version's with the new label, digest and download time.

    Parameters
    ----------
    root : Path
        The store.
    link : str
        Standard path of the slot.
    label : str
        Label of the new version (its directory is ``<label>_<sha8>``).
    downloaded_at : str, optional
        Download time written in the sidecar.
    relink : bool, default True
        Point the standard path at the new version, as a download does.

    Returns
    -------
    str
        The new version file.
    """
    link_path = root / link
    target = _read(_sidecar(link_path))["extra"]["link_target"]
    current = Path(os.path.normpath(link_path.parent / target))
    data = current.read_bytes() + b"\n"
    sha256 = hashlib.sha256(data).hexdigest()
    directory = current.parent.parent / f"{label}_{sha256[:8]}"
    directory.mkdir()
    version = directory / current.name
    version.write_bytes(data)
    meta = _read(_sidecar(current))
    meta["extra"]["version"]["label"] = label
    meta.update(sha256=sha256, size_bytes=len(data), downloaded_at=downloaded_at)
    _write(_sidecar(version), meta)
    if relink:
        link_path.unlink()
        os.link(version, link_path)
        relative = Path(os.path.relpath(version, link_path.parent)).as_posix()
        link_meta = {
            **meta,
            "extra": {**meta["extra"], "link": "hardlink", "link_target": relative},
        }
        _write(_sidecar(link_path), link_meta)
    return version.relative_to(root).as_posix()


def remove_version(root: Path, version: str) -> None:
    """Delete a version directory (its file and sidecar) from the store."""
    shutil.rmtree((root / version).parent)


def sidecar_path(root: Path, path: str) -> Path:
    """Return the sidecar of a store file."""
    return _sidecar(root / path)


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + META_SUFFIX)


def _read(path: Path) -> dict[str, Any]:
    content: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return content


def _write(path: Path, content: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
