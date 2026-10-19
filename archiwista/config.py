"""Local configuration: TOML settings, local data paths, and settings service."""

import logging
import os
import re
import sys
import tempfile
import threading
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, Protocol, Self
from urllib.parse import urlsplit

import platformdirs
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from archiwista.errors import ArchiwistaError
from archiwista.messages import MESSAGES, with_detail
from archiwista.sources import SourceState

logger = logging.getLogger(__name__)

APP_NAME = "archiwista"
CONFIG_FILE_NAME = "config.toml"
DEFAULT_PORT = 8090
DEFAULT_SCAN_THREADS = 8
DEFAULT_SCAN_INTERVAL_LOCAL_MIN = 5
DEFAULT_SCAN_INTERVAL_SHARE_MIN = 15
DEFAULT_FULL_SCAN_INTERVAL_H = 24
SHARE_FILESYSTEMS = frozenset({"cifs", "smb3", "smbfs", "nfs", "nfs4"})
MOUNTINFO_PATH = Path("/proc/self/mountinfo")

type StoreKind = Literal["local", "share"]
type BasemapKind = Literal["xyz", "wms"]
# Visibility of a project without its own access entry (A-ADR-029): everyone
# sees it, or administrators only until someone shares it.
type DefaultProjectVisibility = Literal["public", "private"]

DEFAULT_PROJECT_VISIBILITIES: tuple[DefaultProjectVisibility, ...] = (
    "public",
    "private",
)

_STORE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


class SourceRegistryView(Protocol):
    """Read-only view of producer plugin states used by settings and doctor.

    The plugin registry (``archiwista.sources.registry``) satisfies this
    protocol structurally.
    """

    def states(self) -> tuple[SourceState, ...]:
        """Return the state of every registered producer plugin."""
        ...

    def probe(self, producer: str, root: Path) -> SourceState:
        """Probe a producer directory, or return the plugin's unavailable state."""
        ...


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Locate the configuration file and local application data.

    The data directory holds the rebuildable index, caches, job logs and
    areas, and the state database, which cannot be rebuilt (A-ADR-029).

    Parameters
    ----------
    config_file : Path
        TOML settings file in the user configuration directory.
    data_dir : Path
        Local user data directory holding the index, the state database,
        caches, jobs, and areas.
    """

    config_file: Path
    data_dir: Path

    @classmethod
    def default(cls) -> Self:
        """Return the per-user platform locations."""
        config_dir = platformdirs.user_config_path(APP_NAME, appauthor=False)
        data_dir = platformdirs.user_data_path(APP_NAME, appauthor=False)
        return cls(config_file=config_dir / CONFIG_FILE_NAME, data_dir=data_dir)

    @property
    def index_file(self) -> Path:
        """Local SQLite index."""
        return self.data_dir / "index.sqlite"

    @property
    def state_file(self) -> Path:
        """Local SQLite state: accounts, groups, project access (not rebuildable)."""
        return self.data_dir / "state.sqlite"

    @property
    def cache_dir(self) -> Path:
        """Local caches, one subdirectory per producer."""
        return self.data_dir / "cache"

    @property
    def jobs_dir(self) -> Path:
        """Background job logs."""
        return self.data_dir / "jobs"

    @property
    def areas_dir(self) -> Path:
        """Local copies of uploaded area files."""
        return self.data_dir / "areas"

    @property
    def work_dir(self) -> Path:
        """Scratch directories of processes reading files, one per process."""
        return self.data_dir / "work"

    def source_cache_dir(self, producer: str) -> Path:
        """Return the local cache directory owned by one producer plugin."""
        return self.cache_dir / producer


def _require_absolute(path: Path) -> Path:
    if not (path.is_absolute() or _is_unc(str(path))):
        raise ValueError(MESSAGES["settings_path_not_absolute"])
    return path


def _require_text(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(MESSAGES["settings_empty_text"])
    return stripped


AbsolutePath = Annotated[Path, AfterValidator(_require_absolute)]


def _is_unc(path: str) -> bool:
    return path.startswith(("\\\\", "//")) and len(path) > 2 and path[2] not in "\\/"


def _is_windows_path(path: str) -> bool:
    return _is_unc(path) or re.match(r"[A-Za-z]:[\\/]", path) is not None


class StoreConfig(BaseModel):
    r"""One configured store: a short id and its producer directories.

    Parameters
    ----------
    id : str
        Short name used in the API and interface, e.g. ``"zespol"``.
    name : str
        Human-readable store name.
    kartograf : Path
        Kartograf ``--output`` directory (the ``data/`` directory itself).
    kind : {"local", "share"}
        Detected from the file system when omitted; editable afterwards.
    path_aliases : dict[str, str]
        Local path prefix mapped to the same share's prefix on another
        computer, e.g. ``{"/mnt/nas/": "Z:\\"}``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    kartograf: AbsolutePath
    kind: StoreKind
    path_aliases: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _detect_kind(cls, data: object) -> object:
        if isinstance(data, Mapping) and data.get("kind") is None:
            root = data.get("kartograf")
            if isinstance(root, str | Path):
                return {**data, "kind": detect_store_kind(Path(root))}
        return data

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if _STORE_ID.fullmatch(value) is None:
            raise ValueError(MESSAGES["settings_store_id_pattern"])
        return value

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _require_text(value)

    @field_validator("path_aliases")
    @classmethod
    def _check_aliases(cls, value: dict[str, str]) -> dict[str, str]:
        for local, foreign in value.items():
            _require_absolute(Path(local))
            _require_text(foreign)
        return value

    def roots(self) -> dict[str, Path]:
        """Return producer directories keyed by producer id."""
        return {"kartograf": self.kartograf}

    def local_path(self, path: str) -> Path:
        r"""Translate a path written on another computer to this computer.

        Parameters
        ----------
        path : str
            Path as written elsewhere, e.g. ``Z:\kartograf\nmt`` in a
            project manifest; a path without a matching alias is returned
            unchanged.

        Returns
        -------
        Path
            The same location under this computer's local prefix.
        """
        for local, foreign in self.path_aliases.items():
            rest = _strip_prefix(path, foreign)
            if rest is not None:
                return Path(local).joinpath(*rest)
        return Path(path)

    def foreign_paths(self, path: Path) -> tuple[str, ...]:
        """Return a local path as written on every aliased computer.

        Parameters
        ----------
        path : Path
            Path on this computer.

        Returns
        -------
        tuple[str, ...]
            One path per alias whose local prefix contains ``path``.
        """
        result: list[str] = []
        for local, foreign in self.path_aliases.items():
            rest = _strip_prefix(str(path), local)
            if rest is None:
                continue
            flavour = PureWindowsPath if _is_windows_path(foreign) else PurePosixPath
            result.append(str(flavour(foreign).joinpath(*rest)))
        return tuple(result)


def _strip_prefix(path: str, prefix: str) -> tuple[str, ...] | None:
    """Return the components of ``path`` below ``prefix`` or ``None``."""
    windows = _is_windows_path(prefix)
    flavour = PureWindowsPath if windows else PurePosixPath
    parts = flavour(path).parts
    prefix_parts = flavour(prefix).parts
    if windows:
        parts = tuple(part.casefold() for part in parts)
        compare = tuple(part.casefold() for part in prefix_parts)
    else:
        compare = prefix_parts
    if len(parts) < len(compare) or parts[: len(compare)] != compare:
        return None
    return flavour(path).parts[len(compare) :]


class BasemapConfig(BaseModel):
    """Online basemap shown under the data when offline mode is off.

    Parameters
    ----------
    name : str
        Name shown in the interface.
    kind : {"xyz", "wms"}
        Tile template with ``{z}/{x}/{y}`` or a WMS endpoint.
    url : str
        Tile template or WMS address (http or https).
    attribution : str
        Attribution text required by the provider.
    grayscale : bool
        Render the tiles in grey so data outlines stay readable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: BasemapKind = "xyz"
    url: str
    attribution: str = ""
    grayscale: bool = False

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _require_text(value)

    @model_validator(mode="after")
    def _check_url(self) -> Self:
        parts = urlsplit(self.url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(MESSAGES["settings_basemap_url"])
        if self.kind == "xyz" and not all(
            token in self.url for token in ("{z}", "{x}", "{y}")
        ):
            raise ValueError(MESSAGES["settings_basemap_xyz"])
        return self

    @property
    def origin(self) -> str:
        """Scheme, host, and port of the provider, e.g. for a CSP source list."""
        parts = urlsplit(self.url)
        return f"{parts.scheme}://{parts.netloc}"


# BKG TopPlusOpen "web_grau" is grey by design, so the client does not
# desaturate it; unlike tile.openstreetmap.org it serves real tiles to
# requests without a Referer (the app sends Referrer-Policy: no-referrer).
DEFAULT_BASEMAP = BasemapConfig(
    name="TopPlusOpen szary (BKG)",
    kind="xyz",
    url="https://sgx.geodatenzentrum.de/wmts_topplus_open/tile/1.0.0/web_grau/default/WEBMERCATOR/{z}/{y}/{x}.png",
    attribution="© BKG (2026), dl-de/by-2-0",
    grayscale=False,
)


class AppSettings(BaseModel):
    """All user settings stored in the TOML configuration file.

    Parameters
    ----------
    port : int
        Local server port on 127.0.0.1.
    offline : bool
        Disable every external request made by the browser.
    scan_threads : int
        Threads reading the segments of a store on a share: they hide its
        I/O latency, not CPU. A local store is read by one thread.
    scan_interval_local_min, scan_interval_share_min : int
        Incremental scan interval for local stores and network shares.
    full_scan_interval_h : int
        Hours between two scheduled full control scans of a store:
        incremental scans do not list known version directories again, so
        only a full scan notices a file deleted or added inside one.
    project_dirs : tuple[Path, ...]
        Directories searched for producer project manifests.
    stores : tuple[StoreConfig, ...]
        Configured stores with unique ids.
    basemaps : tuple[BasemapConfig, ...]
        Online basemaps, grey BKG TopPlusOpen by default.
    store_write_for_all : bool
        Give everyone the store write permission, not only people with the
        ``store_writer`` role (A-ADR-029; checked from v0.3).
    default_project_visibility : {"public", "private"}
        Visibility of a project without its own access entry: everyone, or
        administrators only.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    port: int = Field(default=DEFAULT_PORT, ge=1024, le=65535)
    offline: bool = False
    scan_threads: int = Field(default=DEFAULT_SCAN_THREADS, ge=1, le=64)
    scan_interval_local_min: int = Field(
        default=DEFAULT_SCAN_INTERVAL_LOCAL_MIN, ge=1, le=1440
    )
    scan_interval_share_min: int = Field(
        default=DEFAULT_SCAN_INTERVAL_SHARE_MIN, ge=1, le=1440
    )
    full_scan_interval_h: int = Field(
        default=DEFAULT_FULL_SCAN_INTERVAL_H, ge=1, le=720
    )
    project_dirs: tuple[AbsolutePath, ...] = ()
    stores: tuple[StoreConfig, ...] = ()
    basemaps: tuple[BasemapConfig, ...] = (DEFAULT_BASEMAP,)
    store_write_for_all: bool = False
    default_project_visibility: DefaultProjectVisibility = "public"

    @field_validator("default_project_visibility", mode="before")
    @classmethod
    def _check_default_visibility(cls, value: object) -> object:
        if value not in DEFAULT_PROJECT_VISIBILITIES:
            raise ValueError(MESSAGES["settings_default_visibility"])
        return value

    @field_validator("stores")
    @classmethod
    def _check_store_ids(
        cls, value: tuple[StoreConfig, ...]
    ) -> tuple[StoreConfig, ...]:
        _require_unique([store.id for store in value], "settings_duplicate_store")
        return value

    @field_validator("basemaps")
    @classmethod
    def _check_basemap_names(
        cls, value: tuple[BasemapConfig, ...]
    ) -> tuple[BasemapConfig, ...]:
        _require_unique(
            [basemap.name for basemap in value], "settings_duplicate_basemap"
        )
        return value

    def store(self, store_id: str) -> StoreConfig | None:
        """Return the store with ``store_id`` or ``None``."""
        return next((store for store in self.stores if store.id == store_id), None)

    def scan_interval_s(self, kind: StoreKind) -> int:
        """Return the incremental scan interval in seconds for a store kind."""
        minutes = (
            self.scan_interval_share_min
            if kind == "share"
            else self.scan_interval_local_min
        )
        return minutes * 60


def _require_unique(values: Sequence[str], message_key: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(MESSAGES[message_key].format(value=value))
        seen.add(value)


def detect_store_kind(path: Path, *, mountinfo: Path = MOUNTINFO_PATH) -> StoreKind:
    """Detect whether a store directory is on a network share.

    Parameters
    ----------
    path : Path
        Store directory; it does not need to exist.
    mountinfo : Path, optional
        Linux mount table, replaceable in tests.

    Returns
    -------
    {"local", "share"}
        ``"share"`` for UNC paths, Windows network drives, and CIFS, SMB 3,
        or NFS mounts; otherwise ``"local"``.
    """
    if _is_unc(str(path)):
        return "share"
    if sys.platform == "win32":
        return "share" if _is_windows_network_drive(path) else "local"
    fs_type = _filesystem_type(path, mountinfo)
    return "share" if fs_type in SHARE_FILESYSTEMS else "local"


def _filesystem_type(path: Path, mountinfo: Path) -> str | None:
    """Return the file system type of the deepest mount containing ``path``."""
    try:
        lines = mountinfo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    target = Path(os.path.realpath(path))
    best: tuple[int, str] | None = None
    for line in lines:
        fields, separator, rest = line.partition(" - ")
        parts = fields.split(" ")
        if not separator or len(parts) < 5 or not rest:
            continue
        mount_point = Path(_unescape_mount(parts[4]))
        if not target.is_relative_to(mount_point):
            continue
        depth = len(mount_point.parts)
        if best is None or depth >= best[0]:
            best = (depth, rest.split(" ")[0])
    return None if best is None else best[1]


def _unescape_mount(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def _is_windows_network_drive(path: Path) -> bool:  # pragma: no cover - Windows
    if sys.platform != "win32":
        return False
    import ctypes

    drive_remote = 4
    anchor = PureWindowsPath(path).anchor
    return bool(anchor) and ctypes.windll.kernel32.GetDriveTypeW(anchor) == drive_remote


@dataclass(frozen=True, slots=True)
class SettingsProblem:
    """One reason the settings cannot be used.

    Parameters
    ----------
    code : str
        Stable machine code, e.g. ``"root_missing"`` or ``"root_nested"``.
    field : str
        Settings location, e.g. ``"stores[0].kartograf"``.
    message : str
        Polish description for the user.
    """

    code: str
    field: str
    message: str


class SettingsValidationError(ArchiwistaError):
    """Settings are malformed or point at unusable directories."""

    def __init__(self, problems: Sequence[SettingsProblem]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(problem.message for problem in self.problems))


_PYDANTIC_MESSAGES = {
    "missing": "settings_missing",
    "extra_forbidden": "settings_unknown_key",
    "int_type": "settings_not_integer",
    "int_parsing": "settings_not_integer",
    "int_from_float": "settings_not_integer",
    "bool_type": "settings_not_boolean",
    "bool_parsing": "settings_not_boolean",
    "string_type": "settings_not_text",
    "tuple_type": "settings_not_list",
    "list_type": "settings_not_list",
}


def parse_settings(data: Mapping[str, object]) -> AppSettings:
    """Validate raw settings data, reporting problems in Polish.

    Parameters
    ----------
    data : Mapping[str, object]
        Parsed TOML or JSON settings.

    Returns
    -------
    AppSettings
        Validated settings; omitted store kinds are detected.

    Raises
    ------
    SettingsValidationError
        If any value is missing, unknown, or out of range.
    """
    try:
        return AppSettings.model_validate(data)
    except ValidationError as error:
        raise SettingsValidationError(
            [_problem_from_pydantic(item) for item in error.errors()]
        ) from error


def _problem_from_pydantic(item: Mapping[str, object]) -> SettingsProblem:
    loc = item.get("loc", ())
    field = _format_location(loc if isinstance(loc, tuple) else ())
    kind = str(item.get("type", ""))
    context = item.get("ctx")
    ctx = context if isinstance(context, Mapping) else {}
    if kind == "value_error":
        detail = str(ctx.get("error", MESSAGES["settings_bad_value"]))
    elif kind in ("greater_than_equal", "greater_than"):
        limit = ctx.get("ge", ctx.get("gt"))
        detail = MESSAGES["settings_too_small"].format(limit=limit)
    elif kind in ("less_than_equal", "less_than"):
        limit = ctx.get("le", ctx.get("lt"))
        detail = MESSAGES["settings_too_large"].format(limit=limit)
    else:
        detail = MESSAGES[_PYDANTIC_MESSAGES.get(kind, "settings_bad_value")]
    return SettingsProblem(
        code="invalid_value",
        field=field,
        message=MESSAGES["settings_invalid_value"].format(field=field, detail=detail),
    )


def _format_location(loc: tuple[object, ...]) -> str:
    text = ""
    for part in loc:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else str(part)
    return text


def validate_settings(
    settings: AppSettings,
    registry: SourceRegistryView,
    *,
    previous: AppSettings | None = None,
) -> tuple[SettingsProblem, ...]:
    """Check that settings point at usable, non-nested producer directories.

    Parameters
    ----------
    settings : AppSettings
        Candidate settings.
    registry : SourceRegistryView
        Producer plugins; each new or moved store directory is probed for
        a supported producer version and schema.
    previous : AppSettings, optional
        Settings in effect; directories unchanged since then are not checked
        again, so a disconnected share does not block unrelated edits.

    Returns
    -------
    tuple[SettingsProblem, ...]
        Empty when the settings can be saved.
    """
    old_roots = {
        (store.id, producer): root
        for store in (previous.stores if previous else ())
        for producer, root in store.roots().items()
    }
    old_project_dirs = set(previous.project_dirs) if previous else set()
    problems: list[SettingsProblem] = []
    labelled: list[tuple[str, Path]] = []
    for index, store in enumerate(settings.stores):
        for producer, root in store.roots().items():
            field = f"stores[{index}].{producer}"
            labelled.append((field, root))
            if old_roots.get((store.id, producer)) == root:
                continue
            root_problems = check_store_root(store, producer, field)
            problems.extend(
                root_problems or _probe_root(store, producer, field, registry)
            )
    problems.extend(check_nesting(labelled))
    for index, path in enumerate(settings.project_dirs):
        if path not in old_project_dirs:
            problems.extend(check_project_dir(path, f"project_dirs[{index}]"))
    return tuple(problems)


def check_store_root(
    store: StoreConfig, producer: str, field: str
) -> tuple[SettingsProblem, ...]:
    """Check that a producer directory exists and can be listed and read.

    Parameters
    ----------
    store : StoreConfig
        Store owning the directory.
    producer : str
        Producer id, a key of ``store.roots()``.
    field : str
        Settings location reported with a problem.

    Returns
    -------
    tuple[SettingsProblem, ...]
        At most one problem; nothing is created in the directory.
    """
    root = store.roots()[producer]
    values = {"producer": producer, "store": store.id, "path": root}
    code = _directory_problem(root, prefix="root")
    if code is None:
        return ()
    return (SettingsProblem(code, field, MESSAGES[code].format(**values)),)


def check_project_dir(path: Path, field: str) -> tuple[SettingsProblem, ...]:
    """Check that a project directory exists and can be listed and read."""
    code = _directory_problem(path, prefix="project_dir")
    if code is None:
        return ()
    return (SettingsProblem(code, field, MESSAGES[code].format(path=path)),)


def _directory_problem(path: Path, *, prefix: str) -> str | None:
    try:
        exists = path.exists()
        is_dir = path.is_dir()
    except OSError:
        exists = is_dir = False
    if not exists:
        return f"{prefix}_missing"
    if not is_dir:
        return f"{prefix}_not_directory"
    if not os.access(path, os.R_OK | os.X_OK):
        return f"{prefix}_unreadable"
    return None


def check_nesting(roots: Sequence[tuple[str, Path]]) -> tuple[SettingsProblem, ...]:
    """Reject producer directories that are equal to or inside another one.

    Parameters
    ----------
    roots : Sequence[tuple[str, Path]]
        Settings location and producer directory pairs of all stores.

    Returns
    -------
    tuple[SettingsProblem, ...]
        One ``root_nested`` problem per nested directory.
    """
    resolved = [(field, root, Path(os.path.realpath(root))) for field, root in roots]
    problems: list[SettingsProblem] = []
    for index, (field, root, real) in enumerate(resolved):
        for other_index, (_, other, other_real) in enumerate(resolved):
            if other_index == index or not real.is_relative_to(other_real):
                continue
            if real == other_real and other_index > index:
                continue
            message = MESSAGES["root_nested"].format(path=root, other=other)
            problems.append(SettingsProblem("root_nested", field, message))
            break
    return tuple(problems)


def _probe_root(
    store: StoreConfig, producer: str, field: str, registry: SourceRegistryView
) -> tuple[SettingsProblem, ...]:
    state = registry.probe(producer, store.roots()[producer])
    if state.status == "available":
        return ()
    message = MESSAGES["root_source"].format(
        producer=producer,
        store=store.id,
        status=MESSAGES[f"source_status_{state.status}"],
    )
    return (
        SettingsProblem(
            f"source_{state.status}", field, with_detail(message, state.detail)
        ),
    )


class ConfigStore:
    """Read and atomically write the TOML settings file.

    Parameters
    ----------
    path : Path
        Settings file, normally ``AppPaths.default().config_file``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        """Return whether the settings file exists."""
        return self.path.is_file()

    def load(self) -> AppSettings:
        """Read the settings file, or defaults when it does not exist.

        Raises
        ------
        SettingsValidationError
            If the file is not valid TOML or contains invalid settings.
        """
        try:
            with self.path.open("rb") as file:
                data = tomllib.load(file)
        except FileNotFoundError:
            return AppSettings()
        except tomllib.TOMLDecodeError as error:
            message = MESSAGES["settings_invalid_toml"].format(
                path=self.path, detail=error
            )
            raise SettingsValidationError(
                [SettingsProblem("invalid_toml", "", message)]
            ) from error
        return parse_settings(data)

    def save(self, settings: AppSettings) -> None:
        """Write settings atomically: a reader sees the old or the new file."""
        write_text_atomic(self.path, dump_settings(settings))


def write_text_atomic(path: Path, text: str) -> None:
    """Write a UTF-8 text file so that a reader sees the old or the new file.

    The text goes to a temporary file in the same directory, which is
    flushed to the disk and then renamed over ``path``; a failure leaves the
    old file as it was.

    Parameters
    ----------
    path : Path
        File to write; its directory is created when missing.
    text : str
        Content, written with LF line endings.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    if sys.platform == "win32":  # pragma: no cover - directories cannot be opened
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def dump_settings(settings: AppSettings) -> str:
    """Serialize settings to TOML that ``ConfigStore.load`` reads back equal.

    Parameters
    ----------
    settings : AppSettings
        Settings to serialize.

    Returns
    -------
    str
        TOML text with scalar settings first and one table per store and
        basemap.
    """
    data = settings.model_dump(mode="json")
    lines: list[str] = []
    tables: list[tuple[str, list[dict[str, object]]]] = []
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            tables.append((key, value))
        else:
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    for key, rows in tables:
        for row in rows:
            lines.extend(("", f"[[{_toml_key(key)}]]"))
            lines.extend(
                f"{_toml_key(name)} = {_toml_value(value)}"
                for name, value in row.items()
            )
    return "\n".join(lines) + "\n"


def _toml_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return _toml_string(key)


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(
            f"{_toml_key(str(key))} = {_toml_value(item)}"
            for key, item in value.items()
        )
        return "{ " + items + " }" if items else "{}"
    raise TypeError(f"Unsupported settings value: {value!r}")


_TOML_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _toml_string(value: str) -> str:
    escaped = "".join(
        _TOML_ESCAPES.get(char)
        or (f"\\u{ord(char):04X}" if ord(char) < 0x20 or ord(char) == 0x7F else char)
        for char in value
    )
    return f'"{escaped}"'


type SettingsListener = Callable[[AppSettings, AppSettings], None]


class SettingsService:
    """Hold the settings in effect, validate changes, and notify subscribers.

    Parameters
    ----------
    store : ConfigStore
        Settings file.
    registry : SourceRegistryView
        Producer plugins used to probe new store directories.
    """

    def __init__(self, store: ConfigStore, registry: SourceRegistryView) -> None:
        self._store = store
        self._registry = registry
        self._lock = threading.Lock()
        self._settings = store.load()
        self._listeners: list[SettingsListener] = []

    def get(self) -> AppSettings:
        """Return the settings in effect."""
        return self._settings

    def update(self, settings: AppSettings) -> AppSettings:
        """Validate, save, and publish new settings.

        Parameters
        ----------
        settings : AppSettings
            Complete new settings (``PUT /settings`` replaces all of them).

        Returns
        -------
        AppSettings
            The settings now in effect.

        Raises
        ------
        SettingsValidationError
            If a new or moved directory is unusable or directories are
            nested; the file and the settings in effect stay unchanged.
        """
        with self._lock:
            previous = self._settings
            problems = validate_settings(settings, self._registry, previous=previous)
            if problems:
                raise SettingsValidationError(problems)
            self._store.save(settings)
            self._settings = settings
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(previous, settings)
            except Exception:
                logger.exception("Settings listener %r failed", listener)
        return settings

    def subscribe(self, listener: SettingsListener) -> Callable[[], None]:
        """Call ``listener(previous, current)`` after every saved change.

        Returns
        -------
        Callable[[], None]
            Removes the subscription.
        """
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe
