"""Run ``archiwista serve`` on a free port in a background thread."""

import io
import queue
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from archiwista.config import AppPaths
from archiwista.server import LocalServer, serve_main
from archiwista.sources import SourceState

START_TIMEOUT_S = 10.0


class NoSources:
    """Plugin registry without producers, enough for a server without stores."""

    def states(self) -> tuple[SourceState, ...]:
        """Return no plugin states."""
        return ()

    def probe(self, producer: str, root: Path) -> SourceState:
        """Report every producer as not installed."""
        return SourceState(producer=producer, status="not_installed")


def local_paths(tmp_path: Path) -> AppPaths:
    """Place configuration and local data inside the test directory."""
    return AppPaths(
        config_file=tmp_path / "config" / "config.toml",
        data_dir=tmp_path / "data",
    )


@contextmanager
def serving(
    paths: AppPaths, *, access_log: bool = False
) -> Iterator[tuple[LocalServer, str]]:
    """Run ``serve_main`` on a free port; yield the server and what it printed.

    The server stops when the block ends and must then exit with status 0.
    """
    out = io.StringIO()
    err = io.StringIO()
    ready: queue.Queue[LocalServer] = queue.Queue()
    statuses: list[int] = []

    def run() -> None:
        statuses.append(
            serve_main(
                paths,
                NoSources(),
                out,
                err,
                port=0,
                access_log=access_log,
                on_ready=ready.put,
            )
        )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + START_TIMEOUT_S
    while True:
        try:
            server = ready.get(timeout=0.05)
            break
        except queue.Empty:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise AssertionError(f"serve did not start: {err.getvalue()}") from None
    try:
        yield server, out.getvalue()
    finally:
        server.stop()
        thread.join(timeout=START_TIMEOUT_S)
    assert not thread.is_alive()
    assert statuses == [0], err.getvalue()
