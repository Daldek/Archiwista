"""The rows of ``/availability`` and ``archiwista availability`` (plan 2026-10-25, A3).

The stand-in producer's report of the area ``AREA`` is kept, the settings
name the store ``zespol``, and its index holds versions of two of the three
sheets of 2023's PL-2000 set (campaign C). The expected rows are worked out
from the stand-in's report (``tests/fixtures/action_source``): 2023 shows
PL-2000, complete from one campaign, above PL-1992, complete from two; 2022
is partial at 58% with one partial sheet.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.index import IndexWriter
from archiwista.jobs import JobSupervisor
from archiwista.services.commands import actions
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.availability import AREA, PARAMS, area_paths, register_standin
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.index_data import NMT, slot_path, version, write_pass

STORE = "zespol"
QUERY = f"/availability?area_id={AREA.id}&product=dem&producer=standin"


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers; return its producer library."""
    return register_standin(monkeypatch)


@pytest.fixture
def paths(tmp_path: Path, standin: ModuleType) -> AppPaths:
    """Return an installation with the stand-in's report, the store and versions."""
    created = area_paths(tmp_path)
    root = tmp_path / STORE
    root.mkdir()
    store = StoreConfig(id=STORE, name="Zespół", kartograf=root, kind="local")
    ConfigStore(created.config_file).save(AppSettings(stores=(store,)))
    adapter = actions(load_registry(cache_dir=created.cache_dir), "standin")
    report = adapter.availability("dem", area=AREA.geometry, countries=AREA.countries)
    with IndexWriter(created.index_file) as writer:
        writer.write_availability(AREA.id, report, product="dem", job_id=None)
        writer.sync_stores({STORE: {"kartograf": root}})
        write_pass(
            writer,
            [
                version(
                    slot_path(NMT, sheet),
                    "2023-05-01_C",
                    seed,
                    dataset="standin_dem",
                    campaign="C",
                )
                for seed, sheet in enumerate(("T1", "T2"))
            ],
            full=True,
            store=STORE,
        )
    standin.CALLS.clear()
    return created


@contextmanager
def _api(paths: AppPaths) -> Iterator[tuple[Caller, JobSupervisor]]:
    """Serve the API with the store's settings and a supervisor of no network job."""
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    with (
        JobSupervisor(paths, settings, max_network_jobs=0) as jobs,
        running_api(paths, registry, jobs=jobs) as api,
    ):
        yield api.session(LOCAL_OWNER), jobs


def _rows(answer: dict[str, Any]) -> list[tuple[object, ...]]:
    """Return each row's year, label, badge, chip count and variants' systems."""
    return [
        (
            row["year"],
            row["label"],
            None if row["local"] is None else row["local"]["label"],
            row["other_variants"],
            [(item["horizontal"], item["label"]) for item in row["variants"]],
        )
        for row in answer["rows"]
    ]


def test_rows_carry_labels_and_badges_in_the_language_of_the_request(
    paths: AppPaths,
) -> None:
    """2023: PL-2000 "pełne", 2 of 3 sheets held; 2022: 58%, 1 partial sheet."""
    with _api(paths) as (owner, _):
        english = owner.request("GET", f"{QUERY}&store={STORE}").json()
        polish = owner.request(
            "GET", f"{QUERY}&store={STORE}", accept_language="pl"
        ).json()
        unbadged = owner.request("GET", QUERY).json()

    assert _rows(english) == [
        (
            2023,
            "complete",
            "downloaded 2/3",
            1,
            [("PL-2000", "complete"), ("PL-1992", "complete · 2 campaigns")],
        ),
        (
            2022,
            "partial · 58% · 1 partial sheet",
            "not downloaded",
            0,
            [("PL-1992", "partial · 58% · 1 partial sheet")],
        ),
    ]
    assert _rows(polish) == [
        (
            2023,
            "pełne",
            "pobrane 2/3",
            1,
            [("PL-2000", "pełne"), ("PL-1992", "pełne · 2 kampanie")],
        ),
        (
            2022,
            "częściowe · 58% · 1 ark. niepełny",
            "niepobrane",
            0,
            [("PL-1992", "częściowe · 58% · 1 ark. niepełny")],
        ),
    ]
    first = english["rows"][0]
    assert first["local"] == {
        "store": STORE,
        "state": "some",
        "units": 2,
        "of": 3,
        "label": "downloaded 2/3",
    }
    assert first["coverage"]["kind"] == "full"
    assert first["variants"][1]["local"]["state"] == "none"
    assert (english["store"], unbadged["store"]) == (STORE, None)
    assert [row["local"] for row in unbadged["rows"]] == [None, None]


def test_a_fixed_sheet_system_ranks_only_its_variants(paths: AppPaths) -> None:
    """PL-1992 shows 2023 from two campaigns; PL-2000 has no data in 2022."""
    with _api(paths) as (owner, _):
        old = owner.request("GET", f"{QUERY}&horizontal=PL-1992").json()
        new = owner.request("GET", f"{QUERY}&horizontal=PL-2000").json()

    assert [
        (row["year"], row["label"], row["other_variants"]) for row in old["rows"]
    ] == [
        (2023, "complete · 2 campaigns", 0),
        (2022, "partial · 58% · 1 partial sheet", 0),
    ]
    found = [(row["year"], row["label"], len(row["variants"])) for row in new["rows"]]
    assert found == [(2023, "complete", 1), (2022, "no data", 0)]
    assert new["rows"][1]["coverage"]["kind"] == "no_data"
    assert new["variant"] == {
        "horizontal": "PL-2000",
        "resolution": None,
        "vertical_crs": None,
    }


def test_a_store_that_is_not_configured_is_404_before_a_job(
    paths: AppPaths, standin: ModuleType
) -> None:
    """`GET` and `POST` refuse the store; no check starts, the producer is not asked."""
    with _api(paths) as (owner, jobs):
        got = owner.request("GET", f"{QUERY}&store=brak")
        posted = owner.request(
            "POST", "/availability", json={**PARAMS, "store": "brak", "force": True}
        )
        listed = jobs.list().items

    assert_problem(got, 404, "not_found")
    assert_problem(posted, 404, "not_found")
    assert listed == ()
    assert standin.CALLS == []


def _cli(capsys: pytest.CaptureFixture[str], paths: AppPaths, *argv: str) -> Any:
    """Run ``archiwista availability …``; JSON with ``--json``, else the text."""
    capsys.readouterr()
    status = main(
        ["availability", *argv, "--producer", "standin"],
        registry=load_registry(cache_dir=paths.cache_dir),
        paths=paths,
    )
    captured = capsys.readouterr()
    if status != 0:
        return refusal(captured.out, captured.err, status)
    return json.loads(captured.out) if "--json" in argv else captured.out


def test_availability_cli_prints_the_rows_as_http_answers_them(
    paths: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--json` equals `GET`; the Polish text has a line per year; refusals agree."""
    with _api(paths) as (owner, _):
        answered = owner.request("GET", f"{QUERY}&store={STORE}").json()
        refused = owner.request("GET", f"{QUERY}&store=brak")
        printed = _cli(
            capsys,
            paths,
            "show",
            AREA.id,
            "--product",
            "dem",
            "--store",
            STORE,
            "--json",
        )
        text = _cli(
            capsys, paths, "show", AREA.id, "--product", "dem", "--store", STORE
        )
        document = _cli(
            capsys,
            paths,
            "show",
            AREA.id,
            "--product",
            "dem",
            "--store",
            "brak",
            "--json",
        )

    assert printed == answered
    assert text.splitlines()[1:] == [
        "  2023 PL: pełne; wariant PL-2000 · 1m · EVRF2007 · ASC (+1 wariant);"
        " pobrane 2/3",
        "  2022 PL: częściowe · 58% · 1 ark. niepełny; wariant PL-1992 · 1m ·"
        " EVRF2007 · ASC; niepobrane",
    ]
    assert_same_error(document, refused.json())
