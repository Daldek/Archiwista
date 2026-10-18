"""Plugin registry: a second entry point, missing packages, versions, failures.

The second plugin (``tests/fixtures/second_source``) is registered the way
production plugins are: a ``*.dist-info`` directory with ``entry_points.txt``
on ``sys.path``, discovered by ``load_registry``.
"""

import importlib
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from archiwista.config import AppPaths
from archiwista.doctor import run_doctor
from archiwista.errors import SourceIncompatibleError, SourceUnavailableError
from archiwista.messages import MESSAGES
from archiwista.sources import (
    GeoAdapter,
    LinkCheckAdapter,
    SegmentedAdapter,
    SheetGridAdapter,
    SourceState,
)
from archiwista.sources.registry import load_registry

SECOND_SOURCE = Path(__file__).parents[1] / "fixtures" / "second_source"
FIXTURE_MODULES = ("external_source_plugin", "external_producer")
EXTERNAL = SourceState(
    "external",
    "available",
    package_version="1.2.0",
    supported_versions=">=1,<2",
    schemas=("external-meta/1",),
)


@pytest.fixture(autouse=True)
def second_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register the second plugin through its ``*.dist-info`` on ``sys.path``."""
    for name in FIXTURE_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(SECOND_SOURCE))


def _install(
    site: Path, monkeypatch: pytest.MonkeyPatch, name: str, version: str, **points: str
) -> None:
    """Put one more distribution, optionally with plugin entry points, first."""
    dist = site / f"{name.replace('-', '_')}-{version}.dist-info"
    dist.mkdir(parents=True)
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    (dist / "METADATA").write_text(metadata, encoding="utf-8")
    if points:
        lines = "".join(f"{key} = {value}\n" for key, value in points.items())
        (dist / "entry_points.txt").write_text(
            "[archiwista.sources]\n" + lines, encoding="utf-8"
        )
    monkeypatch.syspath_prepend(str(site))


def test_plugins_second_entry_point_works_beside_kartograf(tmp_path: Path) -> None:
    """A second producer registered by entry point loads with its own cache."""
    store = tmp_path / "store"
    store.mkdir()
    (store / "2024.csv").write_text("x", encoding="utf-8")
    registry = load_registry(cache_dir=tmp_path / "cache")

    states = {state.producer: state for state in registry.states()}
    adapter = registry.adapter("external")

    assert states["external"] == EXTERNAL
    assert states["kartograf"].status == "available"
    assert [e.relative_path for e in adapter.iter_entries(store)] == [Path("2024.csv")]
    assert vars(adapter)["cache_dir"] == tmp_path / "cache" / "external"
    assert not any(
        isinstance(adapter, capability)
        for capability in (
            SegmentedAdapter,
            GeoAdapter,
            LinkCheckAdapter,
            SheetGridAdapter,
        )
    )
    assert registry.probe("external", store) == replace(EXTERNAL, store=str(store))


def test_plugins_second_plugin_shown_by_doctor(tmp_path: Path) -> None:
    """The diagnostics list the second plugin without changes in the doctor."""
    paths = AppPaths(config_file=tmp_path / "config.toml", data_dir=tmp_path / "data")
    registry = load_registry(cache_dir=paths.cache_dir)

    report = run_doctor(paths, registry, port_available=lambda port: True)

    assert (
        "ok",
        "Wtyczka external: wersja 1.2.0 (wspierane >=1,<2; schematy: external-meta/1)",
    ) in [(check.level, check.message) for check in report.checks]


def test_plugins_missing_producer_package_is_not_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without its producer library the source is ``not_installed``, not a crash."""
    monkeypatch.setitem(sys.modules, "external_producer", None)
    registry = load_registry(cache_dir=tmp_path)

    state = registry.state("external")

    assert (state.status, state.detail) == (
        "not_installed",
        MESSAGES["plugin_module_missing"].format(module="external_producer"),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        registry.adapter("external")
    assert raised.value.state == state
    assert registry.state("kartograf").status == "available"


def test_plugins_unsupported_producer_version_is_incompatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installed producer outside the plugin's range is ``incompatible``."""
    _install(tmp_path / "site", monkeypatch, "external-producer", "3.0.0")
    registry = load_registry(cache_dir=tmp_path)

    state = registry.state("external")

    assert state == SourceState(
        "external",
        "incompatible",
        package_version="3.0.0",
        supported_versions=">=1,<2",
        schemas=("external-meta/1",),
    )
    with pytest.raises(SourceIncompatibleError) as raised:
        registry.adapter("external")
    assert "3.0.0" in str(raised.value) and ">=1,<2" in str(raised.value)


def test_plugins_unsupported_schema_is_incompatible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A producer writing an unsupported schema makes only its source fail."""
    producer = importlib.import_module("external_producer")
    monkeypatch.setattr(producer, "SCHEMA", "external-meta/2")
    registry = load_registry(cache_dir=tmp_path)

    state = registry.state("external")

    assert (state.status, state.package_version) == ("incompatible", "1.2.0")
    assert state.detail is not None and "external-meta/2" in state.detail
    assert registry.state("kartograf").status == "available"


@pytest.mark.parametrize(
    ("value", "detail"),
    [
        ("external_source_plugin:load_failing", "RuntimeError: uszkodzona wtyczka"),
        ("external_source_plugin:load_not_adapter", MESSAGES["plugin_not_adapter"]),
        (
            "external_source_plugin:load",
            MESSAGES["plugin_wrong_producer"].format(declared="external"),
        ),
        ("missing_plugin_module:load", "ModuleNotFoundError"),
    ],
)
def test_plugins_faulty_plugin_is_an_error_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str, detail: str
) -> None:
    """A failing factory is an ``error`` state; other plugins keep working."""
    _install(tmp_path / "site", monkeypatch, "broken-plugin", "1.0.0", broken=value)
    registry = load_registry(cache_dir=tmp_path)

    states = {state.producer: state for state in registry.states()}

    assert states["broken"].status == "error"
    assert states["broken"].detail is not None and detail in states["broken"].detail
    assert (states["external"], states["kartograf"].status) == (EXTERNAL, "available")
    with pytest.raises(SourceUnavailableError):
        registry.adapter("broken")


def test_plugins_duplicate_producer_is_an_error_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two plugins claiming one producer are refused rather than guessed."""
    _install(
        tmp_path / "site",
        monkeypatch,
        "other-plugin",
        "1.0.0",
        external="external_source_plugin:load_failing",
    )

    state = load_registry(cache_dir=tmp_path).state("external")

    assert state.status == "error"
    assert state.detail is not None and "external_source_plugin:load" in state.detail


def test_plugins_failing_probe_and_unknown_producer_are_states(
    tmp_path: Path,
) -> None:
    """A probe that raises and an unregistered producer report states."""
    registry = load_registry(cache_dir=tmp_path)

    failed = registry.probe("external", tmp_path / "missing")
    unknown = registry.probe("imgw", tmp_path)

    assert (failed.status, failed.store) == ("error", str(tmp_path / "missing"))
    assert failed.detail is not None and "FileNotFoundError" in failed.detail
    assert (unknown.status, unknown.store) == ("not_installed", str(tmp_path))
