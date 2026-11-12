"""The settings Archiwista shares with the Nogat tools: ``nogat.toml`` (A-ADR-053).

The tools of the ecosystem keep their shared settings in one file, ``nogat.toml``
(Nogat ECO-028, DEV-18.1): the path in ``NOGAT_CONFIG``, else the file in the user
configuration directory of ``nogat`` (``platformdirs.user_config_path("nogat")``).
Archiwista keeps its own settings in its ``config.toml`` and reads four keys of
that file, each from the table ``[archiwista]`` before the table ``[nogat]``. A
value comes from the first of: Archiwista's own setting, ``nogat.toml``, the
built-in default.

- ``data_dir``: Archiwista's local data (the index, the state database, the jobs,
  the areas) lies in ``<data_dir>/archiwista``, as each tool's data lies in
  ``<data_dir>/<tool>`` (DEV-18.2); by default in the user data directory of
  ``archiwista``. The producers find their default store roots,
  ``<data_dir>/kartograf`` and ``<data_dir>/obserwator``, in the same file.
- ``cache_dir``: the caches (the preview cache ``previews/`` and the producers'
  ``cache/``) lie in ``<cache_dir>/archiwista``; by default in the local data
  directory.
- ``lang``: the language of the text for a person on the command line, ``pl`` or
  ``en``; Polish by default. Archiwista's own settings come first: ``--json``
  output is English, and the API follows each request's ``Accept-Language``
  (English without it).
- ``gui``: the GUIs of the deployment, the table of their addresses by registry
  name (``[nogat.gui]``, Nogat DEV-15.4, A-ADR-054): an address is absolute
  (``https://hydrolog.example/``) or a path on this host (``/hydrolog/``). The
  server gives it to the interface (``GET /api/v1/session``), whose menu
  „Aplikacje” lists the GUIs; no default, so without it the menu is not drawn.

The ``NOGAT_<KEY>`` variables are not read: the file is the one place every
process of a person reads, while a variable left in one shell would start the
server on another data directory, whose state database (accounts, sharing,
the action log) cannot be rebuilt. The file is read with ``tomllib`` and
Archiwista works without it. A file that cannot be used (unreadable, not UTF-8
text, not TOML, a table that is not one, a value of these keys that is not
valid, or a file ``NOGAT_CONFIG`` names that does not exist) gives no value:
``archiwista doctor`` reports it and every other command refuses to run, so
Archiwista never starts on another directory or with another menu than the file
means.
"""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, Self, cast

import platformdirs

from archiwista.messages import LANGS, Lang, Message, message

TOOL: Final = "archiwista"
CONFIG_ENV: Final = "NOGAT_CONFIG"
FILE_NAME: Final = "nogat.toml"
TABLES: Final = (TOOL, "nogat")
"""The tables read, in their order: Archiwista's own before the shared one."""
PERSON_LANG: Final[Lang] = "pl"
"""The language of the text for a person when ``nogat.toml`` gives none."""

type SharedKey = Literal["data_dir", "cache_dir", "lang"]
SHARED_KEYS: Final[tuple[SharedKey, ...]] = ("data_dir", "cache_dir", "lang")
GUI_KEY: Final = "gui"
"""The table of the GUIs' addresses (Nogat DEV-15.4, DEV-18.1)."""


@dataclass(frozen=True, slots=True)
class SharedValue:
    """A key of ``nogat.toml`` as Archiwista uses it.

    Attributes
    ----------
    key : {"data_dir", "cache_dir", "lang"}
        The key.
    value : str
        The directory (absolute, ``~`` expanded) or the language.
    table : {"archiwista", "nogat"}
        The table of the file that gave it.
    """

    key: SharedKey
    value: str
    table: str

    @property
    def name(self) -> str:
        """Return the key as the file writes it, e.g. ``[nogat] data_dir``."""
        return f"[{self.table}] {self.key}"


@dataclass(frozen=True, slots=True)
class SharedGui:
    """The table ``gui`` of ``nogat.toml``: the GUIs of the deployment (A-ADR-054).

    Attributes
    ----------
    addresses : Mapping of str to str
        Each GUI's address by its registry name, in the file's order, as the
        file writes them (spaces around an address left out): absolute, or a
        path on this host. The interface's menu keeps the http and https ones.
    table : {"archiwista", "nogat"}
        The table of the file that gave it.
    """

    addresses: Mapping[str, str]
    table: str

    @property
    def name(self) -> str:
        """Return the table as the file writes it, e.g. ``[nogat] gui``."""
        return f"[{self.table}] {GUI_KEY}"


@dataclass(frozen=True, slots=True)
class SharedSettings:
    """``nogat.toml`` as Archiwista read it.

    Attributes
    ----------
    path : Path
        The file: the path in ``NOGAT_CONFIG``, else the one in the user
        configuration directory of ``nogat``.
    named : bool
        Whether ``NOGAT_CONFIG`` named it.
    exists : bool
        Whether the file exists.
    problem : Message or None
        Why the file cannot be used; then ``values`` is empty and ``gui`` is
        ``None``.
    values : Mapping of str to SharedValue
        The keys the file gives, by key.
    gui : SharedGui or None
        The GUIs of the deployment, ``None`` without the table ``gui``.
    """

    path: Path
    named: bool
    exists: bool
    problem: Message | None = None
    values: Mapping[SharedKey, SharedValue] = field(default_factory=dict)
    gui: SharedGui | None = None

    @classmethod
    def read(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Read ``nogat.toml``; it never raises.

        Parameters
        ----------
        environ : Mapping of str to str or None, optional
            The environment for ``NOGAT_CONFIG``; the process's own when
            omitted.

        Returns
        -------
        SharedSettings
            The file's values, or why it cannot be used.
        """
        variables = os.environ if environ is None else environ
        given = variables.get(CONFIG_ENV, "").strip()
        named = bool(given)
        path = (
            Path(given).expanduser()
            if named
            else platformdirs.user_config_path("nogat") / FILE_NAME
        )
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            problem = (
                message("settings.shared_missing", path=path, variable=CONFIG_ENV)
                if named
                else None
            )
            return cls(path, named, exists=False, problem=problem)
        except OSError as error:
            detail = error.strerror or str(error)
            problem = message("settings.shared_unreadable", path=path, detail=detail)
            return cls(path, named, exists=True, problem=problem)
        try:
            data = tomllib.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            problem = message("settings.shared_not_utf8", path=path)
            return cls(path, named, exists=True, problem=problem)
        except tomllib.TOMLDecodeError as error:
            detail = str(error)
            problem = message("settings.shared_invalid_toml", path=path, detail=detail)
            return cls(path, named, exists=True, problem=problem)
        try:
            tables = _tables(data, path)
            values = _values(tables, path)
            gui = _gui(tables, path)
        except _UnusableError as error:
            return cls(path, named, exists=True, problem=error.problem)
        return cls(path, named, exists=True, values=values, gui=gui)

    def value(self, key: SharedKey) -> SharedValue | None:
        """Return the value the file gives for ``key``, ``None`` without one."""
        return self.values.get(key)

    @property
    def language(self) -> Lang:
        """Return the language of the text for a person: ``lang``, else Polish."""
        given = self.value("lang")
        return PERSON_LANG if given is None else cast(Lang, given.value)


class _UnusableError(Exception):
    """A table or a value of ``nogat.toml`` that Archiwista cannot use."""

    def __init__(self, problem: Message) -> None:
        super().__init__(problem)
        self.problem = problem


type _Tables = list[tuple[str, Mapping[str, object]]]


def _tables(data: Mapping[str, object], path: Path) -> _Tables:
    """Return the tables Archiwista reads, in their order; refuse one that is not."""
    tables: _Tables = []
    for table in TABLES:
        found = data.get(table, {})
        if not isinstance(found, Mapping):
            raise _UnusableError(
                message("settings.shared_not_table", path=path, table=table)
            )
        tables.append((table, cast(Mapping[str, object], found)))
    return tables


def _values(tables: _Tables, path: Path) -> dict[SharedKey, SharedValue]:
    """Return the keys the tables give, the first table's value winning."""
    values: dict[SharedKey, SharedValue] = {}
    for key in SHARED_KEYS:
        for table, entries in tables:
            if key in entries:
                text = _checked(key, entries[key], table, path)
                values[key] = SharedValue(key, text, table)
                break
    return values


def _gui(tables: _Tables, path: Path) -> SharedGui | None:
    """Return the first table's ``gui`` whole, ``None`` when no table has one."""
    for table, entries in tables:
        if GUI_KEY not in entries:
            continue
        raw = entries[GUI_KEY]
        if not isinstance(raw, Mapping):
            problem = message(
                "settings.shared_gui", path=path, table=table, value=_shown(raw)
            )
            raise _UnusableError(problem)
        addresses: dict[str, str] = {}
        for name, address in cast(Mapping[str, object], raw).items():
            text = address.strip() if isinstance(address, str) else ""
            if not text:
                problem = message(
                    "settings.shared_gui_address",
                    path=path,
                    table=table,
                    name=name,
                    value=_shown(address),
                )
                raise _UnusableError(problem)
            addresses[name] = text
        return SharedGui(addresses, table)
    return None


def _checked(key: SharedKey, raw: object, table: str, path: Path) -> str:
    """Return a usable value of ``key``, or raise ``_UnusableError``."""
    text = raw.strip() if isinstance(raw, str) else ""
    if key == "lang":
        if text.lower() in LANGS:
            return text.lower()
        problem = message(
            "settings.shared_lang", path=path, table=table, value=_shown(raw)
        )
        raise _UnusableError(problem)
    directory = Path(text).expanduser() if text else None
    if directory is not None and directory.is_absolute():
        return str(directory)
    problem = message(
        "settings.shared_directory", path=path, table=table, key=key, value=_shown(raw)
    )
    raise _UnusableError(problem)


def _shown(raw: object) -> str:
    """Return a value of the file as a person reads it in a message."""
    return raw if isinstance(raw, str) else repr(raw)
