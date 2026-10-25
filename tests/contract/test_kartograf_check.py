"""Kartograf's plan of a run through the adapter's capability (plan 2026-10-25, A4).

``check_command`` of ``store init`` plans the marker of a store root without the
network, so the conversion of Kartograf's ``kartograf-plan/1`` is shown on its
own answers: a marker to write, a marked store, a root a write would refuse.
The plan of a download needs the network; its call (``root=``, Archiwista's
metadata cache) and its statuses are stood in for with Kartograf's own
classes.
"""

from pathlib import Path

import kartograf
import pytest

import archiwista.adapter.kartograf.actions as actions_module
from archiwista.adapter.kartograf import load
from archiwista.errors import ProducerError, UnsupportedError
from archiwista.sources import (
    ActionAdapter,
    ActionPlan,
    AvailabilityNotice,
    PlanEntry,
    SourceContext,
)
from tests.fixtures.network import no_network

NMT = {"product": "nmt", "sheet": "N-34-130-D-d-2-4"}
CHECKED_AT = "2026-10-25T08:15:02+00:00"


@pytest.fixture
def adapter(tmp_path: Path) -> ActionAdapter:
    """Kartograf adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "kartograf"))
    assert isinstance(created, ActionAdapter)
    return created


def _item(name: str, status: str, **fields: object) -> kartograf.PlanItem:
    """Return a position of Kartograf's plan of an NMT download."""
    values: dict[str, object] = {
        "track": "pl_sheet",
        "segment": "nmt/pl_1992_1m_evrf2007",
        "hierarchy": "N-34/130",
        "name": name,
        "unit": name.removesuffix(".asc"),
        "local_label": None,
        "local_sha256": None,
        "available_label": None,
        "available_signal": None,
        "status": status,
    }
    return kartograf.PlanItem(**{**values, **fields})  # type: ignore[arg-type]


def test_the_plan_of_a_new_root_writes_its_marker_without_the_network(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """A new root is planned ``missing`` (the marker); a marked one ``current``."""
    root = tmp_path / "store"

    with no_network() as attempts:
        new = adapter.check("store init", {}, root=root)
        kartograf.init_store(root)
        marked = adapter.check("store init", {}, root=root)

    assert attempts == []
    assert (new.producer, new.command, new.schema, new.root) == (
        "kartograf",
        "store init",
        "kartograf-plan/1",
        str(root.resolve()),
    )
    assert new.entries == (
        PlanEntry(path="kartograf-store.json", unit=str(root), status="missing"),
    )
    assert marked.entries == (
        PlanEntry(path="kartograf-store.json", unit=str(root), status="current"),
    )
    assert (new.document["schema"], new.document["root"]) == (
        "kartograf-plan/1",
        str(root.resolve()),
    )
    assert new.todo == new.entries
    assert (new.size_bytes, new.size_complete) == (None, False)
    assert (marked.todo, marked.size_bytes, marked.size_complete) == ((), 0, True)


def test_a_root_a_write_would_refuse_is_the_one_conflict_of_the_plan(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """A root inside a store is planned, not raised: its reason is ``conflict``."""
    outer = tmp_path / "outer"
    kartograf.init_store(outer)
    inner = outer / "inner"

    with no_network() as attempts:
        plan = adapter.check("store init", {}, root=inner)

    assert attempts == []
    (entry,) = plan.entries
    assert (entry.path, entry.status, entry.conflict) == (
        str(inner.resolve()),
        "unverifiable",
        "nested_store",
    )
    assert entry.error is not None and str(outer) in entry.error
    assert plan.ok


def test_the_plan_of_a_download_comes_back_in_archiwistas_types(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kartograf gets the store's root and Archiwista's cache, never ``cache=True``.

    Every status and label comes back as Kartograf gave it; its plan names no
    size, so none is known and the total says so.
    """
    received: list[dict[str, object]] = []
    root = tmp_path / "store"
    items = (
        _item(
            "N-34-130-D-d-2-1.asc",
            "current",
            local_label="2023",
            available_label="2023",
        ),
        _item(
            "N-34-130-D-d-2-2.asc", "newer", local_label="2021", available_label="2023"
        ),
        _item("N-34-130-D-d-2-3.asc", "missing", available_label="2023"),
        _item("N-34-130-D-d-2-4.asc", "unverifiable", local_label="2022"),
        _item("N-34-130-D-d-2-5.asc", "check_failed", error="GUGiK did not answer"),
    )

    def recording(
        command: str, options: object, **kwargs: object
    ) -> kartograf.CommandResult[kartograf.UpdatePlan]:
        received.append({"command": command, "options": options, **kwargs})
        on_notice = kwargs["on_notice"]
        assert callable(on_notice)
        on_notice(kartograf.Notice("info", "sheet_list", "5 sheets"))
        plan = kartograf.UpdatePlan(
            root=str(root),
            checked_at=CHECKED_AT,
            kartograf_version=kartograf.__version__,
            items=items,
            notices=(kartograf.Notice("info", "sheet_list", "5 sheets"),),
        )
        return kartograf.CommandResult(command, True, "partial", plan)

    monkeypatch.setattr(actions_module, "check_command", recording)
    said: list[AvailabilityNotice] = []

    with no_network() as attempts:
        plan = adapter.check(
            "elevation download", NMT, root=root, on_notice=said.append
        )

    (call,) = received
    cache = call.pop("cache")
    assert isinstance(cache, kartograf.MetadataCache)
    assert cache.db_path == tmp_path / "cache" / "kartograf" / "metadata.db"
    assert call == {
        "command": "elevation download",
        "options": NMT,
        "root": root,
        "on_notice": call["on_notice"],
    }
    assert attempts == []
    assert said == [AvailabilityNotice("info", "sheet_list", "5 sheets")]
    assert isinstance(plan, ActionPlan)
    assert plan.entries == tuple(
        PlanEntry(
            path=item.store_path,
            unit=item.unit,
            status=item.status,
            local_label=item.local_label,
            available_label=item.available_label,
            error=item.error,
        )
        for item in items
    )
    assert (
        plan.entries[1].path == "nmt/pl_1992_1m_evrf2007/N-34/130/N-34-130-D-d-2-2.asc"
    )
    assert [entry.size_bytes for entry in plan.entries] == [None] * 5
    assert (plan.size_bytes, plan.size_complete, plan.ok) == (None, False, False)
    assert plan.counts() == {
        "current": 1,
        "newer": 1,
        "missing": 1,
        "unverifiable": 1,
        "check_failed": 1,
    }
    assert plan.checked_at.isoformat() == CHECKED_AT
    assert plan.notices == (AvailabilityNotice("info", "sheet_list", "5 sheets"),)
    assert kartograf.UpdatePlan.from_dict(plan.document).items == items
    assert ActionPlan.from_json(plan.to_json()) == plan


def test_a_check_without_a_plan_of_a_store_is_unsupported(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``project download`` answers with the check of a project, no plan of a store."""

    def answering(command: str, options: object, **kwargs: object) -> object:
        return kartograf.CommandResult(command, True, "ok", None)

    monkeypatch.setattr(actions_module, "check_command", answering)

    with pytest.raises(UnsupportedError) as refused:
        adapter.check("project download", {}, root=tmp_path / "store")

    assert (refused.value.code, refused.value.details["reason"]) == (
        "unsupported",
        "no_plan",
    )


def test_kartograf_refuses_an_invalid_option_before_the_network(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """Kartograf's text is kept, its option becomes ``details.option``."""
    root = tmp_path / "store"
    kartograf.init_store(root)

    with no_network() as attempts, pytest.raises(ProducerError) as refused:
        adapter.check("elevation download", {**NMT, "year": 1800}, root=root)

    assert attempts == []
    assert refused.value.code == "validation_error"
    assert refused.value.details["option"] == "year"
    assert refused.value.details["kartograf"]["message"] == str(refused.value)
