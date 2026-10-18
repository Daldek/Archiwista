"""Consumer-facing checks for TOML settings, validation, and the settings service."""

import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from archiwista.config import (
    AppSettings,
    BasemapConfig,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
    StoreConfig,
    detect_store_kind,
    parse_settings,
    validate_settings,
)
from archiwista.sources import SourceState


@dataclass
class ProbeRegistry:
    """Registry whose probe reports available unless a root is listed."""

    failing: dict[Path, SourceState] = field(default_factory=dict)
    probed: list[Path] = field(default_factory=list)

    def states(self) -> tuple[SourceState, ...]:
        """Report an available Kartograf plugin."""
        return (SourceState(producer="kartograf", status="available"),)

    def probe(self, producer: str, root: Path) -> SourceState:
        """Record the probe and report the configured state."""
        self.probed.append(root)
        return self.failing.get(
            root, SourceState(producer=producer, status="available", store=str(root))
        )


def make_store(store_id: str, root: Path, **values: object) -> StoreConfig:
    """Build a valid local store pointing at ``root``."""
    return StoreConfig.model_validate(
        {"id": store_id, "name": store_id.title(), "kartograf": root, **values}
    )


@pytest.fixture
def roots(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    """Two separate, existing store directories."""
    first = tmp_path / "nas" / "kartograf"
    second = tmp_path / "local" / "kartograf"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    yield first, second
    for path in (first, second):
        path.chmod(stat.S_IRWXU)


def test_config_store_round_trip_restores_all_settings(
    tmp_path: Path, roots: tuple[Path, Path]
) -> None:
    """Saved settings, including Windows aliases and quotes, load back equal."""
    settings = AppSettings(
        port=8123,
        offline=True,
        scan_threads=3,
        scan_interval_local_min=2,
        scan_interval_share_min=30,
        full_scan_interval_h=6,
        project_dirs=(tmp_path / "projekty",),
        stores=(
            make_store(
                "zespol",
                roots[0],
                name='Zespół "NAS"',
                kind="share",
                path_aliases={
                    str(roots[0].parent) + "/": "Z:\\",
                    "/mnt/b": "\\\\nas\\b",
                },
            ),
            make_store("dom", roots[1], kind="local"),
        ),
        basemaps=(
            BasemapConfig(
                name="Ortofotomapa",
                kind="wms",
                url="https://mapy.geoportal.gov.pl/wss/service/WMS",
                attribution="GUGiK",
            ),
        ),
        store_write_for_all=True,
        default_project_visibility="private",
    )
    store = ConfigStore(tmp_path / "config" / "config.toml")

    store.save(settings)

    assert store.load() == settings


def test_config_store_reads_hand_written_spec_toml(tmp_path: Path) -> None:
    """The SPEC 5.5 store entry is accepted; a missing kind is detected."""
    path = tmp_path / "config.toml"
    path.write_text(
        "offline = true\n"
        "[[stores]]\n"
        'id = "zespol"\n'
        'name = "Zespół"\n'
        'kartograf = "/mnt/nas/kartograf"\n'
        "path_aliases = { \"/mnt/nas/\" = 'Z:\\' }\n",
        encoding="utf-8",
    )

    settings = ConfigStore(path).load()

    store = settings.stores[0]
    assert settings.offline is True
    assert store.kartograf == Path("/mnt/nas/kartograf")
    assert store.path_aliases == {"/mnt/nas/": "Z:\\"}
    assert store.kind == detect_store_kind(Path("/mnt/nas/kartograf"))


def test_config_store_missing_file_gives_specified_defaults(tmp_path: Path) -> None:
    """Without a file Archiwista starts with the grey BKG basemap and v0.1 limits."""
    settings = ConfigStore(tmp_path / "absent.toml").load()

    assert settings.stores == ()
    assert settings.offline is False
    assert settings.scan_threads == 8
    assert settings.scan_interval_s("local") == 5 * 60
    assert settings.scan_interval_s("share") == 15 * 60
    assert settings.full_scan_interval_h == 24
    assert [basemap.grayscale for basemap in settings.basemaps] == [False]
    assert settings.basemaps[0].origin == "https://sgx.geodatenzentrum.de"
    assert settings.store_write_for_all is False
    assert settings.default_project_visibility == "public"


def test_config_store_invalid_toml_reported_in_polish(tmp_path: Path) -> None:
    """A syntax error names the file instead of raising a parser traceback."""
    path = tmp_path / "config.toml"
    path.write_text("port = \n", encoding="utf-8")

    with pytest.raises(SettingsValidationError) as error:
        ConfigStore(path).load()

    assert error.value.problems[0].code == "invalid_toml"
    assert "nie jest poprawnym TOML" in error.value.problems[0].message


def test_config_parse_reports_every_invalid_field() -> None:
    """Each bad value is reported with its location and a Polish reason."""
    with pytest.raises(SettingsValidationError) as error:
        parse_settings(
            {
                "port": 80,
                "colour": "red",
                "project_dirs": ["projekty"],
                "default_project_visibility": "users",
                "stores": [
                    {"id": "a", "name": "A", "kartograf": "/a", "kind": "local"},
                    {"id": "a", "name": "B", "kartograf": "/b", "kind": "local"},
                ],
            }
        )

    messages = {problem.field: problem.message for problem in error.value.problems}
    assert "mniejsza niż 1024" in messages["port"]
    assert "nieznane ustawienie" in messages["colour"]
    assert "bezwzględna" in messages["project_dirs[0]"]
    assert "„a” powtarza się" in messages["stores"]
    assert "public, private" in messages["default_project_visibility"]


@pytest.mark.parametrize("hours", [1, 720])
def test_config_full_scan_interval_accepts_bounds(hours: int) -> None:
    """The full control scan may run every hour or every 30 days."""
    assert parse_settings({"full_scan_interval_h": hours}).full_scan_interval_h == hours


@pytest.mark.parametrize("hours", [0, 721])
def test_config_full_scan_interval_rejects_out_of_range(hours: int) -> None:
    """An interval under an hour or over 30 days is refused for its field."""
    with pytest.raises(SettingsValidationError) as error:
        parse_settings({"full_scan_interval_h": hours})

    assert [problem.field for problem in error.value.problems] == [
        "full_scan_interval_h"
    ]


def test_config_basemap_tile_template_requires_coordinates() -> None:
    """A tile URL without {z}/{x}/{y} cannot be saved as an XYZ basemap."""
    with pytest.raises(SettingsValidationError) as error:
        parse_settings(
            {"basemaps": [{"name": "X", "url": "https://tiles.example/tile.png"}]}
        )

    assert "{z}, {x} i {y}" in error.value.problems[0].message


def test_config_store_failed_save_keeps_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted save leaves the old settings and no temporary file."""
    store = ConfigStore(tmp_path / "config.toml")
    store.save(AppSettings(port=8100))

    def fail_replace(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        store.save(AppSettings(port=8200))

    assert store.load().port == 8100
    assert sorted(path.name for path in tmp_path.iterdir()) == ["config.toml"]


def test_config_validate_accepts_several_stores_and_read_only_root(
    roots: tuple[Path, Path],
) -> None:
    """Archiwista only reads, so a read-only store root is valid."""
    roots[0].chmod(stat.S_IRUSR | stat.S_IXUSR)
    registry = ProbeRegistry()
    settings = AppSettings(
        stores=(make_store("a", roots[0]), make_store("b", roots[1]))
    )

    assert validate_settings(settings, registry) == ()
    assert registry.probed == list(roots)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_config_validate_rejects_unreadable_root(roots: tuple[Path, Path]) -> None:
    """A root the user cannot list is rejected before probing the producer."""
    roots[0].chmod(0)
    registry = ProbeRegistry()

    problems = validate_settings(
        AppSettings(stores=(make_store("a", roots[0]),)), registry
    )

    assert [(p.code, p.field) for p in problems] == [
        ("root_unreadable", "stores[0].kartograf")
    ]
    assert registry.probed == []


def test_config_validate_rejects_missing_root(tmp_path: Path) -> None:
    """A disconnected share is reported, not silently accepted."""
    problems = validate_settings(
        AppSettings(stores=(make_store("a", tmp_path / "absent"),)), ProbeRegistry()
    )

    assert [p.code for p in problems] == ["root_missing"]
    assert "udział nie jest podłączony" in problems[0].message


def test_config_validate_rejects_nested_producer_directories(
    roots: tuple[Path, Path],
) -> None:
    """A store inside another store, or the same directory twice, is rejected."""
    inner = roots[0] / "nmt"
    inner.mkdir()
    settings = AppSettings(
        stores=(
            make_store("a", roots[0]),
            make_store("b", inner),
            make_store("c", roots[1]),
            make_store("d", roots[1]),
        )
    )

    problems = validate_settings(settings, ProbeRegistry())

    assert [(p.code, p.field) for p in problems] == [
        ("root_nested", "stores[1].kartograf"),
        ("root_nested", "stores[3].kartograf"),
    ]


def test_config_validate_reports_incompatible_store(roots: tuple[Path, Path]) -> None:
    """The producer's own reason is shown when the directory is not its store."""
    registry = ProbeRegistry(
        failing={
            roots[0]: SourceState(
                producer="kartograf", status="incompatible", detail="schema x/2"
            )
        }
    )

    problems = validate_settings(
        AppSettings(stores=(make_store("a", roots[0]),)), registry
    )

    assert [p.code for p in problems] == ["source_incompatible"]
    assert "schema x/2" in problems[0].message


def test_config_validate_skips_unchanged_disconnected_store(tmp_path: Path) -> None:
    """Changing offline mode works while an existing share is unplugged."""
    previous = AppSettings(stores=(make_store("a", tmp_path / "unplugged"),))
    changed = previous.model_copy(update={"offline": True})

    assert validate_settings(changed, ProbeRegistry(), previous=previous) == ()


def test_config_store_aliases_translate_between_computers() -> None:
    """Paths from a Windows manifest map to the local mount and back."""
    store = make_store(
        "zespol",
        Path("/mnt/nas/kartograf"),
        kind="share",
        path_aliases={"/mnt/nas/": "Z:\\", "/srv/b": "/Volumes/b"},
    )

    assert store.local_path("z:\\kartograf\\nmt\\a.tif") == Path(
        "/mnt/nas/kartograf/nmt/a.tif"
    )
    assert store.local_path("/Volumes/b/x") == Path("/srv/b/x")
    assert store.local_path("/Volumes/bb/x") == Path("/Volumes/bb/x")
    assert store.foreign_paths(Path("/mnt/nas/kartograf/a.tif")) == (
        "Z:\\kartograf\\a.tif",
    )
    assert store.foreign_paths(Path("/mnt/nasty/a.tif")) == ()


def test_config_detect_store_kind_from_mounts_and_unc(tmp_path: Path) -> None:
    """CIFS/NFS mounts and UNC paths are shares; deeper local mounts are not."""
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "22 1 8:1 / / rw - ext4 /dev/sdb1 rw\n"
        "40 22 0:50 / /mnt/nas rw - cifs //nas/dane rw\n"
        "41 40 8:2 / /mnt/nas/usb rw - ext4 /dev/sdc1 rw\n"
        "42 22 0:51 / /mnt/my\\040nfs rw - nfs4 nas:/x rw\n",
        encoding="utf-8",
    )

    def kind(path: str) -> str:
        return detect_store_kind(Path(path), mountinfo=mountinfo)

    assert kind("/mnt/nas/kartograf") == "share"
    assert kind("/mnt/nas/usb/kartograf") == "local"
    assert kind("/mnt/my nfs/kartograf") == "share"
    assert kind("/home/user/kartograf") == "local"
    assert kind("\\\\nas\\dane\\kartograf") == "share"


def test_settings_service_saves_and_notifies_subscribers(
    tmp_path: Path, roots: tuple[Path, Path]
) -> None:
    """A saved change reaches every subscriber even if one of them fails."""
    config = ConfigStore(tmp_path / "config.toml")
    service = SettingsService(config, ProbeRegistry())
    seen: list[tuple[bool, bool]] = []

    def broken(previous: AppSettings, current: AppSettings) -> None:
        raise RuntimeError("listener bug")

    service.subscribe(broken)
    unsubscribe = service.subscribe(
        lambda previous, current: seen.append((previous.offline, current.offline))
    )
    new = AppSettings(offline=True, stores=(make_store("a", roots[0]),))

    service.update(new)
    unsubscribe()
    service.update(new.model_copy(update={"offline": False}))

    assert seen == [(False, True)]
    assert config.load().offline is False
    assert service.get().offline is False


def test_settings_service_rejected_change_keeps_file_and_state(tmp_path: Path) -> None:
    """Invalid settings are neither saved, applied, nor announced."""
    config = ConfigStore(tmp_path / "config.toml")
    service = SettingsService(config, ProbeRegistry())
    calls: list[AppSettings] = []
    service.subscribe(lambda previous, current: calls.append(current))

    with pytest.raises(SettingsValidationError):
        service.update(AppSettings(stores=(make_store("a", tmp_path / "absent"),)))

    assert not config.exists()
    assert service.get() == AppSettings()
    assert calls == []
