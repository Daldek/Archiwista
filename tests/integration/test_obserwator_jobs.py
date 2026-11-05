"""Obserwator's commands as jobs, and a project's IMGW pins (plan 2026-11-05, P2).

Real job workers run Obserwator's ``check_command`` and ``run_command`` with
IMGW-PIB stood in for by Obserwator's own fixture archives
(``tests.fixtures.obserwator_worker``): a ``check`` job plans ``store sync``
of ``pl.imgw.hydro_daily`` 2023 and 2024 into the empty Obserwator directory
of the store ``zespol``, a ``download`` of that plan pins its files into
Olga's project, and the index reads the whole store again (Obserwator reads
no part of it), so the station series are there when the job ends. The
project then checks, restores and re-pins those pins by the calls Obserwator
rebuilds of each version (A-ADR-049 D5).
"""

import json
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.jobs import JobSupervisor
from archiwista.projects import PROJECT_FILE
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Api, Caller, running_api
from tests.fixtures.jobs import worker_path
from tests.fixtures.obserwator_worker import ETAGS_ENV, OBSERWATOR_WORKER
from tests.fixtures.permissions import add_people, principal, share

JOB_TIMEOUT_S = 90.0
STORE = "zespol"
HYDRO = "pl.imgw.hydro_daily"
CALL = {
    "command": "store sync",
    "options": {"datasets": [HYDRO], "years": [2023, 2024]},
}
SLOT_2023 = "archives/versions/dane_hydrologiczne/dobowe/2023/codz_2023"
SLOT_2024 = "archives/versions/dane_hydrologiczne/dobowe/2024/codz_2024"
SERIES = "series/versions/hydro_daily"
GROUP = "IMGW"
# A station of the fixture archives (fictional codes, Obserwator's fixtures).
STATION = "149190310"


@dataclass(frozen=True)
class Place:
    """A served installation with an Obserwator store and Olga's project."""

    api: Api
    jobs: JobSupervisor
    paths: AppPaths
    root: Path
    directory: Path
    project: str
    owner: Caller
    etags: Path


@pytest.fixture
def place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Place]:
    """Serve the store ``zespol`` (an empty Obserwator directory) and a project."""
    worker_path(monkeypatch)
    etags = tmp_path / "etags.json"
    monkeypatch.setenv(ETAGS_ENV, str(etags))
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    root = tmp_path / "obserwator"
    root.mkdir()
    projects = tmp_path / "projekty"
    projects.mkdir()
    store = StoreConfig(id=STORE, name="Zespół", obserwator=root, kind="local")
    ConfigStore(paths.config_file).save(
        AppSettings(stores=(store,), project_dirs=(projects,), store_write_for_all=True)
    )
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    with (
        JobSupervisor(paths, settings, worker_command=OBSERWATOR_WORKER) as jobs,
        running_api(paths, registry, jobs=jobs) as api,
    ):
        add_people(api.state)
        owner = api.session(principal(api.state, "owner"))
        directory = projects / "raba"
        created = owner.request("POST", "/projects", json={"path": str(directory)})
        assert created.status_code == 201, created.text
        share(api.state, access_key(directory), "public")
        yield Place(
            api,
            jobs,
            paths,
            root,
            directory,
            created.json()["project"],
            owner,
            etags,
        )


def _wait(place: Place, job_id: str) -> dict[str, Any]:
    place.jobs.wait(job_id, timeout=JOB_TIMEOUT_S)
    detail: dict[str, Any] = place.owner.request("GET", f"/jobs/{job_id}").json()
    return detail


def _start(place: Place, path: str, body: dict[str, Any]) -> dict[str, Any]:
    started = place.owner.request("POST", path, json=body)
    assert started.status_code == 202, started.text
    return _wait(place, started.json()["id"])


def _planned(
    place: Place, call: dict[str, Any], pin: dict[str, str] | None = None
) -> dict[str, Any]:
    """Plan a call, then run the plan (as the plan window does); pin if asked."""
    body = {"store": STORE, "producer": "obserwator", "calls": [call]}
    checked = _start(place, "/jobs", {"kind": "check", **body})
    assert checked["state"] in ("succeeded", "partial"), checked
    run = {"kind": "download", **body, "plan_job": checked["id"]}
    return _start(place, "/jobs", run if pin is None else {**run, "pin": pin})


def _downloaded(place: Place) -> dict[str, Any]:
    """Fetch the station catalog, then plan the sync and pin it into ``IMGW``."""
    catalog = _start(
        place,
        "/jobs",
        {
            "kind": "download",
            "store": STORE,
            "producer": "obserwator",
            "calls": [{"command": "store catalog", "options": {}}],
        },
    )
    assert catalog["state"] == "succeeded", catalog
    return _planned(place, CALL, {"project": place.project, "group": GROUP})


def _pins(place: Place) -> dict[str, str]:
    """Return the project's pinned versions by their slot (two levels up)."""
    data = json.loads((place.directory / PROJECT_FILE).read_text(encoding="utf-8"))
    (group,) = data["groups"]
    return {
        str(Path(pin["version"]).parent.parent.as_posix()): pin["version"]
        for pin in group["pins"]
    }


def _states(detail: dict[str, Any]) -> dict[str, str]:
    return {
        str(Path(row["version"]).parent.parent.as_posix()): row["status"]
        for row in detail["result"]["pins"]
    }


def test_obserwator_check_and_download_jobs_pin_and_index_the_series(
    place: Place,
) -> None:
    """A planned download writes the archives and the series, pins and indexes them."""
    # Act
    detail = _downloaded(place)

    # Assert
    assert detail["state"] == "succeeded", detail
    result = detail["result"]
    assert result["producer"] == "obserwator"
    assert result["counts"]["new"] == 3
    assert {file["path"] for file in result["files"]} == {SLOT_2023, SLOT_2024, SERIES}
    assert result["rescanned"] > 0
    assert result["pin"]["written"] is True
    assert set(_pins(place)) == {SLOT_2023, SLOT_2024, SERIES}
    plan = place.owner.request("GET", f"/jobs/{detail['params']['plan_job']}/plan")
    assert plan.status_code == 200, plan.text
    assert not list((place.paths.cache_dir).rglob("obserwator-plan-*.json"))
    series = place.owner.request(
        "GET", f"/stations/{STATION}/series?dataset={HYDRO}&variable=H"
    )
    assert series.status_code == 200, series.text
    assert series.json()["dataset"] == HYDRO


def test_obserwator_project_check_restore_and_repin(place: Place) -> None:
    """The pins are checked by their versions' calls, restored and re-pinned."""
    # Arrange
    assert _downloaded(place)["state"] == "succeeded"

    # Act: every pin is current at the source
    checked = _start(place, f"/projects/{place.project}/jobs", {"kind": "check"})

    # Assert
    assert checked["state"] == "succeeded", checked
    assert set(_states(checked).values()) == {"current"}

    # Arrange: the 2023 archive is gone from the store
    version = _pins(place)[SLOT_2023]
    shutil.rmtree(place.root / Path(version).parent)
    scanned = place.jobs.submit(
        "scan", store=STORE, params={"mode": "full"}, actor=LOCAL_OWNER
    )
    assert place.jobs.wait(scanned.id, timeout=JOB_TIMEOUT_S).state == "succeeded"

    # Act
    restored = _start(place, f"/projects/{place.project}/jobs", {"kind": "restore"})

    # Assert
    assert restored["state"] == "succeeded", restored
    assert (place.root / version).is_file()

    # Arrange: IMGW-PIB republished the 2024 archive (a new signal)
    place.etags.write_text(
        json.dumps({"dane_hydrologiczne/dobowe/2024/codz_2024.zip": '"v2"'}),
        encoding="utf-8",
    )
    reopened = place.owner.request(
        "POST", f"/projects/{place.project}/groups/{GROUP}/reopen"
    )
    assert reopened.status_code == 200, reopened.text

    # Act
    newer = _start(place, f"/projects/{place.project}/jobs", {"kind": "check"})
    repinned = _start(
        place, f"/projects/{place.project}/jobs", {"kind": "repin", "groups": [GROUP]}
    )

    # Assert
    assert _states(newer)[SLOT_2024] == "newer"
    assert repinned["state"] == "succeeded", repinned
    assert repinned["result"]["written"] is True
    assert set(_pins(place)) == {SLOT_2023, SLOT_2024, SERIES}
