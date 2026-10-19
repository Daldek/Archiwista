"""The sandbox of processes reading untrusted files (plan v0.2, decision 3).

Children started by ``run_untrusted`` get no proxy or credential, GDAL and
PROJ stay offline, side files and sibling files are off, VRT drivers are
skipped; a child is limited in memory and killed with its group at its
time limit. Work directories of dead processes go, live ones stay.
"""

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from archiwista.config import AppPaths
from archiwista.sandbox import process_work_dir, run_untrusted

GIB = 1024**3
CHILD_TIMEOUT_S = 60.0
# A child printing its environment, umask and address-space limit, then
# trying to allocate the number of bytes given as its argument.
REPORT = """
import json, os, resource, sys
mask = os.umask(0)
try:
    bytearray(int(sys.argv[1]))
    allocated = True
except MemoryError:
    allocated = False
print(json.dumps({
    "env": dict(os.environ),
    "umask": mask,
    "address_space": resource.getrlimit(resource.RLIMIT_AS)[0],
    "allocated": allocated,
}))
"""
# A child starting a grandchild in its group, writing its pid, then waiting.
STALLING = """
import subprocess, sys, time
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
with open(sys.argv[1], "w") as pid_file:
    pid_file.write(str(grandchild.pid))
time.sleep(120)
"""
_PROXIES = ("http_proxy", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "no_proxy")
_CREDENTIALS = ("AWS_SECRET_ACCESS_KEY", "GDAL_HTTP_USERPWD", "GS_SECRET_ACCESS_KEY")


def _report(*, memory_bytes: int | None = None, allocate: int = 0) -> dict[str, object]:
    finished = run_untrusted(
        [sys.executable, "-c", REPORT, str(allocate)],
        timeout_s=CHILD_TIMEOUT_S,
        memory_bytes=memory_bytes,
    )
    assert finished.returncode == 0
    report: dict[str, object] = json.loads(finished.stdout)
    return report


def _running(pid: int) -> bool:
    """Whether a process exists and is not a zombie (Linux ``/proc``)."""
    try:
        status = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    return status.rpartition(")")[2].split()[0] != "Z"


def test_sandbox_child_env_has_no_proxy_credentials_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proxies and credentials stay behind; GDAL is offline and blind to siblings."""
    # Arrange
    for name in _PROXIES:
        monkeypatch.setenv(name, "http://proxy.example:3128")
    for name in _CREDENTIALS:
        monkeypatch.setenv(name, "secret")
    for name, value in {
        "PROJ_NETWORK": "ON",
        "GDAL_HTTP_PROXY": "proxy.example:3128",
        "GDAL_PAM_ENABLED": "YES",
        "GDAL_SKIP": "",
        "CPL_DEBUG": "ON",
        "ARCHIWISTA_MARKER": "kept",
    }.items():
        monkeypatch.setenv(name, value)

    # Act
    env = _report()["env"]

    # Assert
    assert isinstance(env, dict)
    assert not {name.upper() for name in env} & {
        name.upper() for name in (*_PROXIES, *_CREDENTIALS, "CPL_DEBUG")
    }
    assert env["PROJ_NETWORK"] == "OFF"
    assert env["GDAL_HTTP_PROXY"] == "127.0.0.1:9"
    assert env["GDAL_PAM_ENABLED"] == "NO"
    assert env["GDAL_DISABLE_READDIR_ON_OPEN"] == "EMPTY_DIR"
    assert {"VRT", "OGR_VRT"} <= set(env["GDAL_SKIP"].split())
    assert env["ARCHIWISTA_MARKER"] == "kept"


def test_sandbox_child_memory_limited_and_files_private() -> None:
    """``memory_bytes`` caps the child's address space; its umask is 077."""
    # Act
    limited = _report(memory_bytes=GIB, allocate=2 * GIB)

    # Assert
    assert limited["address_space"] == GIB
    assert limited["allocated"] is False
    assert limited["umask"] == 0o077


def test_sandbox_child_killed_with_its_group_at_time_limit(tmp_path: Path) -> None:
    """Past ``timeout_s`` the child and its own children are killed."""
    # Arrange
    pid_file = tmp_path / "grandchild.pid"
    started = time.monotonic()

    # Act
    with pytest.raises(subprocess.TimeoutExpired):
        run_untrusted([sys.executable, "-c", STALLING, str(pid_file)], timeout_s=3.0)
    elapsed = time.monotonic() - started

    # Assert
    assert elapsed < 30
    grandchild = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 10
    while _running(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _running(grandchild)


def test_process_work_dir_cleanup_keeps_live_processes(tmp_path: Path) -> None:
    """Directories of dead processes of this host go; live and foreign ones stay.

    The process gets its own private directory, the same on every call.
    """
    # Arrange
    elsewhere = AppPaths(config_file=tmp_path / "a.toml", data_dir=tmp_path / "a")
    host = process_work_dir(elsewhere).name.rsplit("_", 2)[0]
    paths = AppPaths(config_file=tmp_path / "b.toml", data_dir=tmp_path / "b")
    ended = subprocess.Popen([sys.executable, "-c", "pass"])
    ended.wait()
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"]
    ) as live:
        try:
            names = {
                "dead": f"{host}_{ended.pid}_0a1b",
                "live": f"{host}_{live.pid}_2c3d",
                "foreign": f"other-host_{ended.pid}_4e5f",
                "unrelated": "notes",
            }
            for name in names.values():
                (paths.work_dir / name).mkdir(parents=True)
                (paths.work_dir / name / "copy.gpkg").write_bytes(b"x")

            # Act
            directory = process_work_dir(paths)
            again = process_work_dir(paths)
        finally:
            live.kill()

    # Assert
    left = sorted(item.name for item in paths.work_dir.iterdir())
    expected = [names["live"], names["foreign"], names["unrelated"], directory.name]
    assert left == sorted(expected)
    assert again == directory
    assert directory.name.startswith(f"{host}_{os.getpid()}_")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
