"""Consumer-facing checks for TOML settings, validation, and the settings service."""

import os
import stat
import tomllib
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
    dump_settings,
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


def make_store(store_id: str, root: Path | None, **values: object) -> StoreConfig:
    """Build a valid local store with the Kartograf directory ``root`` (or none)."""
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
        own_data_dirs={str(tmp_path / "projekty" / "raba"): '/mnt/nas/dane "raba"'},
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
    """Without a file Archiwista starts with the grey basemaps and v0.1 limits."""
    settings = ConfigStore(tmp_path / "absent.toml").load()

    assert settings.stores == ()
    assert settings.offline is False
    assert settings.scan_threads == 8
    assert settings.scan_interval_s("local") == 5 * 60
    assert settings.scan_interval_s("share") == 15 * 60
    assert settings.full_scan_interval_h == 24
    assert [(item.kind, item.origin, item.grayscale) for item in settings.basemaps] == [
        ("vector", "https://tiles.openfreemap.org", False),
        ("xyz", "https://mapy.geoportal.gov.pl", True),
    ]
    assert settings.store_write_for_all is False
    assert settings.default_project_visibility == "public"


@pytest.mark.usefixtures("polish")
def test_config_store_invalid_toml_reported_in_polish(tmp_path: Path) -> None:
    """A syntax error names the file instead of raising a parser traceback."""
    path = tmp_path / "config.toml"
    path.write_text("port = \n", encoding="utf-8")

    with pytest.raises(SettingsValidationError) as error:
        ConfigStore(path).load()

    assert error.value.problems[0].code == "invalid_toml"
    assert "nie jest poprawnym TOML" in error.value.problems[0].message


@pytest.mark.usefixtures("polish")
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


@pytest.mark.parametrize(
    ("kind", "url", "reason"),
    [
        ("xyz", "https://tiles.example/tile.png", "{z}, {x} i {y}"),
        ("vector", "https://tiles.example/{z}/{x}/{y}.pbf", "adres TileJSON"),
    ],
)
@pytest.mark.usefixtures("polish")
def test_config_basemap_url_fits_its_kind(kind: str, url: str, reason: str) -> None:
    """XYZ needs a tile template; a vector basemap its TileJSON, not a template."""
    with pytest.raises(SettingsValidationError) as error:
        parse_settings({"basemaps": [{"name": "X", "kind": kind, "url": url}]})

    assert reason in error.value.problems[0].message


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


@pytest.mark.usefixtures("polish")
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


def test_config_validate_carries_reason_and_hint_of_a_refused_store(
    roots: tuple[Path, Path],
) -> None:
    """What a producer says about a directory it refuses reaches the problem."""
    refused = SourceState(
        producer="kartograf",
        status="incompatible",
        detail="no marker",
        reason="no_marker",
        hint="run the init command",
    )
    settings = AppSettings(
        stores=(make_store("a", roots[0]), make_store("b", roots[1]))
    )
    registry = ProbeRegistry(failing={roots[0]: refused})

    problems = validate_settings(settings, registry)
    error = SettingsValidationError(problems)

    assert [(p.code, p.field, p.reason, p.hint) for p in problems] == [
        (
            "source_incompatible",
            "stores[0].kartograf",
            "no_marker",
            "run the init command",
        )
    ]
    assert error.details["problems"] == [
        {
            "code": "source_incompatible",
            "field": "stores[0].kartograf",
            "message": problems[0].message,
            "reason": "no_marker",
            "hint": "run the init command",
        }
    ]


def test_config_problem_without_reason_has_only_code_field_and_message(
    roots: tuple[Path, Path],
) -> None:
    """A probe with nothing to add leaves the members of the problem as they were."""
    failing = SourceState(producer="kartograf", status="error", detail="boom")
    registry = ProbeRegistry(failing={roots[0]: failing})

    problems = validate_settings(
        AppSettings(stores=(make_store("a", roots[0]),)), registry
    )

    assert (problems[0].reason, problems[0].hint) == (None, None)
    assert set(SettingsValidationError(problems).details["problems"][0]) == {
        "code",
        "field",
        "message",
    }


def test_config_validate_skips_unchanged_disconnected_store(tmp_path: Path) -> None:
    """Changing offline mode works while an existing share is unplugged."""
    previous = AppSettings(stores=(make_store("a", tmp_path / "unplugged"),))
    changed = previous.model_copy(update={"offline": True})

    assert validate_settings(changed, ProbeRegistry(), previous=previous) == ()


def _mark(directory: Path, marker: str) -> Path:
    """Create ``directory`` holding the marker file of a producer's store."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / marker).write_text("{}", encoding="utf-8")
    return directory


def test_config_store_keeps_the_directories_it_has_and_loads_old_files(
    tmp_path: Path,
) -> None:
    """Stores of one or both directories round-trip; an old file is unchanged."""
    # Arrange
    old = tmp_path / "old.toml"
    old.write_text(
        "[[stores]]\n"
        'id = "zespol"\n'
        'name = "Zespół"\n'
        'kartograf = "/mnt/nas/kartograf"\n',
        encoding="utf-8",
    )
    settings = AppSettings(
        stores=(
            make_store("kart", tmp_path / "k"),
            make_store("imgw", None, imgw=tmp_path / "i"),
            make_store("both", tmp_path / "b", imgw=tmp_path / "bi"),
        )
    )
    config = ConfigStore(tmp_path / "config.toml")

    # Act
    loaded = ConfigStore(old).load().stores[0]
    config.save(settings)
    text = config.path.read_text(encoding="utf-8")

    # Assert
    assert config.load() == settings
    assert [store.roots() for store in settings.stores] == [
        {"kartograf": tmp_path / "k"},
        {"imgw": tmp_path / "i"},
        {"kartograf": tmp_path / "b", "imgw": tmp_path / "bi"},
    ]
    assert (text.count("kartograf = "), text.count("imgw = ")) == (2, 2)
    assert loaded.imgw is None and loaded.roots() == {
        "kartograf": Path("/mnt/nas/kartograf")
    }
    again = AppSettings(stores=(loaded,))
    assert "imgw" not in dump_settings(again)
    assert parse_settings(tomllib.loads(dump_settings(again))) == again


@pytest.mark.parametrize("store", [{}, {"kartograf": None, "imgw": None}])
def test_config_store_needs_a_directory_and_detects_its_kind_from_any(
    store: dict[str, None],
) -> None:
    """A store with no directory is refused as a whole; IMGW's gives the kind."""
    with pytest.raises(SettingsValidationError) as error:
        parse_settings({"stores": [{"id": "a", "name": "A", **store}]})
    share = parse_settings(
        {"stores": [{"id": "a", "name": "A", "imgw": "\\\\nas\\dane\\imgw"}]}
    )

    problem = error.value.problems[0]
    assert (problem.code, problem.field) == ("invalid_value", "stores[0]")
    assert "at least one producer directory: kartograf or imgw" in problem.message
    assert share.stores[0].kind == "share"


def test_config_validate_checks_each_directory_of_a_store_at_its_own_field(
    tmp_path: Path,
) -> None:
    """The IMGW directory is checked like the Kartograf one and named by its field."""
    # Arrange
    kartograf = tmp_path / "kartograf"
    kartograf.mkdir()
    both = AppSettings(stores=(make_store("a", kartograf, imgw=tmp_path / "brak"),))
    imgw = tmp_path / "imgw"
    imgw.mkdir()
    only = AppSettings(stores=(make_store("a", None, imgw=imgw),))
    failing = ProbeRegistry(
        failing={imgw: SourceState(producer="imgw", status="not_installed")}
    )

    # Act
    missing = validate_settings(both, ProbeRegistry())
    accepted = validate_settings(only, ProbeRegistry())
    refused = validate_settings(only, failing)

    # Assert
    assert [(p.code, p.field) for p in missing] == [("root_missing", "stores[0].imgw")]
    assert "imgw" in missing[0].message
    assert accepted == ()
    assert [(p.code, p.field) for p in refused] == [
        ("source_not_installed", "stores[0].imgw")
    ]


def test_config_validate_finds_a_directory_inside_a_store_by_its_marker(
    tmp_path: Path,
) -> None:
    """A marker of either producer in an ancestor nests the directory under it."""
    # Arrange
    imgw_store = _mark(tmp_path / "imgw", "imgw-store.json")
    kartograf_store = _mark(tmp_path / "kartograf", "kartograf-store.json")
    inside_imgw = imgw_store / "kartograf"
    inside_kartograf = kartograf_store / "nmt" / "imgw"
    inside_imgw.mkdir()
    inside_kartograf.mkdir(parents=True)
    settings = AppSettings(
        stores=(make_store("a", inside_imgw, imgw=inside_kartograf),)
    )

    # Act
    problems = validate_settings(settings, ProbeRegistry())

    # Assert
    assert [(p.code, p.field) for p in problems] == [
        ("root_nested", "stores[0].kartograf"),
        ("root_nested", "stores[0].imgw"),
    ]
    assert str(imgw_store) in problems[0].message
    assert "imgw-store.json" in problems[0].message
    assert str(kartograf_store) in problems[1].message
    assert "kartograf-store.json" in problems[1].message


@pytest.mark.parametrize(
    ("below", "found"),
    [
        (("segment",), True),
        (("product", "segment"), True),
        (("product", "segment", "slot"), False),
    ],
)
def test_config_validate_looks_two_levels_below_a_directory_for_a_store(
    tmp_path: Path, below: tuple[str, ...], found: bool
) -> None:
    """A store down in the tree is found to the bounded depth, not deeper."""
    # Arrange
    root = _mark(tmp_path / "kartograf", "kartograf-store.json")
    folder = _mark(root.joinpath(*below), "imgw-store.json")

    # Act
    problems = validate_settings(
        AppSettings(stores=(make_store("a", root),)), ProbeRegistry()
    )

    # Assert
    assert [(p.code, p.field) for p in problems] == (
        [("root_nested", "stores[0].kartograf")] if found else []
    )
    if found:
        assert str(folder) in problems[0].message


def test_config_validate_accepts_stores_beside_each_other_with_their_own_markers(
    tmp_path: Path,
) -> None:
    """A marker in the directory itself, or in a sibling's, nests nothing."""
    kartograf = _mark(tmp_path / "data" / "kartograf", "kartograf-store.json")
    imgw = _mark(tmp_path / "data" / "imgw", "imgw-store.json")

    problems = validate_settings(
        AppSettings(stores=(make_store("a", kartograf, imgw=imgw),)), ProbeRegistry()
    )

    assert problems == ()


def test_config_validate_judges_by_the_real_path_and_enters_no_link(
    tmp_path: Path,
) -> None:
    """A link into a store nests; a link out of a directory is not followed."""
    # Arrange
    store = _mark(tmp_path / "imgw", "imgw-store.json")
    inner = store / "kartograf"
    inner.mkdir()
    shortcut = tmp_path / "shortcut"
    shortcut.symlink_to(inner, target_is_directory=True)
    elsewhere = _mark(tmp_path / "elsewhere", "kartograf-store.json")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(elsewhere, target_is_directory=True)

    # Act
    linked = validate_settings(
        AppSettings(stores=(make_store("a", shortcut),)), ProbeRegistry()
    )
    entered = validate_settings(
        AppSettings(stores=(make_store("b", root),)), ProbeRegistry()
    )

    # Assert
    assert [(p.code, p.field) for p in linked] == [
        ("root_nested", "stores[0].kartograf")
    ]
    assert entered == ()


def test_config_validate_reads_markers_only_around_new_or_moved_directories(
    tmp_path: Path,
) -> None:
    """Markers are read around new or moved directories only: a share may be gone."""
    # Arrange
    store = _mark(tmp_path / "imgw", "imgw-store.json")
    (store / "kartograf").mkdir()
    (store / "other").mkdir()
    saved = AppSettings(stores=(make_store("a", store / "kartograf"),))
    edited = saved.model_copy(update={"offline": True})
    moved = AppSettings(stores=(make_store("a", store / "other"),))

    # Act
    unchanged = validate_settings(edited, ProbeRegistry(), previous=saved)
    first = validate_settings(saved, ProbeRegistry())
    relocated = validate_settings(moved, ProbeRegistry(), previous=saved)

    # Assert
    assert unchanged == ()
    assert [p.code for p in first] == ["root_nested"]
    assert [p.code for p in relocated] == ["root_nested"]


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


@pytest.mark.usefixtures("polish")
def test_own_data_dir_validation(tmp_path: Path, roots: tuple[Path, Path]) -> None:
    """A data folder in a store, nested with another project's or absent is refused.

    A valid folder passes; one refused already (unchanged since the
    settings in effect) is not checked on the disk again, only its rules.
    """
    # Arrange
    store = make_store("zespol", roots[0])
    valid = tmp_path / "dane" / "raba"
    nested = valid / "wisla"
    inside = roots[0] / "projekty" / "dane"
    for folder in (nested, inside):
        folder.mkdir(parents=True)
    projects = {name: str(tmp_path / "projekty" / name) for name in "abcd"}

    def check(**folders: Path) -> list[tuple[str, str]]:
        settings = AppSettings(
            stores=(store,),
            own_data_dirs={projects[key]: str(path) for key, path in folders.items()},
        )
        return [(p.code, p.field) for p in validate_settings(settings, ProbeRegistry())]

    # Act
    alone = check(a=valid)
    refused = check(a=valid, b=nested, c=inside, d=tmp_path / "brak")
    with pytest.raises(SettingsValidationError) as relative:
        parse_settings({"own_data_dirs": {projects["a"]: "dane/raba"}})

    # Assert
    assert alone == []
    field = "own_data_dirs.{}".format
    assert refused == [
        ("own_data_dir_overlaps_project", field(projects["a"])),
        ("own_data_dir_overlaps_project", field(projects["b"])),
        ("own_data_dir_inside_store", field(projects["c"])),
        ("own_data_dir_missing", field(projects["d"])),
    ]
    assert "bezwzględna" in relative.value.problems[0].message
