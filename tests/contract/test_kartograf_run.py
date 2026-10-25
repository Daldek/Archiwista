"""Kartograf's run of a command through the adapter's capability (plan 2026-10-25, A5).

A download needs the network, so ``run_command`` is stood in for with
Kartograf's own classes (``DataReport``, ``UnitFile``, ``VersionedFile``,
``CommandResult``): the call Archiwista makes (``root=``, its metadata cache,
the kept plan as ``update="upgrade"``, never ``output_dir``) and the reading
of ``kartograf-download/1``. The refusal of an invalid call and the scan
scope of every standard path are Kartograf's own answers, without the
network.
"""

from pathlib import Path

import kartograf
import pytest

import archiwista.adapter.kartograf.actions as actions_module
from archiwista.adapter.kartograf import load
from archiwista.errors import BrokenContractError, ProducerError
from archiwista.sources import (
    ActionAdapter,
    ActionFile,
    ActionItem,
    ActionProgress,
    AvailabilityNotice,
    RunStatus,
    SourceAdapter,
    SourceContext,
)
from tests.fixtures.make_store import STORE_DIR, make_store
from tests.fixtures.network import no_network

NMT = {"product": "nmt", "sheet": "N-34-130-D-d-2"}
SEGMENT = "nmt/pl_1992_1m_evrf2007"
SHA = "ab" * 32
STALE_TEXT = "The source changed since the plan was made: make a new plan."


@pytest.fixture
def adapter(tmp_path: Path) -> ActionAdapter:
    """Kartograf adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "kartograf"))
    assert isinstance(created, ActionAdapter)
    return created


def _file(root: Path, sheet: str, status: str, label: str) -> kartograf.UnitFile:
    """Return a file of an NMT sheet as a run of Kartograf reports it."""
    name = f"{sheet}.asc"
    version = root / SEGMENT / "versions" / "N-34" / "130" / f"{label}_abababab"
    return kartograf.UnitFile(
        sheet,
        "PL",
        kartograf.VersionedFile(
            path=root / SEGMENT / "N-34" / "130" / name,
            status=status,  # type: ignore[arg-type]
            label=label,
            sha256=SHA,
            size_bytes=4096,
            version_path=version / name,
        ),
    )


def _stale(sheet: str) -> kartograf.PlanItem:
    """Return a position of a plan whose source changed since the plan."""
    return kartograf.PlanItem(
        track="pl_sheet",
        segment=SEGMENT,
        hierarchy="N-34/130",
        name=f"{sheet}.asc",
        unit=sheet,
        local_label="2021",
        local_sha256=None,
        available_label="2023",
        available_signal=None,
        status="newer",
    )


def _answer(
    root: Path,
    files: tuple[kartograf.UnitFile, ...],
    *,
    failed: tuple[kartograf.UnitFailure, ...] = (),
    stale: tuple[kartograf.PlanItem, ...] = (),
    items: tuple[kartograf.ResultItem, ...] = (),
) -> kartograf.CommandResult[kartograf.DataReport]:
    """Return the envelope of a run of ``elevation download`` in ``root``."""
    report = kartograf.DataReport(
        files=files,
        failed=failed,
        stale=stale,
        superseded=(),
        notices=(kartograf.Notice("info", "sheet_list", "4 sheets"),),
        ok=not failed and not stale,
        root=root,
    )
    status: RunStatus = "ok" if report.ok else "partial"
    return kartograf.CommandResult(
        "elevation download", False, status, report, items=items, notices=report.notices
    )


def test_a_run_writes_the_store_root_with_archiwistas_cache_and_no_plain_files(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``root=`` the store, ``metadata.db`` of the adapter, no plan, no ``output_dir``.

    ``files[]`` come back below the root with Kartograf's statuses (``local``
    is ``unchanged``), ``items[]`` with the code and reason of each failure
    (a stale position: ``conflict``, ``stale_plan``), and the progress counts
    the units of the run: an event about a flight or a transfer keeps them.
    """
    root = tmp_path / "store"
    received: list[dict[str, object]] = []
    failure = kartograf.UnitFailure(
        "N-34-130-D-d-2-4", "PL", "GUGiK did not answer", "download"
    )
    stale = _stale("N-34-130-D-d-2-3")
    files = (
        _file(root, "N-34-130-D-d-2-1", "new", "2023"),
        _file(root, "N-34-130-D-d-2-2", "local", "2021"),
        _file(root, "N-34-130-D-d-2-5", "relabeled", "2023-b"),
    )
    items = (
        kartograf.ResultItem("N-34-130-D-d-2-1", "ok"),
        kartograf.ResultItem("N-34-130-D-d-2-2", "ok"),
        kartograf.ResultItem("N-34-130-D-d-2-5", "ok"),
        kartograf.ResultItem(
            "N-34-130-D-d-2-4", "failed", "source_unavailable", None, failure.error
        ),
        kartograf.ResultItem(
            stale.store_path, "failed", "conflict", "stale_plan", STALE_TEXT
        ),
    )
    events = (
        kartograf.DownloadProgress(0, 1, "Arkusz N-34-130-D-d-2 w 1:10000", "start"),
        kartograf.DownloadProgress(1, 4, "N-34-130-D-d-2-1", "downloading"),
        kartograf.DownloadProgress(1, 2, "N-34-130-D-d-2-1", "campaign", "2023"),
        kartograf.DownloadProgress(2, 4, "N-34-130-D-d-2-1", "completed"),
        kartograf.DownloadProgress(5, 10, "", "tiles"),
    )

    def recording(
        command: str, options: object, **kwargs: object
    ) -> kartograf.CommandResult[kartograf.DataReport]:
        received.append({"command": command, "options": options, **kwargs})
        on_progress, on_notice = kwargs["on_progress"], kwargs["on_notice"]
        assert callable(on_progress) and callable(on_notice)
        for event in events:
            on_progress(event)
        on_notice(kartograf.Notice("info", "sheet_list", "4 sheets"))
        return _answer(root, files, failed=(failure,), stale=(stale,), items=items)

    monkeypatch.setattr(actions_module, "run_command", recording)
    progress: list[ActionProgress] = []
    said: list[AvailabilityNotice] = []

    with no_network() as attempts:
        result = adapter.run(
            "elevation download",
            NMT,
            root=root,
            on_progress=progress.append,
            on_notice=said.append,
        )

    (call,) = received
    cache = call.pop("cache")
    assert isinstance(cache, kartograf.MetadataCache)
    assert cache.db_path == tmp_path / "cache" / "kartograf" / "metadata.db"
    assert call == {
        "command": "elevation download",
        "options": NMT,
        "root": root,
        "update": None,
        "plan": None,
        "on_progress": call["on_progress"],
        "on_notice": call["on_notice"],
    }
    assert attempts == []
    hierarchy = f"{SEGMENT}/N-34/130"
    assert result.files == (
        ActionFile(
            path=f"{hierarchy}/N-34-130-D-d-2-1.asc",
            unit="N-34-130-D-d-2-1",
            status="new",
            size_bytes=4096,
            sha256=SHA,
            label="2023",
            version_path=f"{SEGMENT}/versions/N-34/130/2023_abababab/N-34-130-D-d-2-1.asc",
        ),
        ActionFile(
            path=f"{hierarchy}/N-34-130-D-d-2-2.asc",
            unit="N-34-130-D-d-2-2",
            status="unchanged",
            size_bytes=4096,
            sha256=SHA,
            label="2021",
            version_path=f"{SEGMENT}/versions/N-34/130/2021_abababab/N-34-130-D-d-2-2.asc",
        ),
        ActionFile(
            path=f"{hierarchy}/N-34-130-D-d-2-5.asc",
            unit="N-34-130-D-d-2-5",
            status="relabeled",
            size_bytes=4096,
            sha256=SHA,
            label="2023-b",
            version_path=(
                f"{SEGMENT}/versions/N-34/130/2023-b_abababab/N-34-130-D-d-2-5.asc"
            ),
        ),
    )
    assert result.failed == (
        ActionItem(
            "N-34-130-D-d-2-4", "failed", "source_unavailable", None, failure.error
        ),
        ActionItem(stale.store_path, "failed", "conflict", "stale_plan", STALE_TEXT),
    )
    assert (result.status, result.root, result.schema, result.command) == (
        "partial",
        str(root),
        "kartograf-download/1",
        "elevation download",
    )
    assert said == [AvailabilityNotice("info", "sheet_list", "4 sheets")]
    assert [(p.current, p.total, p.unit, p.status) for p in progress] == [
        (0, 0, None, "start"),
        (1, 4, "N-34-130-D-d-2-1", "downloading"),
        (1, 4, "N-34-130-D-d-2-1", "campaign"),
        (2, 4, "N-34-130-D-d-2-1", "completed"),
        (5, 10, None, "tiles"),
    ]
    assert progress[2].message == "2023"


def test_a_kept_plan_runs_as_an_upgrade_of_that_very_plan(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plan's document goes back as Kartograf's plan, ``update="upgrade"``."""
    root = tmp_path / "store"
    with no_network():
        plan = adapter.check("store init", {}, root=root)
    received: list[dict[str, object]] = []

    def recording(
        command: str, options: object, **kwargs: object
    ) -> kartograf.CommandResult[kartograf.DataReport]:
        received.append(dict(kwargs))
        return _answer(root, ())

    monkeypatch.setattr(actions_module, "run_command", recording)

    with no_network() as attempts:
        result = adapter.run("store init", {}, root=root, plan=plan)

    (call,) = received
    given = call["plan"]
    assert isinstance(given, kartograf.UpdatePlan)
    assert given == kartograf.UpdatePlan.from_dict(plan.document)
    assert (call["update"], call["root"]) == ("upgrade", root)
    assert "output_dir" not in call
    assert attempts == []
    assert (result.status, result.files, result.items) == ("ok", (), ())


@pytest.mark.parametrize("status", ["written", "replaced"])
def test_a_plain_file_of_a_run_in_a_store_breaks_the_contract(
    adapter: ActionAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    """A store run never writes plain files: ``data_error``, ``broken_contract``."""
    root = tmp_path / "store"
    plain = _file(root, "N-34-130-D-d-2-1", status, "")

    def answering(
        command: str, options: object, **kwargs: object
    ) -> kartograf.CommandResult[kartograf.DataReport]:
        return _answer(root, (plain,))

    monkeypatch.setattr(actions_module, "run_command", answering)

    with pytest.raises(BrokenContractError) as refused:
        adapter.run("elevation download", NMT, root=root)

    assert (refused.value.code, refused.value.details["reason"]) == (
        "data_error",
        "broken_contract",
    )
    assert status in str(refused.value)


def test_a_file_outside_the_store_breaks_the_contract(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file reported beside the root, also through ``..``, is no file of the store."""
    root = tmp_path / "store"
    outside = _file(tmp_path / "store" / ".." / "other", "N-34-130-D-d-2-1", "new", "x")

    def answering(
        command: str, options: object, **kwargs: object
    ) -> kartograf.CommandResult[kartograf.DataReport]:
        return _answer(root, (outside,))

    monkeypatch.setattr(actions_module, "run_command", answering)

    with pytest.raises(BrokenContractError):
        adapter.run("elevation download", NMT, root=root)


def test_kartograf_refuses_an_invalid_run_before_the_network_and_writes_nothing(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """Kartograf's text is kept, its option becomes ``details.option``."""
    root = tmp_path / "store"
    kartograf.init_store(root)
    before = sorted(root.rglob("*"))

    with no_network() as attempts, pytest.raises(ProducerError) as refused:
        adapter.run("elevation download", {**NMT, "year": 1800}, root=root)

    assert attempts == []
    assert refused.value.code == "validation_error"
    assert refused.value.details["option"] == "year"
    assert sorted(root.rglob("*")) == before


def test_the_scope_of_each_standard_path_reads_that_file_again(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """Every product family: the segment and unit of a link find that link.

    A scan of the scope reads one slot, so it names no file of another slot.
    """
    make_store(tmp_path / "base", slots=17, seed=7)
    root = tmp_path / "base" / STORE_DIR
    assert isinstance(adapter, SourceAdapter)
    links = [
        entry.relative_path.as_posix()
        for entry in adapter.iter_entries(root)
        if entry.kind == "link"
    ]
    segments = {path.split("/")[0] + "/" + path.split("/")[1] for path in links}

    found: dict[str, list[str]] = {}
    for path in links:
        scope = adapter.scope(path)
        found[path] = [
            entry.relative_path.as_posix()
            for entry in adapter.iter_entries(root, scope=scope)
            if entry.kind == "link"
        ]

    assert len(segments) > 10
    for path, read in found.items():
        assert path in read, path
        slot = path.rpartition("/")[0]
        assert {other.rpartition("/")[0] for other in read} == {slot}, path


@pytest.mark.parametrize("path", ["/abs/a/b/c.asc", "nmt/c.asc", "nmt/x/../c.asc"])
def test_a_place_outside_a_segment_has_no_scope(
    adapter: ActionAdapter, path: str
) -> None:
    """Only a relative path with a segment and a file has a scope."""
    with pytest.raises(ValueError):
        adapter.scope(path)
