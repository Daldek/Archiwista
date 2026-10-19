"""The real ``archiwista serve`` where a directory is bind-mounted read-only.

An unprivileged user and mount namespace (``unshare``) binds a directory
onto itself read-only and executes the console script installed next to the
interpreter; the network namespace is shared, so a browser reaches the
server. ``tree`` records a directory's names, sizes, modification times and
inodes, so a test can show that nothing was written below it.
"""

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

type Snapshot = dict[str, tuple[int, int, int]]

SERVE_URL = re.compile(r"http://127\.0\.0\.1:\d+/#token=\S+")
START_TIMEOUT_S = 30.0
STOP_TIMEOUT_S = 30.0


def tree(directory: Path) -> Snapshot:
    """Return every name below ``directory`` with its size, mtime and inode."""
    found = {}
    for top, dirnames, filenames in os.walk(directory):
        for name in [*dirnames, *filenames]:
            info = os.lstat(os.path.join(top, name))
            found[os.path.relpath(os.path.join(top, name), directory)] = (
                info.st_size,
                info.st_mtime_ns,
                info.st_ino,
            )
    return found


def require_read_only_mounts(tmp_path: Path) -> None:
    """Skip unless an unprivileged mount namespace makes a directory read-only."""
    if shutil.which("unshare") is None:
        pytest.skip("unshare (util-linux) is not installed")
    probe = tmp_path / "probe"
    probe.mkdir()
    where = shlex.quote(str(probe))
    script = (
        f"mount --bind {where} {where} && mount -o remount,bind,ro {where}"
        f" && ! touch {where}/written 2>/dev/null"
    )
    done = subprocess.run(
        ["unshare", "--user", "--map-root-user", "--mount", "sh", "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    shutil.rmtree(probe)
    if done.returncode != 0:
        reason = done.stderr.strip() or f"exit status {done.returncode}"
        pytest.skip(f"no read-only bind mount in a user namespace: {reason}")


def mount_options(pid: int, mount_point: Path) -> list[str]:
    """Return the options of the mount at ``mount_point`` as process ``pid`` sees it."""
    found = [
        fields[5].split(",")
        for fields in (
            line.split(" ")
            for line in Path(f"/proc/{pid}/mountinfo").read_text().splitlines()
        )
        if fields[4] == str(mount_point)
    ]
    assert found, f"no mount at {mount_point} in process {pid}"
    return found[-1]


@contextmanager
def serving_read_only(
    directory: Path, env: dict[str, str], logs: Path
) -> Iterator[tuple["subprocess.Popen[bytes]", str]]:
    """Run ``archiwista serve`` where ``directory`` is mounted read-only.

    Yields the process and the one-time address it printed (its output in
    ``logs``); afterwards the server gets ``SIGINT`` (Ctrl+C) and must stop
    by itself.
    """
    console = Path(sys.executable).with_name("archiwista")
    where = shlex.quote(str(directory))
    script = (
        f"mount --bind {where} {where} && mount -o remount,bind,ro {where}"
        f" && exec {shlex.quote(str(console))} serve --no-browser --port 0"
    )
    out, err = logs / "serve.out", logs / "serve.err"
    with out.open("wb") as stdout, err.open("wb") as stderr:
        process = subprocess.Popen(
            ["unshare", "--user", "--map-root-user", "--mount", "sh", "-c", script],
            stdout=stdout,
            stderr=stderr,
            env=env,
        )
        try:
            deadline = time.monotonic() + START_TIMEOUT_S
            while (found := SERVE_URL.search(out.read_text(encoding="utf-8"))) is None:
                assert process.poll() is None, err.read_text(encoding="utf-8")
                assert time.monotonic() < deadline, err.read_text(encoding="utf-8")
                time.sleep(0.1)
            yield process, found[0]
            process.send_signal(signal.SIGINT)
            process.wait(timeout=STOP_TIMEOUT_S)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
