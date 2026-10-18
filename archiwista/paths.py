"""Paths taken from the index, joined and resolved inside their root (SPEC 10.1).

The API accepts only paths the index knows; a file is opened only through
``resolve_indexed_path``, which resolves symbolic links and refuses a path
whose real location leaves its store or project root. Without web
dependencies, so background job workers use it too.
"""

from pathlib import Path, PurePosixPath, PureWindowsPath

from archiwista.errors import PathOutsideRootError
from archiwista.messages import MESSAGES


def indexed_path(root: Path, relative: str) -> Path:
    """Return where an indexed path lies below its root, without touching the disk.

    The file card's "copy path": a store's directory on this computer joined
    with a path the index holds. Symbolic links are not followed; a file is
    opened only through ``resolve_indexed_path``.

    Parameters
    ----------
    root : Path
        Configured producer directory of a store, or a project directory.
    relative : str
        Slot, version or project path relative to ``root`` as stored in the
        local index (``/`` separators).

    Returns
    -------
    Path
        ``root`` joined with the parts of ``relative``.

    Raises
    ------
    PathOutsideRootError
        If the path is empty, absolute, names a drive, contains ``..`` or a
        NUL character.
    """
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if (
        not relative
        or "\x00" in relative
        or posix.is_absolute()
        or windows.anchor
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise PathOutsideRootError(MESSAGES["path_outside_root"].format(path=relative))
    return root.joinpath(*posix.parts)


def resolve_indexed_path(root: Path, relative: str) -> Path:
    """Resolve an indexed path inside its store or project root.

    Parameters
    ----------
    root : Path
        Configured producer directory of a store, or a project directory.
    relative : str
        Slot, version or project path relative to ``root`` as stored in the
        local index (``/`` separators). Never a raw path from a client:
        routes look the identifier up in the index first.

    Returns
    -------
    Path
        The real path (symbolic links resolved) inside the real root.

    Raises
    ------
    PathOutsideRootError
        If the path is absolute, contains ``..`` or a NUL character, or
        resolves outside the root, e.g. through a symbolic link.
    FileNotFoundError
        If the root or the file does not exist (e.g. a disconnected share).
    """
    joined = indexed_path(root, relative)
    real_root = root.resolve(strict=True)
    real = joined.resolve(strict=True)
    if not real.is_relative_to(real_root):
        message = MESSAGES["path_outside_root"].format(path=relative)
        raise PathOutsideRootError(message)
    return real
