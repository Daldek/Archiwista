"""Worker process of the job tests: the real worker with test hooks.

A test's ``JobSupervisor`` starts ``python -m tests.fixtures.job_worker``
(``TEST_WORKER`` of ``tests.fixtures.jobs``). The hooks come from the
environment the test sets, which the worker inherits:

``ARCHIWISTA_TEST_ENTRY_DELAY_S``
    Seconds Kartograf's adapter waits before each scanned entry, so a scan
    lasts long enough to be queried, cancelled or interrupted.
``ARCHIWISTA_TEST_CRASH_AFTER``
    The worker kills itself (SIGKILL) after this many scanned entries.
``ARCHIWISTA_TEST_NO_NETWORK``
    Every connection attempt fails and is appended to this file.
``ARCHIWISTA_TEST_PREVIEW_SOURCES``
    JSON file of ``PreviewSource`` objects by ref: the ``preview`` job
    resolves refs ``test:…`` from it and builds with the test renderer
    (``tests.fixtures.render_worker``).
``ARCHIWISTA_TEST_BUILD_PROCESSES``
    Build processes at once of the ``preview`` job. The time limit of a build
    is the file's own instruction ``timeout_s`` (``tests.fixtures.render_worker``),
    so that only the file meant to be too slow can run out of time.
``ARCHIWISTA_TEST_SNAPSHOT_FAULT``
    ``<phase>:<signal>``, e.g. ``rename:SIGKILL``: the worker sends itself
    the signal when a snapshot reaches the phase (``SNAPSHOT_PHASES``).
``ARCHIWISTA_TEST_MISSING_PACKAGES``
    Comma separated distributions that look not installed to the plugin
    registry (``tests.fixtures.missing_package``).
"""

import importlib.metadata
import json
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from archiwista.adapter.kartograf.adapter import KartografAdapter
from archiwista.errors import NotFoundError
from archiwista.jobs import worker
from archiwista.jobs.protocol import JobSpec
from archiwista.owndata import snapshots
from archiwista.owndata.snapshots import SnapshotPhase, SnapshotResult
from archiwista.previews import build
from archiwista.previews.types import PreviewSource
from archiwista.sources import ScanScope, SourceEntry
from tests.fixtures.missing_package import MISSING_PACKAGES_ENV, hiding
from tests.fixtures.render_worker import TEST_RENDER_WORKER

DELAY_ENV = "ARCHIWISTA_TEST_ENTRY_DELAY_S"
CRASH_ENV = "ARCHIWISTA_TEST_CRASH_AFTER"
NO_NETWORK_ENV = "ARCHIWISTA_TEST_NO_NETWORK"
PREVIEW_SOURCES_ENV = "ARCHIWISTA_TEST_PREVIEW_SOURCES"
BUILD_PROCESSES_ENV = "ARCHIWISTA_TEST_BUILD_PROCESSES"
SNAPSHOT_FAULT_ENV = "ARCHIWISTA_TEST_SNAPSHOT_FAULT"


def _hook_entries(delay_s: float, crash_after: int | None) -> None:
    """Slow down the scanned entries, or crash after some of them."""
    real = KartografAdapter.iter_entries
    lock = threading.Lock()
    seen = 0

    def iter_entries(
        self: KartografAdapter, root: Path, *, scope: ScanScope | None = None
    ) -> Iterator[SourceEntry]:
        nonlocal seen
        for entry in real(self, root, scope=scope):
            time.sleep(delay_s)
            with lock:
                seen += 1
                crash = crash_after is not None and seen > crash_after
            if crash:
                os.kill(os.getpid(), signal.SIGKILL)
            yield entry

    KartografAdapter.iter_entries = iter_entries  # type: ignore[method-assign]


def _refuse_network(record: Path) -> None:
    """Fail every connection attempt and note it in ``record``."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        with record.open("a", encoding="utf-8") as file:
            file.write(f"{args!r}\n")
        raise OSError("network disabled by the job tests")

    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign]
    socket.create_connection = refuse
    socket.getaddrinfo = refuse


def _build_timeout(source: PreviewSource) -> float:
    """Return the build's time limit the file's instructions give, else the real one."""
    steps = json.loads(source.paths[0].read_text(encoding="utf-8"))
    return float(steps.get("timeout_s", build.BUILD_TIMEOUT_S))


def _hook_previews(sources: Path) -> None:
    """Resolve ``test:`` refs from ``sources``; build with the test renderer."""
    table = json.loads(sources.read_text(encoding="utf-8"))

    def resolver(spec: JobSpec) -> build.SourceResolver:
        def resolve(ref: str) -> PreviewSource:
            if ref not in table:
                raise NotFoundError(f"no test source {ref}")
            return PreviewSource.from_json(table[ref])

        return resolve

    build.RESOLVERS = {**build.RESOLVERS, "test": resolver}
    build.BUILD_COMMAND = TEST_RENDER_WORKER
    build.build_timeout_s = _build_timeout
    processes = os.environ.get(BUILD_PROCESSES_ENV)
    if processes:
        build.build_processes = lambda: int(processes)


def _hook_snapshots(fault: str) -> None:
    """Send the worker a signal when a snapshot reaches a phase."""
    phase, _, name = fault.partition(":")
    sent = signal.Signals[name]
    real = snapshots.make_snapshot

    def make_snapshot(
        *args: Any,
        on_phase: Callable[[SnapshotPhase], None] | None = None,
        **kwargs: Any,
    ) -> SnapshotResult:
        def reached(done: SnapshotPhase) -> None:
            if on_phase is not None:
                on_phase(done)
            if done == phase:
                os.kill(os.getpid(), sent)

        return real(*args, on_phase=reached, **kwargs)

    worker.make_snapshot = make_snapshot  # type: ignore[attr-defined]


def main() -> int:
    """Arm the hooks named in the environment and run the real worker."""
    delay = float(os.environ.get(DELAY_ENV, "0"))
    crash = os.environ.get(CRASH_ENV)
    if delay or crash:
        _hook_entries(delay, None if crash is None else int(crash))
    record = os.environ.get(NO_NETWORK_ENV)
    if record:
        _refuse_network(Path(record))
    sources = os.environ.get(PREVIEW_SOURCES_ENV)
    if sources:
        _hook_previews(Path(sources))
    fault = os.environ.get(SNAPSHOT_FAULT_ENV)
    if fault:
        _hook_snapshots(fault)
    missing = os.environ.get(MISSING_PACKAGES_ENV)
    if missing:
        importlib.metadata.version = hiding(missing.split(","))  # type: ignore[assignment]
    return worker.main()


if __name__ == "__main__":
    sys.exit(main())
