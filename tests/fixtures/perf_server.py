r"""``archiwista serve`` as a person starts it, for the measurements (SPEC 4.5).

The perf modules (``tests/perf/test_store_50k.py``, ``test_previews_perf.py``,
``test_own_data_perf.py``) run the server as its own process over a work
directory (configuration and index there, ``XDG_*_HOME`` pointing into it),
talk to it as an agent with the one-time token it prints, and sample the
memory of the server and of every process it starts. ``Medium`` names the
mount a store lies on, so a report says what was measured: an SSD or a real
SMB share, never a local directory standing for one.
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Self

import httpx
import pytest

from archiwista.config import AppPaths, AppSettings, ConfigStore
from archiwista.security import CSRF_HEADER

START_TIMEOUT_S = 60.0
FINAL_STATES = frozenset({"succeeded", "failed", "interrupted", "cancelled"})
JOB_WORKER = "archiwista.jobs.worker"
RENDER_WORKER = "archiwista.previews.worker"
# Only the render pool's processes have it; a build process has not.
POOL_FLAG = "--previews-dir"
_SERVE_URL = re.compile(r"http://127\.0\.0\.1:(\d+)/#token=(\S+)")


@dataclass(frozen=True)
class Medium:
    """The mount holding a path, as ``/proc/self/mountinfo`` names it."""

    mount_point: str
    filesystem: str
    source: str
    options: str
    rotational: bool | None

    @classmethod
    def of(cls, path: Path) -> Self:
        """Return the deepest mount containing ``path``."""
        target = Path(os.path.realpath(path))
        best: tuple[int, Self] | None = None
        with open("/proc/self/mountinfo", encoding="utf-8") as table:
            for line in table:
                fields, _, rest = line.rstrip("\n").partition(" - ")
                parts = fields.split(" ")
                mount_point = Path(parts[4].replace("\\040", " "))
                if not target.is_relative_to(mount_point):
                    continue
                filesystem, source, options = (rest.split(" ") + ["", "", ""])[:3]
                depth = len(mount_point.parts)
                if best is None or depth >= best[0]:
                    found = cls(
                        str(mount_point),
                        filesystem,
                        source,
                        f"{parts[5]} {options}",
                        _rotational(source),
                    )
                    best = (depth, found)
        assert best is not None, path
        return best[1]

    @property
    def share(self) -> bool:
        """Whether the mount is an SMB share."""
        return self.filesystem in ("cifs", "smb3")

    def describe(self) -> str:
        """Return the mount for a report line."""
        return (
            f"{self.filesystem} {self.source} at {self.mount_point}"
            f" ({self.options}; rotational {self.rotational})"
        )


def _rotational(source: str) -> bool | None:
    """Whether a block device (or the disk of a partition) spins."""
    device = Path("/sys/class/block") / Path(source).name
    if not source.startswith("/dev/") or not device.exists():
        return None
    for queue in (device / "queue", device.resolve().parent / "queue"):
        flag = queue / "rotational"
        if flag.exists():
            return flag.read_text(encoding="ascii").strip() == "1"
    return None


def p95(samples: list[float]) -> float:
    """Return the 95th percentile: the 38th of 40 sorted samples."""
    ordered = sorted(samples)
    return ordered[int(0.95 * (len(ordered) - 1))]


def frame_rate(times: list[float]) -> tuple[float, float]:
    """Return frames per second and the p95 of a frame (ms) of frame times (ms)."""
    intervals = [b - a for a, b in zip(times, times[1:], strict=False)]
    return 1000 * len(intervals) / (times[-1] - times[0]), p95(intervals)


def job_seconds(job: dict[str, Any]) -> float:
    """Return how long a job ran: ``finished_at`` - ``started_at``."""
    started = datetime.fromisoformat(job["started_at"])
    finished = datetime.fromisoformat(job["finished_at"])
    return (finished - started).total_seconds()


def load() -> str:
    """Return the load averages of the computer, for a report line."""
    one, five, fifteen = os.getloadavg()
    return f"load average {one:.2f} {five:.2f} {fifteen:.2f}"


def memory_status(pid: int) -> dict[str, int] | None:
    """Memory lines of ``/proc/<pid>/status`` in KiB; ``None`` once it is gone."""
    try:
        with open(f"/proc/{pid}/status", encoding="ascii") as status:
            fields = dict(line.split(":", 1) for line in status)
    except (OSError, ValueError):
        return None
    names = ("VmHWM", "VmRSS", "RssAnon", "RssFile")
    if not all(name in fields for name in names):
        return None
    return {name: int(fields[name].split()[0]) for name in names}


def descendants(pid: int) -> list[int]:
    """Return the processes a process started, and theirs, while they run."""
    found: list[int] = []
    try:
        tasks = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return found
    for task in tasks:
        try:
            with open(f"/proc/{pid}/task/{task}/children", encoding="ascii") as text:
                children = [int(item) for item in text.read().split()]
        except OSError:
            continue
        for child in children:
            found += [child, *descendants(child)]
    return found


def command_line(pid: int) -> str:
    """Return a process's command line, empty once it is gone."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as text:
            return text.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


@dataclass
class Peak:
    """The highest memory a process was seen with."""

    command: str
    hwm_kib: int = 0
    anon_kib: int = 0


class MemorySampler:
    """Peak memory of a process and of each process it starts, every 50 ms."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.peaks: dict[int, Peak] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def __enter__(self) -> Self:
        """Start sampling."""
        self._thread.start()
        return self

    def __exit__(self, *details: object) -> None:
        """Stop sampling; the peaks stay."""
        self._stop.set()
        self._thread.join()

    def matching(self, *parts: str, without: str | None = None) -> list[Peak]:
        """Peaks of the started processes whose command has every part."""
        return [
            peak
            for pid, peak in self.peaks.items()
            if pid != self.pid
            and all(part in peak.command for part in parts)
            and (without is None or without not in peak.command)
        ]

    def _sample(self) -> None:
        while not self._stop.wait(0.05):
            for pid in [self.pid, *descendants(self.pid)]:
                status = memory_status(pid)
                if status is None:
                    continue
                peak = self.peaks.get(pid)
                if peak is None:
                    peak = self.peaks[pid] = Peak(command_line(pid))
                peak.hwm_kib = max(peak.hwm_kib, status["VmHWM"])
                peak.anon_kib = max(peak.anon_kib, status["RssAnon"])


@dataclass
class ServerProcess:
    """A running ``archiwista serve`` and a session of an agent with it."""

    process: subprocess.Popen[bytes]
    client: httpx.Client
    memory: MemorySampler
    paths: AppPaths

    @property
    def base(self) -> str:
        """The server's address."""
        return str(self.client.base_url).rstrip("/")

    def get(self, path: str, **params: str | int | float) -> Any:
        """Read ``/api/v1`` with the session; require 200."""
        response = self.client.get(f"/api/v1{path}", params=params or None)
        assert response.status_code == 200, (path, response.text)
        return response.json()

    def post(self, path: str, body: object) -> Any:
        """Change something with the session's CSRF token."""
        response = self.client.post(f"/api/v1{path}", json=body)
        assert response.status_code in (200, 201, 202), (path, response.text)
        return response.json()

    def wait(self, job_id: str, timeout_s: float, *, poll_s: float = 0.5) -> Any:
        """Wait for a job to end and return it."""
        deadline = time.monotonic() + timeout_s
        while True:
            job = self.get(f"/jobs/{job_id}")
            if job["state"] in FINAL_STATES:
                return job
            assert time.monotonic() < deadline, job
            time.sleep(poll_s)

    def jobs(self, **filters: str) -> list[dict[str, Any]]:
        """Return every job of the filters, page after page."""
        found: list[dict[str, Any]] = []
        params: dict[str, str | int] = {"limit": 200, **filters}
        while True:
            page = self.get("/jobs", **params)
            found += page["items"]
            if page["next_cursor"] is None:
                return found
            params["cursor"] = page["next_cursor"]

    def wait_previews(self, timeout_s: float) -> list[dict[str, Any]]:
        """Wait until no ``preview`` job waits or runs; return all of them."""
        deadline = time.monotonic() + timeout_s
        while any(self.jobs(kind="preview", state=state) for state in BUSY_STATES):
            assert time.monotonic() < deadline, "preview jobs did not end"
            time.sleep(1.0)
        return self.jobs(kind="preview")

    def index_bytes(self) -> int:
        """Size of the index with its write-ahead log."""
        return sum(
            item.stat().st_size
            for item in self.paths.data_dir.glob("index.sqlite*")
            if item.is_file()
        )

    def previews_bytes(self) -> int:
        """Size of the preview cache: every file under ``previews/``."""
        return sum(
            item.stat().st_size
            for item in self.paths.previews_dir.rglob("*")
            if item.is_file()
        )


BUSY_STATES = ("queued", "running")


def refuse_coverage() -> None:
    """Fail when coverage traces this run: its tracing would be measured too."""
    coverage = sys.modules.get("coverage")
    if coverage is not None and coverage.Coverage.current() is not None:
        pytest.fail("run with --no-cov: coverage tracing would be measured too")


def serve_paths(work: Path) -> AppPaths:
    """Where ``archiwista serve`` with ``XDG_*_HOME`` in ``work`` keeps its data."""
    return AppPaths(
        config_file=work / "config" / "archiwista" / "config.toml",
        data_dir=work / "data" / "archiwista",
    )


@contextmanager
def serve_process(work: Path, settings: AppSettings) -> Iterator[ServerProcess]:
    """Start ``archiwista serve`` over ``work`` with ``settings``; stop it after.

    Its output goes to ``work/serve.out`` and ``work/serve.err``; it must end
    with status 0 at SIGINT.
    """
    paths = serve_paths(work)
    ConfigStore(paths.config_file).save(settings)
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(work / "config"),
        "XDG_DATA_HOME": str(work / "data"),
    }
    out = work / "serve.out"
    with out.open("wb") as stdout, (work / "serve.err").open("wb") as stderr:
        process = subprocess.Popen(
            [
                str(Path(sys.executable).with_name("archiwista")),
                "serve",
                "--no-browser",
                "--port",
                "0",
            ],
            env=env,
            stdout=stdout,
            stderr=stderr,
        )
    try:
        deadline = time.monotonic() + START_TIMEOUT_S
        while (found := _SERVE_URL.search(out.read_text(encoding="utf-8"))) is None:
            assert process.poll() is None, (work / "serve.err").read_text("utf-8")
            assert time.monotonic() < deadline, "the server did not start"
            time.sleep(0.1)
        with (
            closing(_agent_session(found)) as client,
            MemorySampler(process.pid) as memory,
        ):
            yield ServerProcess(process, client, memory, paths)
    finally:
        assert _stop(process) == 0, (work / "serve.err").read_text("utf-8")


def _agent_session(found: re.Match[str]) -> httpx.Client:
    """Exchange the one-time token of the address for a session (as an agent)."""
    client = httpx.Client(base_url=f"http://127.0.0.1:{found[1]}", timeout=120.0)
    answer = client.post("/api/v1/session", json={"token": found[2]})
    assert answer.status_code == 200, answer.text
    # Every request of the session carries its CSRF token (SPEC 10.1).
    client.headers[CSRF_HEADER] = answer.json()["csrf_token"]
    return client


def _stop(process: subprocess.Popen[bytes]) -> int:
    process.send_signal(signal.SIGINT)
    try:
        return process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()
