"""Kartograf's runs of a project through the adapter's capability (plan 2026-10-25, A8).

``verify_project`` and a download whose pins the store holds work offline on
Kartograf's own fixture project, so they run for real under the socket guard.
A download that pins, a repin and a check need the network: Kartograf's
functions are stood in for with its own classes (``ProjectReport``,
``TaskResult``, ``ProjectCheck``, ``FileCheck``), and the call Archiwista makes
is recorded: Archiwista's metadata cache (never ``cache=True``), the update
mode, the tasks, no ``output_dir``. A lock of the manifest that stays is the
``project_locked`` conflict with its path, and is never removed.
"""

from pathlib import Path
from typing import Any

import kartograf
import pytest
from kartograf.testing import FixtureStore, build_fixture_store, build_project

import archiwista.adapter.kartograf.actions as actions_module
from archiwista.adapter.kartograf import load
from archiwista.error_document import describe
from archiwista.errors import ProducerError, ProjectLockedError
from archiwista.sources import (
    ActionProgress,
    AvailabilityNotice,
    PinnedVersion,
    ProjectActionAdapter,
    ProjectFileState,
    ProjectTaskRun,
    SourceContext,
)
from tests.fixtures.network import no_network

PL_TASK = "nmt-pl"
CZ_TASK = "nmt-cz"
LOCK = kartograf.PROJECT_LOCK
SEGMENT = "nmt/pl_1992_1m_evrf2007"


@pytest.fixture
def adapter(tmp_path: Path) -> ProjectActionAdapter:
    """Kartograf adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "kartograf"))
    assert isinstance(created, ProjectActionAdapter)
    return created


@pytest.fixture
def built(tmp_path: Path) -> FixtureStore:
    """Kartograf's fixture store, marked by the writer that built it."""
    return build_fixture_store(tmp_path / "data")


@pytest.fixture
def project(tmp_path: Path, built: FixtureStore) -> Path:
    """Kartograf's fixture project: two tasks, each pinning one version."""
    return build_project(tmp_path / "projekty" / "raba", built)


def _pin(sheet: str, label: str) -> kartograf.PinnedFile:
    """Return a pin of an NMT sheet as Kartograf keeps it: paths below the store."""
    place = f"{SEGMENT}/N-34/130/D/d/2/4"
    return kartograf.PinnedFile(
        role="output",
        unit=sheet,
        path=f"{place}/{sheet}.asc",
        version=f"{SEGMENT}/versions/N-34/130/D/d/2/4/{label}_abababab/{sheet}.asc",
        label=label,
        sha256="ab" * 32,
        size_bytes=4096,
    )


def _report(
    directory: Path, root: Path, *results: kartograf.TaskResult
) -> kartograf.ProjectReport:
    """Return a report of ``download_project`` with these results of tasks."""
    return kartograf.ProjectReport(
        project=kartograf.Project(directory=directory, root=root, tasks=()),
        tasks=results,
        notices=(kartograf.Notice("info", "sheet_list", f"{PL_TASK}: 1 sheet"),),
        ok=all(result.outcome != "failed" for result in results),
    )


def _failed(name: str, text: str, reason: str | None = None) -> kartograf.TaskResult:
    """Return a task that failed as Kartograf's commit of its pins fails."""
    return kartograf.TaskResult(
        name, "failed", (), (), (text,), "validation_error", reason
    )


def test_the_adapter_runs_projects_beside_changing_them(
    adapter: ProjectActionAdapter,
) -> None:
    """Kartograf's adapter offers the whole capability of a project."""
    assert callable(adapter.download_project)
    assert callable(adapter.check_project)
    assert callable(adapter.verify_project)


def test_a_verification_reads_every_pinned_file_offline(
    adapter: ProjectActionAdapter, built: FixtureStore, project: Path
) -> None:
    """Each pin is ``ok`` with its standard path below the store; then one is corrupt.

    A version whose bytes differ from the pin is ``corrupt`` with Kartograf's
    remedy, and the check says the project is not whole.
    """
    with no_network() as attempts:
        whole = adapter.verify_project(project)
        pinned = kartograf.open_project(project).tasks[0].files[0]
        version = built.root / pinned.version
        version.chmod(0o644)
        version.write_bytes(b"0" * 10)
        damaged = adapter.verify_project(project, tasks=[PL_TASK])

    assert attempts == []
    assert (whole.producer, whole.root, whole.ok) == (
        "kartograf",
        str(built.root),
        True,
    )
    assert [(item.task, item.status) for item in whole.files] == [
        (PL_TASK, "ok"),
        (CZ_TASK, "ok"),
    ]
    assert whole.files[0].path == pinned.path
    assert not Path(whole.files[0].path).is_absolute()
    assert whole.counts()["ok"] == 2
    assert damaged.ok is False
    assert [(item.task, item.status) for item in damaged.files] == [
        (PL_TASK, "corrupt")
    ]
    assert damaged.files[0].detail is not None
    assert "--force" in damaged.files[0].detail


def test_a_download_of_pins_the_store_holds_needs_no_network_and_no_lock(
    adapter: ProjectActionAdapter, built: FixtureStore, project: Path
) -> None:
    """Every task is ``unchanged``: nothing is fetched and the manifest stays."""
    manifest = (project / "kartograf-project.json").read_bytes()

    with no_network() as attempts:
        run = adapter.download_project(project)

    assert attempts == []
    assert (run.producer, run.root, run.ok) == ("kartograf", str(built.root), True)
    assert [(task.name, task.outcome) for task in run.tasks] == [
        (PL_TASK, "unchanged"),
        (CZ_TASK, "unchanged"),
    ]
    assert run.counts() == {
        "pinned": 0,
        "unchanged": 2,
        "restored": 0,
        "updated": 0,
        "failed": 0,
    }
    assert (project / "kartograf-project.json").read_bytes() == manifest
    assert not (project / LOCK).exists()


def test_a_corrupt_pin_fails_its_task_with_kartografs_code_and_reason(
    adapter: ProjectActionAdapter, built: FixtureStore, project: Path
) -> None:
    """The task keeps its pins and the others run; no lock is left or blamed."""
    pinned = kartograf.open_project(project).tasks[0].files[0]
    version = built.root / pinned.version
    version.chmod(0o644)
    version.write_bytes(b"0" * 10)

    with no_network() as attempts:
        run = adapter.download_project(project)

    assert attempts == []
    assert run.ok is False
    failed, kept = run.tasks
    assert (failed.name, failed.outcome, failed.code, failed.reason) == (
        PL_TASK,
        "failed",
        "data_error",
        "corrupt_pin",
    )
    assert failed.errors and "--force" in failed.errors[0]
    assert (kept.name, kept.outcome) == (CZ_TASK, "unchanged")
    assert run.failed == (failed,)


def test_a_download_gets_archiwistas_cache_and_the_mode_and_reads_the_pins(
    adapter: ProjectActionAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``update`` unset pins or restores, ``upgrade`` repins; never ``output_dir``.

    The pins come back below the store root as the manifest keeps them; the
    progress counts units and the notices keep Kartograf's texts.
    """
    directory = tmp_path / "projekty" / "raba"
    root = tmp_path / "data"
    received: list[dict[str, Any]] = []
    first, second = _pin("N-34-130-D-d-2-4", "2025"), _pin("N-34-130-D-d-2-4", "2021")

    def download(project_dir: Path, **kwargs: Any) -> kartograf.ProjectReport:
        received.append({"project_dir": project_dir, **kwargs})
        cache = kwargs["cache"]
        assert isinstance(cache, kartograf.MetadataCache)
        assert cache.db_path == tmp_path / "cache" / "kartograf" / "metadata.db"
        if kwargs["on_progress"] is not None:
            sheet = "N-34-130-D-d-2-4"
            kwargs["on_progress"](kartograf.DownloadProgress(1, 1, sheet, "completed"))
            kwargs["on_notice"](kartograf.Notice("info", "sheet_list", "1 sheet"))
        return _report(
            project_dir,
            root,
            kartograf.TaskResult(PL_TASK, "updated", (first,), (second,), ()),
        )

    monkeypatch.setattr(actions_module, "download_project", download)
    events: list[ActionProgress] = []
    notices: list[AvailabilityNotice] = []

    pinned = adapter.download_project(directory)
    repinned = adapter.download_project(
        directory,
        tasks=[PL_TASK],
        upgrade=True,
        on_progress=events.append,
        on_notice=notices.append,
    )

    assert [
        (call["project_dir"], call["tasks"], call["update"]) for call in received
    ] == [
        (directory, None, None),
        (directory, [PL_TASK], "upgrade"),
    ]
    assert (received[0]["on_progress"], received[0]["on_notice"]) == (None, None)
    assert all(
        set(call)
        == {"project_dir", "tasks", "update", "cache", "on_progress", "on_notice"}
        for call in received
    )
    assert pinned.root == str(root)
    assert repinned.tasks == (
        ProjectTaskRun(
            name=PL_TASK,
            outcome="updated",
            pinned=(
                PinnedVersion(
                    path=first.path,
                    version_path=first.version,
                    unit="N-34-130-D-d-2-4",
                    label="2025",
                    sha256="ab" * 32,
                    size_bytes=4096,
                ),
            ),
            unpinned=(
                PinnedVersion(
                    path=second.path,
                    version_path=second.version,
                    unit="N-34-130-D-d-2-4",
                    label="2021",
                    sha256="ab" * 32,
                    size_bytes=4096,
                ),
            ),
        ),
    )
    assert repinned.notices == (
        AvailabilityNotice("info", "sheet_list", f"{PL_TASK}: 1 sheet"),
    )
    assert events == [ActionProgress(1, 1, "N-34-130-D-d-2-4", "completed", "")]
    assert notices == [AvailabilityNotice("info", "sheet_list", "1 sheet")]


def test_a_check_gets_archiwistas_cache_and_keeps_every_state_of_kartograf(
    adapter: ProjectActionAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``newer``, ``check_failed`` and a store's ``conflict`` come back as they were."""
    directory = tmp_path / "projekty" / "raba"
    root = tmp_path / "data"
    received: list[dict[str, Any]] = []
    path = _pin("N-34-130-D-d-2-4", "2021").path
    files = (
        kartograf.FileCheck(
            PL_TASK, "N-34-130-D-d-2-4", path, "newer", "2021", "2025", None
        ),
        kartograf.FileCheck(
            CZ_TASK,
            "CTES96",
            "nmt/x/CTES96.tif",
            "check_failed",
            "2024",
            None,
            "timeout",
        ),
        kartograf.FileCheck("las", "", "", "conflict", None, None, "nested store"),
    )

    def check(project_dir: Path, **kwargs: Any) -> kartograf.ProjectCheck:
        received.append({"project_dir": project_dir, **kwargs})
        assert isinstance(kwargs["cache"], kartograf.MetadataCache)
        assert (
            kwargs["cache"].db_path == tmp_path / "cache" / "kartograf" / "metadata.db"
        )
        return kartograf.ProjectCheck(
            kartograf.Project(directory=project_dir, root=root, tasks=()),
            files,
            ("nowe",),
            (),
            False,
        )

    monkeypatch.setattr(actions_module, "check_project", check)

    checked = adapter.check_project(directory, tasks=[PL_TASK, CZ_TASK])

    (call,) = received
    assert (call["project_dir"], call["tasks"], call["on_notice"]) == (
        directory,
        [PL_TASK, CZ_TASK],
        None,
    )
    assert "output_dir" not in call
    assert checked.files == (
        ProjectFileState(PL_TASK, "N-34-130-D-d-2-4", path, "newer", "2021", "2025"),
        ProjectFileState(
            CZ_TASK,
            "CTES96",
            "nmt/x/CTES96.tif",
            "check_failed",
            "2024",
            None,
            "timeout",
        ),
        ProjectFileState("las", "", "", "conflict", None, None, "nested store"),
    )
    assert (checked.not_downloaded, checked.ok, checked.root) == (
        ("nowe",),
        False,
        str(root),
    )
    assert checked.counts()["check_failed"] == 1


def test_a_change_refused_while_the_lock_stays_names_the_lock_and_keeps_it(
    adapter: ProjectActionAdapter, project: Path
) -> None:
    """Kartograf waits for its lock, then Archiwista names it as ``project_locked``.

    The problem is a ``409 conflict`` with the lock's path and the instruction;
    Kartograf's own text is kept, and the lock and the manifest stay as they
    were.
    """
    lock = project / LOCK
    lock.mkdir()
    manifest = (project / "kartograf-project.json").read_bytes()

    with pytest.raises(ProjectLockedError) as raised:
        adapter.remove_project_task(project, name=PL_TASK)

    problem = describe(raised.value)
    assert problem.code == "conflict"
    assert problem.details["reason"] == "project_locked"
    assert problem.details["lock"] == str(lock)
    assert str(lock) in str(problem.hint)
    assert "kartograf" in raised.value.message
    assert lock.is_dir()
    assert (project / "kartograf-project.json").read_bytes() == manifest


def test_a_task_that_failed_on_the_lock_is_the_left_lock(
    adapter: ProjectActionAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed task with Kartograf's reason ``project_locked`` names the lock."""
    directory = tmp_path / "projekty" / "raba"
    directory.mkdir(parents=True)
    text = "project locked by another process"
    reason: list[str | None] = ["invalid_input"]

    def download(project_dir: Path, **kwargs: Any) -> kartograf.ProjectReport:
        failed = _failed(PL_TASK, text, reason[0])
        return _report(project_dir, tmp_path / "data", failed)

    monkeypatch.setattr(actions_module, "download_project", download)

    (directory / LOCK).mkdir()  # a lock that Kartograf does not blame is no refusal
    unlocked = adapter.download_project(directory)
    reason[0] = "project_locked"
    with pytest.raises(ProjectLockedError) as raised:
        adapter.download_project(directory)

    assert [task.outcome for task in unlocked.tasks] == ["failed"]
    assert raised.value.lock == str(directory / LOCK)
    assert text in raised.value.message
    assert (directory / LOCK).is_dir()


def test_a_refusal_without_a_lock_stays_kartografs_own(
    adapter: ProjectActionAdapter, tmp_path: Path
) -> None:
    """A directory with no manifest is Kartograf's refusal with its text, offline."""
    directory = tmp_path / "projekty" / "pusty"
    directory.mkdir(parents=True)

    with no_network() as attempts, pytest.raises(ProducerError) as raised:
        adapter.verify_project(directory)

    assert attempts == []
    assert not isinstance(raised.value, ProjectLockedError)
    assert raised.value.details["kartograf"]["exception"] == "ValidationError"
