"""A second producer plugin goes through the index and the API (SPEC 13.7).

The test plugin (``tests/fixtures/second_source``) is registered the way
production plugins are, by an entry point on ``sys.path``. Its flat store of
``*.csv`` files has no segments, sheets or links; the scanner, the index and
the API handle it with no change and no import of Kartograf.
"""

import sys
from pathlib import Path

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppSettings, StoreConfig
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import running_api
from tests.fixtures.local_server import local_paths

SECOND_SOURCE = Path(__file__).parents[1] / "fixtures" / "second_source"
FIXTURE_MODULES = ("external_source_plugin", "external_producer")


class _ExternalStore(StoreConfig):
    """A store of the test producer: v0.1 settings name only Kartograf's directory."""

    def roots(self) -> dict[str, Path]:
        """Return the test producer's directory."""
        return {"external": self.kartograf}


def test_second_adapter_indexes_and_browses_without_core_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entry point → scan → /sources, /slots and the file card of a CSV file."""
    # Arrange
    for name in FIXTURE_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(SECOND_SOURCE))
    store = tmp_path / "pomiary"
    store.mkdir()
    for name in ("opady.csv", "stany.csv"):
        (store / name).write_text("data;wartość\n", encoding="utf-8")
    paths = local_paths(tmp_path)
    registry = load_registry(cache_dir=paths.cache_dir)
    config = _ExternalStore(id="pomiary", name="Pomiary", kartograf=store, kind="local")
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({"pomiary": {"external": str(store)}})
        scan_store(
            registry.adapter("external"),
            writer,
            AppSettings(stores=(config,)),
            "pomiary",
            mode="full",
        )

    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)

        # Act
        sources = owner.request("GET", "/sources").json()["items"]
        page = owner.request("GET", "/slots?store=pomiary&location=none").json()
        card = owner.request("GET", "/stores/pomiary/slots/opady.csv").json()

    # Assert
    assert {item["producer"]: item["status"] for item in sources} == {
        "external": "available",
        "kartograf": "available",
    }
    assert [row["slot"] for row in page["items"]] == ["opady.csv", "stany.csv"]
    assert page["items"][0]["segment"]["producer"] == "external"
    assert page["groups"] == {"footprint": 0, "country": 0, "none": 2}
    assert [version["path"] for version in card["versions"]] == ["opady.csv"]
    assert card["current"] == "opady.csv"
