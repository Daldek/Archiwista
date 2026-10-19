"""Sandbox of the processes that read untrusted files (plan v0.2, decision 3).

Every process opening data files with GDAL, OGR, laspy or ``zipfile`` (the
area reader, the render processes, the COG builds and the own-data reader)
is started through this module:

- ``untrusted_env()``: a minimal environment without proxies or credentials
  that keeps GDAL and PROJ offline, with ``GDAL_PAM_ENABLED=NO`` (statistics
  never write ``<file>.aux.xml`` next to the data),
  ``GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`` (GDAL sees no ``.ovr``,
  ``.msk``, ``.aux.xml`` or world file next to a file; a Shapefile still
  reads its ``.shx .dbf .prj .cpg`` and a MapInfo table its ``.dat .map
  .id``), ``GDAL_SKIP`` of the drivers that refer to other files or to the
  network (``SKIPPED_GDAL_DRIVERS``) and a bounded GDAL block cache;
- ``child_limits()``: the child in its own session (killed as a whole),
  ``umask 077`` and, on POSIX, ``RLIMIT_AS``;
- ``run_untrusted()``: one such process run to its end, its group killed
  after a time limit;
- ``process_work_dir()``: the calling process's own scratch directory
  ``<data_dir>/work/<host>_<pid>_<token>/``.

``GDAL_SKIP`` is only a second line of defence: the first ``WarpedVRT`` in
a process registers the VRT driver again. Files are therefore opened with
an explicit driver (``archiwista.formats``).
"""

import contextlib
import functools
import logging
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from archiwista.config import AppPaths
from archiwista.paths import private_directory

if sys.platform != "win32":
    import resource

# Inherited by the child: what Python and its libraries need to start on
# Linux and Windows, ARCHIWISTA_* (the application's own) and COVERAGE_*
# (measuring the children in tests). Nothing about proxies, credentials,
# GDAL or the network: libcurl honours NO_PROXY even with GDAL_HTTP_PROXY.
UNTRUSTED_INHERITED = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "LANG",
        "LANGUAGE",
        "LD_LIBRARY_PATH",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROJ_DATA",
        "PROJ_LIB",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUTF8",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WINDIR",
        "XDG_DATA_HOME",
    }
)
UNTRUSTED_INHERITED_PREFIXES = ("ARCHIWISTA_", "COVERAGE_", "LC_")
# Drivers whose files name other files or network addresses: VRT and its
# relatives, web services, and raw formats whose header points to the data.
SKIPPED_GDAL_DRIVERS: tuple[str, ...] = (
    "VRT",
    "OGR_VRT",
    "GTI",
    "WMS",
    "WMTS",
    "WCS",
    "WFS",
    "OAPIF",
    "OGCAPI",
    "STACIT",
    "STACTA",
    "PDS",
    "PDS4",
    "ISIS3",
    "ERS",
    "ENVI",
    "EHdr",
    "GML",
)
# GDAL's raster block cache in MB (by default 5% of the RAM), well below
# the address-space limit of a render process.
GDAL_CACHE_MB = 256
# GDAL and PROJ kept offline even if they try to fetch something: every
# request goes to a closed local port, gives up within a second, untried
# again. Sibling files and the PAM side files stay out of reach.
UNTRUSTED_FORCED = {
    "PROJ_NETWORK": "OFF",
    "GDAL_HTTP_PROXY": "127.0.0.1:9",
    "GDAL_HTTPS_PROXY": "127.0.0.1:9",
    "GDAL_HTTP_TIMEOUT": "1",
    "GDAL_HTTP_CONNECTTIMEOUT": "1",
    "GDAL_HTTP_MAX_RETRY": "0",
    "GDAL_HTTP_NETRC": "NO",
    "GDAL_PAM_ENABLED": "NO",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "GDAL_SKIP": " ".join(SKIPPED_GDAL_DRIVERS),
    "GDAL_CACHEMAX": str(GDAL_CACHE_MB),
}
# Files are the user's alone, also what a child writes.
UNTRUSTED_UMASK = 0o077

# <host>_<pid>_<token>; the host part has no "_" (see ``_host``).
_WORK_NAME = re.compile(
    r"(?P<host>[^_]+)_(?P<pid>[1-9][0-9]{0,9})_(?P<token>[0-9a-f]+)"
)
_HOST_UNSAFE = re.compile(r"[^A-Za-z0-9.-]")
_work_dirs: dict[tuple[Path, int], Path] = {}
_work_lock = threading.Lock()

logger = logging.getLogger(__name__)


def untrusted_env() -> dict[str, str]:
    """Return the environment of a process reading untrusted files.

    Returns
    -------
    dict[str, str]
        The allowed variables of this process (``UNTRUSTED_INHERITED``,
        ``UNTRUSTED_INHERITED_PREFIXES``) and the forced ones
        (``UNTRUSTED_FORCED``), which win.
    """
    kept = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in UNTRUSTED_INHERITED
        or name.upper().startswith(UNTRUSTED_INHERITED_PREFIXES)
    }
    return {**kept, **UNTRUSTED_FORCED}


def child_limits(memory_bytes: int | None = None) -> dict[str, Any]:
    """Return the ``subprocess.Popen`` arguments limiting a child.

    The child gets its own session (``kill_untrusted`` ends it with all
    its descendants) and ``umask 077``. On Windows only its own process
    group (limits there come with v1.0).

    Parameters
    ----------
    memory_bytes : int or None, optional
        Address space of the child (``RLIMIT_AS``, POSIX), set before it
        starts; ``None`` keeps the inherited limit.

    Returns
    -------
    dict[str, Any]
        Keyword arguments for ``subprocess.Popen``.
    """
    if sys.platform == "win32":  # pragma: no cover - Windows (v1.0)
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    limits: dict[str, Any] = {"start_new_session": True, "umask": UNTRUSTED_UMASK}
    if memory_bytes is not None:
        # Runs between fork and exec: one system call, no lock taken.
        limits["preexec_fn"] = functools.partial(_limit_memory, memory_bytes)
    return limits


def run_untrusted(
    argv: Sequence[str],
    *,
    timeout_s: float,
    memory_bytes: int | None = None,
    input: bytes | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run a process reading untrusted files with the sandbox, to its end.

    Its standard error is discarded (library messages may name paths).

    Parameters
    ----------
    argv : Sequence[str]
        The command.
    timeout_s : float
        Wall-clock seconds after which the process and its group are killed.
    memory_bytes : int or None, optional
        Address-space limit of the process (see ``child_limits``).
    input : bytes or None, optional
        Written to the standard input, then closed; without it the
        standard input is empty.
    cwd : Path or None, optional
        Working directory of the process.

    Returns
    -------
    subprocess.CompletedProcess[bytes]
        The exit code and the standard output.

    Raises
    ------
    subprocess.TimeoutExpired
        The process ran longer than ``timeout_s``; it is killed and reaped.
    """
    process = subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=cwd,
        env=untrusted_env(),
        **child_limits(memory_bytes),
    )
    try:
        output, _ = process.communicate(input, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        kill_untrusted(process)
        process.communicate()
        raise
    except BaseException:
        kill_untrusted(process)
        process.wait()
        raise
    return subprocess.CompletedProcess(process.args, process.returncode, output)


def kill_untrusted(process: subprocess.Popen[Any]) -> None:
    """Kill a child started with ``child_limits`` and its whole group."""
    if process.poll() is not None:
        return
    if sys.platform == "win32":  # pragma: no cover - Windows
        process.kill()
        return
    with contextlib.suppress(ProcessLookupError):  # ended in the meantime
        os.killpg(process.pid, signal.SIGKILL)


def process_work_dir(paths: AppPaths) -> Path:
    """Return this process's scratch directory, created on the first call.

    ``<data_dir>/work/<host>_<pid>_<token>/`` (mode ``0700``) is the
    process's own: consistent copies of SQLite files and other temporary
    files of one read. Creating it removes the directories of this host's
    dead processes (a crashed or killed reader), never those of a live
    process or of another host, so a command line and the server running
    side by side keep their files.

    Parameters
    ----------
    paths : AppPaths
        Local application data (``AppPaths.work_dir``).

    Returns
    -------
    Path
        The directory; the same one on every call of this process.
    """
    root = paths.work_dir
    key = (root, os.getpid())
    with _work_lock:
        found = _work_dirs.get(key)
        if found is not None and found.is_dir():
            return found
        private_directory(root)
        _prune_dead(root)
        directory = root / f"{_host()}_{os.getpid()}_{secrets.token_hex(8)}"
        directory.mkdir(mode=0o700)
        _work_dirs[key] = directory
        return directory


def _prune_dead(root: Path) -> None:
    """Remove the work directories of this host's processes no longer running."""
    host = _host()
    try:
        with os.scandir(root) as entries:
            found = [(entry.name, entry.path) for entry in entries]
    except OSError as error:
        logger.warning("cannot list the work directories in %s: %s", root, error)
        return
    for name, path in found:
        match = _WORK_NAME.fullmatch(name)
        if match is None or match["host"] != host or _alive(int(match["pid"])):
            continue
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
        except FileNotFoundError:  # another process pruned it first
            continue
        except OSError as error:
            logger.warning("cannot remove the work directory %s: %s", path, error)


def _alive(pid: int) -> bool:
    """Whether a process of this host may still run; kept when unsure."""
    if sys.platform == "win32":  # pragma: no cover - Windows (v1.0)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):  # another user's process; unsure
        return True
    return True


def _host() -> str:
    """Return this computer's name as written in work directory names."""
    return _HOST_UNSAFE.sub("-", socket.gethostname()) or "host"


def _limit_memory(memory_bytes: int) -> None:  # pragma: no cover - in the child
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
