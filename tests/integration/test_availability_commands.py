"""The producer's commands of an availability set and its products (ADR-035).

A row of ``GET /availability`` is planned from the producer's own command
lines (Kartograf's ``download_hint``): each variant names them by format,
``POST /commands/parse`` reads each line into a call, and ``POST /jobs`` checks
all the calls of the row in one job (ADR-044). ``GET /sources`` names the
products whose availability a producer checks. The stand-in producer
(``tests/fixtures/action_source``) reports three sets: two of 2023 with the
line that fetches one station's files, and 2022 with three such lines.
"""

from pathlib import Path
from types import ModuleType
from urllib.parse import urlencode

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths
from archiwista.index import IndexWriter
from archiwista.sources import AvailabilityReport
from archiwista.sources.registry import load_registry
from tests.fixtures.actions import (
    STORE,
    action_paths,
    action_supervisor,
    standin_in_settings,
)
from tests.fixtures.api_session import running_api
from tests.fixtures.availability import AREA, PARAMS, register_standin
from tests.fixtures.jobs import worker_path

JOB_TIMEOUT_S = 90.0


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers, in every store's settings."""
    worker_path(monkeypatch)
    module = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    return module


@pytest.fixture
def paths(tmp_path: Path, standin: ModuleType) -> AppPaths:
    """Return an installation with the stand-in's store and the area ``AREA``."""
    created = action_paths(tmp_path)
    with IndexWriter(created.index_file) as writer:
        writer.write_area(AREA)
    return created


def test_a_rows_command_lines_read_into_one_check_of_the_store(
    paths: AppPaths,
) -> None:
    """Each variant names its lines by format; a row's lines start one check."""
    with action_supervisor(paths) as jobs:
        registry = load_registry(cache_dir=paths.cache_dir)
        with running_api(paths, registry, jobs=jobs) as api:
            owner = api.session(LOCAL_OWNER)
            asked = owner.request("POST", "/availability", json={**PARAMS})
            jobs.wait(asked.json()["id"], timeout=JOB_TIMEOUT_S)
            query = urlencode({**PARAMS, "store": STORE})
            kept = owner.request("GET", f"/availability?{query}")
            variants = [row["variants"] for row in kept.json()["rows"]]

            # Act
            lines = variants[1][0]["commands"]["ASC"]
            calls = [
                owner.request(
                    "POST",
                    "/commands/parse",
                    json={"producer": "standin", "line": line},
                ).json()
                for line in lines
            ]
            started = owner.request(
                "POST",
                "/jobs",
                json={
                    "kind": "check",
                    "producer": "standin",
                    "store": STORE,
                    "calls": [
                        {"command": call["command"], "options": call["options"]}
                        for call in calls
                    ],
                },
            )
            listed = [job.kind for job in jobs.list().items]

    # Assert: 2023 shows PL-2000 (one campaign) first, PL-1992 is "+1 variant".
    stations = ("150160200", "150160210", "150160220")
    assert [[variant["commands"] for variant in row] for row in variants] == [
        [
            {"ASC": ["series fetch --station 150160190 --kind hydro"]},
            {"ASC": ["series fetch --station 150160180 --kind hydro"]},
        ],
        [{"ASC": [f"series fetch --station {code} --kind hydro" for code in stations]}],
    ]
    assert kept.json()["report"]["combinations"][2]["commands"] == lines
    assert started.status_code == 202, started.text
    assert started.json()["params"]["calls"] == [
        {"command": "series fetch", "options": {"station": code, "kind": "hydro"}}
        for code in stations
    ]
    assert listed == ["check", "availability"]


def test_a_report_kept_before_commands_reads_with_none(paths: AppPaths) -> None:
    """A combination of an older kept report has no command lines, no error."""
    report = AvailabilityReport.from_json(
        {
            "producer": "standin",
            "schema": "standin-availability/1",
            "checked_at": "2026-10-25T08:00:00+00:00",
            "request": {"product": "dem"},
            "areas": [],
            "combinations": [
                {
                    "country": "PL",
                    "product": "dem",
                    "source": "standin_dem",
                    "year": 2023,
                    "horizontal": "PL-2000",
                    "resolution": "1m",
                    "vertical_crs": "EVRF2007",
                    "format": "ASC",
                    "campaigns": ["C"],
                    "complete": True,
                    "sheets_full": ["T1"],
                    "sheets_partial": [],
                    "sheets_missing": [],
                    "uncovered_m2": 0.0,
                    "full_m2": 1.0,
                    "size_bytes": None,
                    "published": None,
                    "sheet_records": [],
                    "campaign_coverage": [],
                }
            ],
            "failed": [],
            "notices": [],
            "ok": True,
        }
    )

    assert report.combinations[0].commands == ()
    assert AvailabilityReport.from_json(report.to_json()) == report


def test_sources_name_the_products_each_producer_checks(paths: AppPaths) -> None:
    """The stand-in checks `dem`; Kartograf its elevation products."""
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        listed = api.session(LOCAL_OWNER).request("GET", "/sources").json()["items"]
    products = {item["producer"]: item["availability"] for item in listed}

    assert products["standin"] == ["dem"]
    assert {"nmt", "nmpt", "laz"} <= set(products["kartograf"])
