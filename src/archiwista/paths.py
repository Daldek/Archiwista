"""Local paths: indexed paths inside their root, private local data (SPEC 10.1).

The API accepts only paths the index knows; a file is opened only through
``resolve_indexed_path``, which resolves symbolic links and refuses a path
whose real location leaves its store or project root, and then by
``open_real_file``, which opens that real path without following any link,
so a link put in its place after the check cannot lead outside. Local data
(the index, the state database, job logs, copies of area files) belongs to
its user alone: ``private_directory`` keeps its directories closed to other
accounts. Without web dependencies, so background job workers use it too.
"""

import contextlib
import errno
import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

from archiwista.errors import PathOutsideRootError
from archiwista.messages import message

# Owner only: read, write, enter.
PRIVATE_DIRECTORY_MODE = 0o700


def private_directory(path: Path) -> Path:
    """Create a directory only its owner may enter, or close an existing one.

    On POSIX the directory gets mode ``0700``, also when it existed with a
    wider one (data written by an older Archiwista); a directory of another
    account keeps its mode (``archiwista doctor`` reports it). Missing
    parents are created as usual. Elsewhere it is only created.

    Returns
    -------
    Path
        ``path``.
    """
    path.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    if os.name == "posix" and (
        stat.S_IMODE(path.stat().st_mode) != PRIVATE_DIRECTORY_MODE
    ):
        with contextlib.suppress(PermissionError):
            path.chmod(PRIVATE_DIRECTORY_MODE)
    return path


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
        raise PathOutsideRootError(message("ref.path_outside_root", path=relative))
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
        text = message("ref.path_outside_root", path=relative)
        raise PathOutsideRootError(text)
    return real


def open_real_file(real: Path) -> int:
    """Open a regular file at its real path without following any link.

    The path is what ``resolve_indexed_path`` returned, checked to lie in its
    root. Each directory from the file system's root down is opened relative
    to its parent, then the file, none through a symbolic link
    (``O_NOFOLLOW``): the descriptor is the file at that very path now, so a
    link swapped into any part of it since the check (a time-of-check race)
    is refused instead of followed out of the root. Read the file through
    the descriptor only, never again by its path.

    Parameters
    ----------
    real : Path
        An absolute path with every link resolved.

    Returns
    -------
    int
        A descriptor open for reading (non-blocking); the caller closes it.

    Raises
    ------
    PathOutsideRootError
        A part of the path is a symbolic link now, or the file is not a
        regular file (e.g. a FIFO); the error names the file only.
    OSError
        The file cannot be opened, e.g. ``FileNotFoundError`` when it is gone.
    """
    outside = PathOutsideRootError(message("ref.path_outside_root", path=real.name))
    # A directory is only passed through (``O_PATH`` where the system has it
    # needs no right to list it); a FIFO in the file's place does not block.
    passing = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_NOFOLLOW
    reading = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    parts = real.parts
    current = os.open(parts[0], passing | os.O_CLOEXEC)
    try:
        for part in parts[1:-1]:
            following = os.open(part, passing | os.O_CLOEXEC, dir_fd=current)
            os.close(current)
            current = following
        descriptor = os.open(parts[-1], reading | os.O_CLOEXEC, dir_fd=current)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise outside from None
        raise
    finally:
        os.close(current)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise outside
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor
