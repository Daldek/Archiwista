r"""Criteria 1 and 6 of SPEC 13 v0.3 against the real source (plan A14).

UC-01 live, with one NMT sheet of GUGiK (``N-34-130-D-d-2-4``, 1 m,
EVRF2007) through Archiwista and through Kartograf's own command line, each
into its own store in the test directory:

- criterion 1: the same command run by ``archiwista jobs start download``
  (with the plan of a ``check`` job, as the plan window runs it) and by
  ``kartograf elevation download --root`` gives the same versions, links,
  SHA-256 and sidecars (all but ``downloaded_at``);
- criterion 6: UC-01 (the availability of an area inside the sheet, the plan,
  the download, the store's badge).

The project cases (criterion 2 and UC-06) left with the producers' project
manifests (A-ADR-049); the pins of Archiwista's project file bring their
successors.

Run deliberately, by the author (plan D10). The variable opts in, so the
weekly ``live`` workflow skips the file; the run downloads about 400 MB::

    ARCHIWISTA_LIVE_ACTIONS=1 .venv/bin/python -m pytest -m live \\
        tests/integration/test_live_actions.py --no-cov

Archiwista runs in this process (``archiwista.cli.main``, as the owner of the
installation) with real job workers; Kartograf's command line runs as
``python -m kartograf`` with its metadata cache in the test directory, so the
canary of the producers' default directories stays empty.
"""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import kartograf
import pytest

from archiwista.cli import main
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    StoreConfig,
)
from archiwista.index import IndexQueries, IndexWriter, initialize, scan_store
from archiwista.index.types import AreaRecord, IssueRef
from archiwista.sources.registry import load_registry

pytestmark = pytest.mark.live

OPT_IN = "ARCHIWISTA_LIVE_ACTIONS"
STORE = "zespol"
COMMAND = "elevation download"
SHEET = "N-34-130-D-d-2-4"
LINE = (
    f"kartograf elevation download --product nmt --sheet {SHEET}"
    " --resolution 1m --vertical-crs EVRF2007"
)
# The fixed dimensions of the availability rows: the variant the line takes.
VARIANT = (
    "--horizontal",
    "PL-1992",
    "--resolution",
    "1m",
    "--vertical-crs",
    "EVRF2007",
)
# About 1 km² in the middle of the sheet (its outline in WGS 84 spans 22.967 to
# 23.002 E and 52.375 to 52.396 N).
AREA = AreaRecord(
    id="a14c0de5ee7a0001",
    source="drawn",
    geometry={
        "type": "Polygon",
        "coordinates": [
            [
                [22.978, 52.381],
                [22.991, 52.381],
                [22.991, 52.390],
                [22.978, 52.390],
                [22.978, 52.381],
            ]
        ],
    },
    created_at=datetime(2026, 10, 26, 8, 0, tzinfo=UTC),
    area_km2=0.9,
    countries=("PL",),
    name=f"Arkusz {SHEET}",
)
JOB_TIMEOUT_S = 1800.0
CLI_TIMEOUT_S = 1800.0


@dataclass(frozen=True, slots=True)
class Place:
    """An installation of Archiwista and, beside it, the command line's store."""

    paths: AppPaths
    root: Path
    projects: Path
    cli_root: Path
    cli_env: dict[str, str]


@pytest.fixture
def place(tmp_path: Path) -> Place:
    """Give two empty marked stores: Archiwista's, configured, and the CLI's."""
    if os.environ.get(OPT_IN) != "1":
        pytest.skip(f"{OPT_IN}=1 runs the live actions: about 400 MB from GUGiK")
    root = tmp_path / "archiwista" / "kartograf"
    projects = tmp_path / "archiwista" / "projekty"
    cli_root = tmp_path / "cli" / "kartograf"
    for store in (root, cli_root):
        kartograf.init_store(store)
    projects.mkdir(parents=True)
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    config = StoreConfig(id=STORE, name="Zespół", kartograf=root, kind="local")
    ConfigStore(paths.config_file).save(
        AppSettings(stores=(config,), project_dirs=(projects,))
    )
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
        writer.write_area(AREA)
    cli_env = {**os.environ, "KARTOGRAF_CACHE_DIR": str(tmp_path / "cli-cache")}
    return Place(paths, root, projects, cli_root, cli_env)


def _archiwista(capsys: pytest.CaptureFixture[str], place: Place, *argv: str) -> Any:
    """Run ``archiwista … --json`` in this process; return the model it printed.

    Every command of these journeys succeeds (exit 0): a refusal, or a job
    that does not succeed, fails the test at that step with what it printed.
    """
    capsys.readouterr()
    status = main(
        [*argv, "--json"],
        registry=load_registry(cache_dir=place.paths.cache_dir),
        paths=place.paths,
    )
    captured = capsys.readouterr()
    shown = f"archiwista {' '.join(argv)}: {status}\n{captured.out}\n{captured.err}"
    assert status == 0, shown
    return json.loads(captured.out)


def _kartograf(place: Place, *argv: str) -> subprocess.CompletedProcess[str]:
    """Run Kartograf's command line with its own cache; return how it ended."""
    return subprocess.run(
        [sys.executable, "-m", "kartograf", *argv],
        capture_output=True,
        text=True,
        env=place.cli_env,
        timeout=CLI_TIMEOUT_S,
        check=False,
    )


def _succeeded(ran: subprocess.CompletedProcess[str]) -> None:
    """Fail with what Kartograf printed unless it exited 0."""
    assert ran.returncode == 0, (
        f"{ran.args}: {ran.returncode}\n{ran.stdout}\n{ran.stderr}"
    )


def _options(capsys: pytest.CaptureFixture[str], place: Place, line: str) -> str:
    """Return the options of a pasted line, as Archiwista parses it, as JSON."""
    parsed = _archiwista(capsys, place, "commands", "parse", "kartograf", line)
    assert parsed["command"] == COMMAND
    assert parsed["options"] == kartograf.parse_command(line).options
    return json.dumps(parsed["options"])


def _below(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar(version: Path) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(
        Path(f"{version}.meta.json").read_text(encoding="utf-8")
    )
    return found


def _entries(root: Path) -> dict[tuple[str, str], tuple[str | None, str | None]]:
    """Return every entry Kartograf reads in a store: its version and problem."""
    return {
        (entry.kind, _below(entry.path, root)): (
            None if entry.version_path is None else _below(entry.version_path, root),
            entry.problem,
        )
        for entry in kartograf.iter_store(root)
    }


def _versions(root: Path) -> dict[str, tuple[str, dict[str, Any]]]:
    """Return each version's SHA-256 and its sidecar without ``downloaded_at``."""
    found = {}
    for entry in kartograf.iter_store(root):
        if entry.kind == "version":
            sidecar = _sidecar(entry.path)
            del sidecar["downloaded_at"]
            found[_below(entry.path, root)] = (_sha256(entry.path), sidecar)
    return found


def _partial(root: Path) -> list[str]:
    """Return what a stopped download left: staging, problems, a cut version."""
    left = [_below(path, root) for path in root.rglob(".incoming")]
    for entry in kartograf.iter_store(root):
        if entry.problem is not None:
            left.append(f"{entry.problem}: {_below(entry.path, root)}")
        elif entry.kind == "version":
            sidecar = _sidecar(entry.path)
            held = (_sha256(entry.path), entry.path.stat().st_size)
            if held != (sidecar["sha256"], sidecar["size_bytes"]):
                left.append(f"unlike its sidecar: {_below(entry.path, root)}")
    return left


def _scan_problems(place: Place) -> tuple[IssueRef, ...]:
    """Scan Archiwista's store in full; return the problems the index then holds."""
    settings = ConfigStore(place.paths.config_file).load()
    adapter = load_registry(cache_dir=place.paths.cache_dir).adapter("kartograf")
    with IndexWriter(place.paths.index_file) as writer:
        scan_store(adapter, writer, settings, STORE, mode="full")
    with IndexQueries(place.paths.index_file) as queries:
        return queries.issues(STORE)


def _badges(capsys: pytest.CaptureFixture[str], place: Place) -> list[str]:
    """Return the store's badge of each year of the kept report (no network)."""
    argv = ["availability", "show", AREA.id, "--product", "nmt", "--store", STORE]
    shown = _archiwista(capsys, place, *argv, *VARIANT)
    return [row["local"]["state"] for row in shown["rows"] if row["local"] is not None]


def test_uc01_a_download_through_archiwista_equals_the_command_line(
    place: Place, capsys: pytest.CaptureFixture[str]
) -> None:
    """Availability, plan, download; the same store as Kartograf's command line."""
    # Arrange
    options = _options(capsys, place, LINE)

    # Act: UC-01 in Archiwista: the source's years, the plan, the download.
    asked = ["availability", "check", AREA.id, "--product", "nmt", "--store", STORE]
    report = _archiwista(capsys, place, *asked, *VARIANT, "--force")
    given = json.dumps({"command": COMMAND, "options": json.loads(options)})
    call = ["kartograf", "--store", STORE, "--call", given]
    plan = _archiwista(capsys, place, "jobs", "start", "check", *call)
    after_plan = _entries(place.root)
    download = _archiwista(
        capsys, place, "jobs", "start", "download", *call, "--plan", plan["id"]
    )
    badges = _badges(capsys, place)
    # The same command through Kartograf's command line.
    _succeeded(_kartograf(place, *LINE.split()[1:], "--root", str(place.cli_root)))

    # Assert
    rows = [row for row in report["rows"] if row["year"] is not None]
    assert rows, report
    assert {row["local"]["state"] for row in rows if row["local"] is not None} <= {
        "none"
    }
    assert plan["result"]["counts"]["missing"] >= 1, plan["result"]
    assert after_plan == {}, "the plan wrote the store"
    assert download["result"]["plan_job"] == plan["id"]
    statuses = {file["status"] for file in download["result"]["files"]}
    assert statuses == {"new"}, download["result"]
    assert set(badges) - {"none"}, f"no year shows the download: {badges}"
    # Criterion 1: the same versions, links, SHA-256 and sidecars.
    assert _entries(place.root) == _entries(place.cli_root)
    versions = _versions(place.root)
    assert versions, "no version was downloaded"
    assert versions == _versions(place.cli_root)
    for sha256, sidecar in versions.values():
        assert sidecar["sha256"] == sha256
    assert _partial(place.root) == []
    assert _scan_problems(place) == ()
