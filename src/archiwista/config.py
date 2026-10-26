"""Local configuration: TOML settings, local data paths, and settings service."""

import ipaddress
import logging
import os
import re
import sys
import tempfile
import threading
import tomllib
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
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
    ValidationInfo,
    field_validator,
    model_validator,
)

from archiwista.errors import ArchiwistaError
from archiwista.messages import join, message, with_detail
from archiwista.sources import SourceState
from archiwista.sources.markers import store_around, store_below

logger = logging.getLogger(__name__)

APP_NAME = "archiwista"
CONFIG_FILE_NAME = "config.toml"
DEFAULT_PORT = 8090
DEFAULT_SCAN_THREADS = 8
DEFAULT_SCAN_INTERVAL_LOCAL_MIN = 5
DEFAULT_SCAN_INTERVAL_SHARE_MIN = 15
DEFAULT_FULL_SCAN_INTERVAL_H = 24
# Preview cache limit in GB of 1024**3 bytes (SPEC 5.7: 20 GB, LRU).
DEFAULT_PREVIEW_CACHE_LIMIT_GB = 20
SHARE_FILESYSTEMS = frozenset({"cifs", "smb3", "smbfs", "nfs", "nfs4"})
MOUNTINFO_PATH = Path("/proc/self/mountinfo")
# A project's data folder unless the settings name another (decision 8).
OWN_DATA_DIR_NAME = "dane"
# Network jobs one person runs at once, their agents' included (ADR-047).
DEFAULT_NETWORK_JOBS_PER_PERSON = 2
DEFAULT_ACTION_LOG_RETENTION_DAYS = 365
# A trusted proxy of team mode is an address or a network of at most this many
# addresses (IPv4 /24, IPv6 /120), so a mistyped prefix cannot trust a whole
# network (ADR-046).
MAX_PROXY_ADDRESSES = 256
# The headers a proxy may not name the person in: the request's own, the
# forwarded ones Archiwista reads and its own (ADR-046).
_RESERVED_HEADERS = frozenset({"host", "cookie", "authorization", "origin"})
_RESERVED_HEADER_PREFIXES = ("x-forwarded-", "x-archiwista-")
# A header name is an HTTP token (RFC 9110, 5.6.2).
_HTTP_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
# A host name of an origin: labels of letters, digits and hyphens (punycode too).
_HOST_NAME = re.compile(
    r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*"
)
HTTPS_PORT = 443

type StoreKind = Literal["local", "share"]
type BasemapKind = Literal["xyz", "wms", "vector"]
type OwnFolderSource = Literal["default", "setting"]
type OwnFolderReason = Literal["inside_store", "inside_app_data", "overlaps_project"]
# Why a directory of the settings cannot be used; the suffix of a problem code.
type DirectoryProblem = Literal["missing", "not_directory", "unreadable"]
# Visibility of a project without its own access entry (A-ADR-029): everyone
# sees it, or administrators only until someone shares it.
type DefaultProjectVisibility = Literal["public", "private"]
type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

DEFAULT_PROJECT_VISIBILITIES: tuple[DefaultProjectVisibility, ...] = (
    "public",
    "private",
)

_STORE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
# Producers whose directory a store can name, in the order of its settings: the
# first one found decides the detected kind and the order of ``roots()``.
STORE_PRODUCERS = ("kartograf", "imgw")


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

    @property
    def previews_dir(self) -> Path:
        """Preview cache: objects by content and their LRU accounting."""
        return self.data_dir / "previews"

    def source_cache_dir(self, producer: str) -> Path:
        """Return the local cache directory owned by one producer plugin."""
        return self.cache_dir / producer


def _require_absolute(path: Path) -> Path:
    if not (path.is_absolute() or _is_unc(str(path))):
        raise ValueError(message("settings.path_not_absolute"))
    return path


def _require_text(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(message("settings.empty_text"))
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
    kartograf : Path or None
        Store root of Kartograf: the directory that holds ``kartograf-store.json``
        and the product directories (usually called ``data``).
    imgw : Path or None
        IMGWTools store root, the directory that holds ``imgw-store.json``.
        At least one of the two directories is required; one of them left out
        is ``None``, never an empty path.
    kind : {"local", "share"}
        Detected from the file system when omitted; editable afterwards.
    path_aliases : dict[str, str]
        Local path prefix mapped to the same share's prefix on another
        computer, e.g. ``{"/mnt/nas/": "Z:\\"}``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    kartograf: AbsolutePath | None = None
    imgw: AbsolutePath | None = None
    kind: StoreKind
    path_aliases: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _require_a_directory(cls, data: object) -> object:
        # Before the kind is looked for: a store without a directory has none.
        if isinstance(data, Mapping) and all(
            data.get(producer) is None for producer in STORE_PRODUCERS
        ):
            raise ValueError(message("settings.store_needs_directory"))
        return data

    @model_validator(mode="before")
    @classmethod
    def _detect_kind(cls, data: object) -> object:
        if isinstance(data, Mapping) and data.get("kind") is None:
            for producer in STORE_PRODUCERS:
                root = data.get(producer)
                if isinstance(root, str | Path):
                    return {**data, "kind": detect_store_kind(Path(root))}
        return data

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if _STORE_ID.fullmatch(value) is None:
            raise ValueError(message("settings.store_id_pattern"))
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
        """Return the configured producer directories keyed by producer id."""
        found = {"kartograf": self.kartograf, "imgw": self.imgw}
        return {producer: root for producer, root in found.items() if root is not None}

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
    kind : {"xyz", "wms", "vector"}
        Raster tile template with ``{z}/{x}/{y}``, a WMS endpoint, or the
        TileJSON of vector tiles in the OpenMapTiles schema, drawn with
        Archiwista's own grey style.
    url : str
        Tile template, WMS address or TileJSON address (http or https). The
        tiles of a TileJSON must come from its origin: the page's CSP allows
        only the origin of this address, and the browser rejects mismatched
        tiles with a basemap warning.
    attribution : str
        Attribution text required by the provider.
    grayscale : bool
        Render raster tiles in grey so data outlines stay readable (the
        vector style is grey already).
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
            raise ValueError(message("settings.basemap_url"))
        tokens = [token in self.url for token in ("{z}", "{x}", "{y}")]
        if self.kind == "xyz" and not all(tokens):
            raise ValueError(message("settings.basemap_xyz"))
        if self.kind == "vector" and any(tokens):
            raise ValueError(message("settings.basemap_vector"))
        return self

    @property
    def origin(self) -> str:
        """Scheme, host, and port of the provider, e.g. for a CSP source list."""
        parts = urlsplit(self.url)
        return f"{parts.scheme}://{parts.netloc}"


# Both serve tiles to requests without a Referer (the app sends
# Referrer-Policy: no-referrer) and print Polish names, unlike BKG
# TopPlusOpen ("Gdańsk / Danzig"). OpenFreeMap's vector tiles carry
# `name:pl` for the whole planet and need no key; GUGiK's OSM raster covers
# Poland only and is coloured, so the client desaturates it.
DEFAULT_BASEMAPS: tuple[BasemapConfig, ...] = (
    BasemapConfig(
        name="OpenFreeMap szary",
        kind="vector",
        url="https://tiles.openfreemap.org/planet",
        attribution="OpenFreeMap © OpenMapTiles Data from OpenStreetMap",
    ),
    BasemapConfig(
        name="OSM GUGiK szary (tylko Polska)",
        kind="xyz",
        url="https://mapy.geoportal.gov.pl/wss/ext/OSM/BaseMap/wmts/osm_3857/GLOBAL_WEBMERCATOR/{z}/{x}/{y}.png",
        attribution="© OpenStreetMap contributors, GUGiK",
        grayscale=True,
    ),
)


def _normalize_origin(value: str) -> str:
    """Return a team's origin lower-case and without the port 443, or refuse it.

    An origin is ``https://``, a host name or an IP address, and an optional
    port: nothing else, so that it compares with a browser's ``Origin``.
    """
    text = value.lower()
    parts = urlsplit(text)
    try:
        port = parts.port
    except ValueError:
        port = 0
    host = parts.hostname or ""
    bracketed = f"[{host}]" if ":" in host else host
    given = f"https://{bracketed}" + ("" if port is None else f":{port}")
    if text != given or port == 0 or not _valid_host(host):
        raise ValueError(message("settings.team_origin"))
    if port == HTTPS_PORT:
        return f"https://{bracketed}"
    return given


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return _HOST_NAME.fullmatch(host) is not None and not host.isdigit()
    return True


def _check_proxy(value: str) -> str:
    """Return a trusted proxy (an address or a small network), or refuse it."""
    text = value.strip()
    try:
        network = ipaddress.ip_network(text, strict=False)
    except ValueError:
        network = None
    if network is None or network.num_addresses > MAX_PROXY_ADDRESSES:
        raise ValueError(message("settings.team_proxy", limit=MAX_PROXY_ADDRESSES))
    return text


def _reserved_header(name: str) -> bool:
    """Return whether a proxy may not name the person in the header ``name``."""
    lowered = name.lower()
    return lowered in _RESERVED_HEADERS or lowered.startswith(_RESERVED_HEADER_PREFIXES)


class TeamSettings(BaseModel):
    """Team mode: the table ``[team]`` of the configuration file (ADR-046).

    The server reads it when it starts; the API neither shows nor changes
    it, so no session can widen the server's exposure.

    Parameters
    ----------
    enabled : bool
        Team mode: people sign in, every request comes over TLS, and the
        server may listen beyond ``127.0.0.1``.
    origin : str or None
        The address people open: ``https``, a host and an optional port,
        nothing else; kept lower-case and without the port 443. Required
        when ``enabled``.
    tls_cert, tls_key : Path or None
        TLS in the server: the certificate chain and its unencrypted private
        key (PEM files); both or neither.
    trusted_proxies : tuple[str, ...]
        Reverse proxies whose ``X-Forwarded-For``, ``X-Forwarded-Proto`` and
        ``proxy_user_header`` are believed: addresses, or networks of at most
        256 addresses (IPv4 ``/24``, IPv6 ``/120``).
    proxy_user_header : str or None
        Header in which a trusted proxy names the person (an HTTP token, not
        ``Host``, ``Cookie``, ``Authorization``, ``Origin``, an
        ``X-Forwarded-*`` or ``X-Archiwista-*`` name); needs
        ``trusted_proxies``.
    proxy_autocreate : bool
        Create a missing account, without roles, when the proxy names it;
        needs ``proxy_user_header``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    origin: str | None = Field(default=None, validate_default=True)
    tls_cert: AbsolutePath | None = None
    tls_key: AbsolutePath | None = Field(default=None, validate_default=True)
    trusted_proxies: tuple[Annotated[str, AfterValidator(_check_proxy)], ...] = ()
    proxy_user_header: str | None = Field(default=None, validate_default=True)
    proxy_autocreate: bool = Field(default=False, validate_default=True)

    # A check of two fields runs on the second one, so that the problem names
    # it (``team.<name>``); it is skipped when the first one is itself invalid.

    @field_validator("origin")
    @classmethod
    def _check_origin(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None:
            return _normalize_origin(value)
        if info.data.get("enabled"):
            raise ValueError(message("settings.team_origin"))
        return None

    @field_validator("tls_key")
    @classmethod
    def _check_tls_pair(cls, value: Path | None, info: ValidationInfo) -> Path | None:
        if "tls_cert" in info.data and (value is None) != (
            info.data["tls_cert"] is None
        ):
            raise ValueError(message("settings.team_tls_pair"))
        return value

    @field_validator("proxy_user_header")
    @classmethod
    def _check_proxy_header(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        without_proxies = (
            "trusted_proxies" in info.data and not info.data["trusted_proxies"]
        )
        if (
            _HTTP_TOKEN.fullmatch(value) is None
            or _reserved_header(value)
            or without_proxies
        ):
            raise ValueError(message("settings.team_proxy_header"))
        return value

    @field_validator("proxy_autocreate")
    @classmethod
    def _check_autocreate(cls, value: bool, info: ValidationInfo) -> bool:
        if (
            value
            and "proxy_user_header" in info.data
            and info.data["proxy_user_header"] is None
        ):
            raise ValueError(message("settings.team_proxy_autocreate"))
        return value

    def trusted_networks(self) -> tuple[IPNetwork, ...]:
        """Return the trusted proxies as networks (an address is a ``/32``)."""
        return tuple(
            ipaddress.ip_network(value, strict=False) for value in self.trusted_proxies
        )


class AppSettings(BaseModel):
    """All user settings stored in the TOML configuration file.

    Parameters
    ----------
    port : int
        Server port (on 127.0.0.1 in local mode).
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
        Online basemaps: grey OpenFreeMap vector tiles and GUGiK's OSM
        raster (Poland only) by default.
    store_write_for_all : bool
        Give everyone the store write permission, not only people with the
        ``store_writer`` role (A-ADR-029; checked from v0.3).
    default_project_visibility : {"public", "private"}
        Visibility of a project without its own access entry: everyone, or
        administrators only.
    preview_cache_limit_gb : int
        Size limit of the preview cache in GB (1024**3 bytes); past it the
        least recently used previews go (SPEC 5.7).
    preview_warm_after_scan : bool
        After a scan that indexed new versions of a store, the scheduler
        prepares the first look at them in a ``preview_warm`` job (SPEC 5.7,
        ADR-041); off by default.
    own_data_dirs : dict[str, str]
        Data folder of a project by the project directory after ``realpath``
        (its access key): absolute directories, set by an administrator.
        Without an entry a project's folder is ``<project directory>/dane``.
    network_jobs_per_person : int
        Network jobs one person (with their agents) runs at once; further
        ones wait (ADR-047).
    action_log_retention_days : int
        Days the action log keeps an entry (ADR-047).
    team : TeamSettings
        Team mode, the table ``[team]``: read when the server starts, never
        shown or changed by the API (ADR-046).
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
    basemaps: tuple[BasemapConfig, ...] = DEFAULT_BASEMAPS
    store_write_for_all: bool = False
    default_project_visibility: DefaultProjectVisibility = "public"
    preview_cache_limit_gb: int = Field(
        default=DEFAULT_PREVIEW_CACHE_LIMIT_GB, ge=1, le=10_000
    )
    preview_warm_after_scan: bool = False
    own_data_dirs: dict[str, str] = Field(default_factory=dict)
    network_jobs_per_person: int = Field(
        default=DEFAULT_NETWORK_JOBS_PER_PERSON, ge=1, le=10
    )
    action_log_retention_days: int = Field(
        default=DEFAULT_ACTION_LOG_RETENTION_DAYS, ge=30, le=3650
    )
    team: TeamSettings = Field(default_factory=TeamSettings)

    @field_validator("default_project_visibility", mode="before")
    @classmethod
    def _check_default_visibility(cls, value: object) -> object:
        if value not in DEFAULT_PROJECT_VISIBILITIES:
            raise ValueError(message("settings.default_visibility"))
        return value

    @field_validator("stores")
    @classmethod
    def _check_store_ids(
        cls, value: tuple[StoreConfig, ...]
    ) -> tuple[StoreConfig, ...]:
        _require_unique([store.id for store in value], "settings.duplicate_store")
        return value

    @field_validator("basemaps")
    @classmethod
    def _check_basemap_names(
        cls, value: tuple[BasemapConfig, ...]
    ) -> tuple[BasemapConfig, ...]:
        _require_unique(
            [basemap.name for basemap in value], "settings.duplicate_basemap"
        )
        return value

    @field_validator("own_data_dirs")
    @classmethod
    def _check_own_data_dirs(cls, value: dict[str, str]) -> dict[str, str]:
        for project, folder in value.items():
            _require_absolute(Path(project))
            _require_absolute(Path(folder))
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

    @property
    def preview_cache_limit_bytes(self) -> int:
        """Return the preview cache limit in bytes."""
        return self.preview_cache_limit_gb * 1024**3

    def own_data_dir(self, project: str) -> tuple[Path, OwnFolderSource]:
        """Return a project's data folder and where it comes from.

        Parameters
        ----------
        project : str
            The project directory after ``realpath`` (``access_key``).

        Returns
        -------
        tuple[Path, {"default", "setting"}]
            The folder of ``own_data_dirs``, or ``<project>/dane``.
        """
        folder = self.own_data_dirs.get(project)
        if folder is not None:
            return Path(folder), "setting"
        return Path(project) / OWN_DATA_DIR_NAME, "default"


def _require_unique(values: Sequence[str], key: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(message(key, value=value))
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
        Description for the user, a catalog message.
    reason : str or None, optional
        Machine code of the cause a producer gave for a directory it refuses
        (``SourceState.reason``, e.g. ``"no_marker"``).
    hint : str or None, optional
        One line telling how to fix it, a catalog message, when it is known.
    """

    code: str
    field: str
    message: str
    reason: str | None = None
    hint: str | None = None


class SettingsValidationError(ArchiwistaError):
    """Settings are malformed or point at unusable directories.

    A ``validation_error`` with the reason ``invalid_settings``; the problems
    are ``details["problems"]``: ``code``, ``field`` and ``message`` of each,
    and its ``reason`` and ``hint`` when it has them.
    """

    default_code = "validation_error"
    default_reason = "invalid_settings"

    def __init__(self, problems: Sequence[SettingsProblem]) -> None:
        self.problems = tuple(problems)
        super().__init__(
            join([problem.message for problem in self.problems]),
            details={"problems": [_problem_details(item) for item in self.problems]},
        )


def _problem_details(problem: SettingsProblem) -> dict[str, object]:
    """Return a problem as the JSON of ``details["problems"]``."""
    details: dict[str, object] = {
        "code": problem.code,
        "field": problem.field,
        "message": problem.message,
    }
    if problem.reason is not None:
        details["reason"] = problem.reason
    if problem.hint is not None:
        details["hint"] = problem.hint
    return details


_PYDANTIC_KEYS = {
    "missing": "settings.missing",
    "extra_forbidden": "settings.unknown_key",
    "int_type": "settings.not_integer",
    "int_parsing": "settings.not_integer",
    "int_from_float": "settings.not_integer",
    "bool_type": "settings.not_boolean",
    "bool_parsing": "settings.not_boolean",
    "string_type": "settings.not_text",
    "tuple_type": "settings.not_list",
    "list_type": "settings.not_list",
}


def parse_settings(data: Mapping[str, object]) -> AppSettings:
    """Validate raw settings data, describing the problems in catalog messages.

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
        detail = _validator_text(ctx.get("error", message("settings.bad_value")))
    elif kind in ("greater_than_equal", "greater_than"):
        limit = ctx.get("ge", ctx.get("gt"))
        detail = message("settings.too_small", limit=limit)
    elif kind in ("less_than_equal", "less_than"):
        limit = ctx.get("le", ctx.get("lt"))
        detail = message("settings.too_large", limit=limit)
    else:
        detail = message(_PYDANTIC_KEYS.get(kind, "settings.bad_value"))
    return SettingsProblem(
        code="invalid_value",
        field=field,
        message=message("settings.invalid_value", field=field, detail=detail),
    )


def _validator_text(error: object) -> str:
    """Return what a validator said: its catalog message, else the error's text."""
    first = error.args[0] if isinstance(error, BaseException) and error.args else None
    return first if isinstance(first, str) else str(error)


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
        Settings in effect; directories unchanged since then are neither
        probed nor searched for store markers, so a disconnected share does
        not block unrelated edits.

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
    unchanged: set[str] = set()
    for index, store in enumerate(settings.stores):
        for producer, root in store.roots().items():
            field = f"stores[{index}].{producer}"
            labelled.append((field, root))
            if old_roots.get((store.id, producer)) == root:
                unchanged.add(field)
                continue
            root_problems = check_store_root(store, producer, field)
            problems.extend(
                root_problems or _probe_root(store, producer, field, registry)
            )
    problems.extend(check_nesting(labelled, skip_markers=unchanged))
    for index, path in enumerate(settings.project_dirs):
        if path not in old_project_dirs:
            problems.extend(check_project_dir(path, f"project_dirs[{index}]"))
    problems.extend(check_own_data_dirs(settings, previous=previous))
    return tuple(problems)


def check_own_data_dirs(
    settings: AppSettings, *, previous: AppSettings | None = None
) -> tuple[SettingsProblem, ...]:
    """Check the data folders of ``own_data_dirs`` (decision 8).

    A new or changed folder must be an existing, readable directory. Every
    folder must lie outside the stores' producer directories and apart from
    the other folders of the settings (``own_folder_conflict``). The
    folders of projects without an entry and Archiwista's data directory
    are not known here: the service setting a folder and every scan check
    them too.

    Parameters
    ----------
    settings : AppSettings
        Candidate settings.
    previous : AppSettings or None, optional
        Settings in effect; their folders are not checked on the disk again.

    Returns
    -------
    tuple[SettingsProblem, ...]
        At most one problem per folder.
    """
    old = previous.own_data_dirs if previous is not None else {}
    stores = [root for store in settings.stores for root in store.roots().values()]
    problems: list[SettingsProblem] = []
    for project, folder in settings.own_data_dirs.items():
        field = f"own_data_dirs.{project}"
        if old.get(project) != folder:
            problem = _directory_problem(Path(folder))
            if problem is not None:
                text = message(f"own.data_dir_{problem}", project=project, path=folder)
                code = f"own_data_dir_{problem}"
                problems.append(SettingsProblem(code, field, text))
                continue
        others = [
            Path(other)
            for key, other in settings.own_data_dirs.items()
            if key != project
        ]
        conflict = own_folder_conflict(
            Path(folder), stores=stores, app_data=None, others=others
        )
        if conflict is not None:
            reason, directory = conflict
            text = message(
                f"own.data_dir_{reason}", project=project, path=folder, other=directory
            )
            code = f"own_data_dir_{reason}"
            problems.append(SettingsProblem(code, field, text))
    return tuple(problems)


def own_folder_conflict(
    folder: Path,
    *,
    stores: Iterable[Path],
    app_data: Path | None,
    others: Iterable[Path],
) -> tuple[OwnFolderReason, Path] | None:
    """Return why a data folder may not be used, or ``None`` (decision 8).

    Paths are compared after ``realpath`` (a folder that does not exist is
    resolved as far as it does), so a symbolic link does not hide a store.
    A snapshot must never land in a store, a file belongs to one project
    (so to one visibility), and Archiwista's own data is never read as a
    project's.

    Parameters
    ----------
    folder : Path
        The data folder.
    stores : Iterable[Path]
        Producer directories of the stores: the folder must not be one of
        them or lie inside one.
    app_data : Path or None
        Archiwista's data directory (``AppPaths.data_dir``): the folder must
        neither contain it nor lie in it.
    others : Iterable[Path]
        Data folders of the other projects: the folder must neither contain
        one of them nor lie in one.

    Returns
    -------
    tuple[OwnFolderReason, Path] or None
        ``inside_store``, ``inside_app_data`` or ``overlaps_project`` with
        the directory in the way, checked in this order.
    """
    real = Path(os.path.realpath(folder))
    for store in stores:
        if real.is_relative_to(os.path.realpath(store)):
            return "inside_store", store
    if app_data is not None and _overlap(real, Path(os.path.realpath(app_data))):
        return "inside_app_data", app_data
    for other in others:
        if _overlap(real, Path(os.path.realpath(other))):
            return "overlaps_project", other
    return None


def _overlap(first: Path, second: Path) -> bool:
    """Whether two real directories are one, or one lies inside the other."""
    return first.is_relative_to(second) or second.is_relative_to(first)


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
    problem = _directory_problem(root)
    if problem is None:
        return ()
    text = message(f"root.{problem}", producer=producer, store=store.id, path=root)
    return (SettingsProblem(f"root_{problem}", field, text),)


def check_project_dir(path: Path, field: str) -> tuple[SettingsProblem, ...]:
    """Check that a project directory exists and can be listed and read."""
    problem = _directory_problem(path)
    if problem is None:
        return ()
    text = message(f"project.dir_{problem}", path=path)
    return (SettingsProblem(f"project_dir_{problem}", field, text),)


def _directory_problem(path: Path) -> DirectoryProblem | None:
    try:
        exists = path.exists()
        is_dir = path.is_dir()
    except OSError:
        exists = is_dir = False
    if not exists:
        return "missing"
    if not is_dir:
        return "not_directory"
    if not os.access(path, os.R_OK | os.X_OK):
        return "unreadable"
    return None


def check_nesting(
    roots: Sequence[tuple[str, Path]], *, skip_markers: Collection[str] = ()
) -> tuple[SettingsProblem, ...]:
    """Reject producer directories that are nested in a store (DEV-19.14).

    A directory is nested when it is equal to or inside another directory of
    the settings, which is judged by the paths alone, or when it lies inside a
    store that the settings do not name or holds one: an ancestor holds the
    marker file of a producer (``sources/markers.py``), or a directory within
    ``NESTING_DEPTH`` levels below it does (no link is followed). The
    producer's own writer looks at the whole tree below a directory, which
    holds tens of thousands of slots in a large store; this check stays
    bounded, so a store deeper down is found there.

    Parameters
    ----------
    roots : Sequence[tuple[str, Path]]
        Settings location and producer directory pairs of all stores.
    skip_markers : Collection[str], optional
        Settings locations of the directories whose surroundings are not
        searched for markers (unchanged directories: a share that is not
        connected must not block other edits).

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
            text = message("root.nested", path=root, other=other)
            problems.append(SettingsProblem("root_nested", field, text))
            break
        else:
            if field not in skip_markers:
                problems.extend(_nested_by_markers(field, root, real))
    return tuple(problems)


def _nested_by_markers(
    field: str, root: Path, real: Path
) -> tuple[SettingsProblem, ...]:
    around = store_around(real)
    if around is not None:
        ancestor, marker = around
        text = message("root.in_store", path=root, other=ancestor, marker=marker)
        return (SettingsProblem("root_nested", field, text),)
    below = store_below(real)
    if below is not None:
        folder, marker = below
        text = message("root.holds_store", path=root, other=folder, marker=marker)
        return (SettingsProblem("root_nested", field, text),)
    return ()


def _probe_root(
    store: StoreConfig, producer: str, field: str, registry: SourceRegistryView
) -> tuple[SettingsProblem, ...]:
    state = registry.probe(producer, store.roots()[producer])
    if state.status == "available":
        return ()
    text = message(
        "root.source",
        producer=producer,
        store=store.id,
        status=message(f"source.status_{state.status}"),
    )
    return (
        SettingsProblem(
            f"source_{state.status}",
            field,
            with_detail(text, state.detail),
            reason=state.reason,
            hint=state.hint,
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
            text = message("settings.invalid_toml", path=self.path, detail=error)
            raise SettingsValidationError(
                [SettingsProblem("invalid_toml", "", text)]
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
        TOML text with scalar settings first, then the table ``[team]`` unless
        it holds the defaults, and one table per store and basemap.
    """
    data = settings.model_dump(mode="json")
    team: dict[str, object] = data.pop("team")
    lines: list[str] = []
    tables: list[tuple[str, list[dict[str, object]]]] = []
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            tables.append((key, value))
        elif value is not None:
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    if settings.team != TeamSettings():
        lines.extend(("", "[team]"))
        lines.extend(
            f"{_toml_key(name)} = {_toml_value(value)}"
            for name, value in team.items()
            if value is not None
        )
    for key, rows in tables:
        for row in rows:
            lines.extend(("", f"[[{_toml_key(key)}]]"))
            lines.extend(
                f"{_toml_key(name)} = {_toml_value(value)}"
                for name, value in row.items()
                if value is not None
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
