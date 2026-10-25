"""Fake producer library of the action tests, called the way IMGWTools is.

Its catalog (``list_commands``, ``command_schema``) has two commands. A command
that works on a store takes the store root as an option of the call,
``options["root"]`` (path role ``root``), as IMGWTools does, where Kartograf
takes it by name beside the options. ``validate_command`` returns the options
as the library reads them (texts trimmed, a value of a choice in lower case),
``format_command`` writes the canonical line of a call and ``parse_command``
reads a line back. ``check_availability`` reports what a fake source has for an
area: one sheet system of 2023 complete from one campaign, another complete
from two, and 2022 partial, checked now. ``check_command`` plans a fetch of a
station's files into the store of ``options["root"]``: one current, one newer,
one missing of unknown size and one unverifiable; a station whose code starts
with ``9`` cannot be asked about its missing file, station ``999`` about none.
``run_command`` fetches them into the store (``<kind>/<station>/<file>``): a
file the store holds stays (``unchanged``), and with the plan of a check only
the plan's files to download are fetched, a file whose source changed since
the plan coming back as a stale item. While the store holds ``HOLD`` a run
waits after its first new file until the file is gone. Each of these six
appends its call to ``CALLS`` with the options it received, so a test can
tell what Archiwista passed.
"""

import hashlib
import os
import shlex
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

__version__ = "2.0.0"
PROGRAM = "standin"
# The products ``check_availability`` reports on.
AVAILABILITY_PRODUCTS = ("dem",)
# A file in the store that makes a run wait after its first new file.
HOLD = ".standin-hold"

CALLS: list[tuple[str, str, dict[str, object]]] = []


def _combination(year: int, system: str, **fields: object) -> dict[str, object]:
    """Return a combination of 1 m ASC files in EVRF2007 of the fake source."""
    return {
        "country": "PL",
        "product": "dem",
        "source": "standin_dem",
        "year": year,
        "horizontal": system,
        "resolution": "1m",
        "vertical_crs": "EVRF2007",
        "format": "ASC",
        "sheets_partial": [],
        "sheets_missing": [],
        "uncovered_m2": 0.0,
        "size_bytes": None,
        "published": None,
        **fields,
    }


def _records(campaign: str, *sheets: str, full: bool = True) -> list[dict[str, object]]:
    """Return the records of one campaign's sheets."""
    return [
        {
            "sheet": sheet,
            "campaign": campaign,
            "full_sheet": full,
            "acquisition_date": None,
            "published": None,
        }
        for sheet in sheets
    ]


# The land of the fake area: 120 km².
LAND_M2 = 120_000_000.0
_COMBINATIONS: list[dict[str, object]] = [
    _combination(
        2023,
        "PL-1992",
        campaigns=["A", "B"],
        complete=True,
        sheets_full=["S1", "S2", "S3", "S4"],
        full_m2=LAND_M2,
        sheet_records=_records("A", "S1", "S2") + _records("B", "S3", "S4"),
        campaign_coverage=[
            {"campaign": "A", "complete": False, "full_m2": 60_000_000.0},
            {"campaign": "B", "complete": False, "full_m2": 60_000_000.0},
        ],
    ),
    _combination(
        2023,
        "PL-2000",
        campaigns=["C"],
        complete=True,
        sheets_full=["T1", "T2", "T3"],
        full_m2=LAND_M2,
        sheet_records=_records("C", "T1", "T2", "T3"),
        campaign_coverage=[{"campaign": "C", "complete": True, "full_m2": LAND_M2}],
    ),
    _combination(
        2022,
        "PL-1992",
        campaigns=["D"],
        complete=False,
        sheets_full=["S1", "S2", "S3"],
        sheets_partial=["S4"],
        full_m2=69_600_000.0,
        sheet_records=_records("D", "S1", "S2", "S3") + _records("D", "S4", full=False),
        campaign_coverage=[
            {"campaign": "D", "complete": False, "full_m2": 69_600_000.0}
        ],
    ),
]

_COMMANDS: dict[str, dict[str, object]] = {
    "series fetch": {
        "summary": "Fetch the daily series of one station into the store.",
        "summary_pl": "Pobierz serię dobową jednej stacji do magazynu.",
        "writes": "add",
        "network": True,
        "check": True,
        "options": [
            {
                "name": "station",
                "type": "string",
                "required": True,
                "description": "Station code.",
            },
            {
                "name": "kind",
                "type": "string",
                "required": False,
                "enum": ["hydro", "meteo"],
                "description": "Kind of the station.",
            },
            {
                "name": "area",
                "type": "string",
                "required": False,
                "path_role": "input",
                "description": "Vector file of the area whose stations are fetched.",
            },
            {
                "name": "root",
                "type": "string",
                "required": True,
                "path_role": "root",
                "description": "Store root.",
            },
        ],
        "examples": [
            "standin series fetch --station 150160180 --kind hydro --root /data/standin"
        ],
    },
    "stations list": {
        "summary": "List the stations of one kind.",
        "summary_pl": "Wypisz stacje jednego rodzaju.",
        "writes": "none",
        "network": False,
        "check": False,
        "options": [
            {
                "name": "kind",
                "type": "string",
                "required": True,
                "enum": ["hydro", "meteo"],
                "description": "Kind of the stations.",
            }
        ],
        "examples": ["standin stations list --kind meteo"],
    },
}


class ValidationError(Exception):
    """A call the library refuses; ``option`` names the option at fault."""

    code = "validation_error"

    def __init__(self, message: str, *, option: str | None = None) -> None:
        super().__init__(message)
        self.option = option


def list_commands() -> list[str]:
    """Return the names of the commands, in the order of the catalog."""
    return list(_COMMANDS)


def command_schema(command: str) -> dict[str, object]:
    """Return the description of one command."""
    if command not in _COMMANDS:
        raise ValidationError(f"unknown command {command!r}", option="command")
    return _COMMANDS[command]


def validate_command(
    command: str, /, *, options: Mapping[str, object]
) -> dict[str, object]:
    """Check a call; return its options as the library reads them."""
    CALLS.append(("validate_command", command, dict(options)))
    return _checked(command, options)


def format_command(command: str, /, *, options: Mapping[str, object]) -> str:
    """Return the canonical line of a call: its options in the catalog's order."""
    CALLS.append(("format_command", command, dict(options)))
    checked = _checked(command, options)
    words = [PROGRAM, *command.split()]
    for name, value in checked.items():
        words += [f"--{name.replace('_', '-')}", str(value)]
    return shlex.join(words)


def parse_command(line: str) -> tuple[str, dict[str, object]]:
    """Read a command line into its command and its options (texts)."""
    CALLS.append(("parse_command", line, {}))
    words = shlex.split(line)
    if words[:1] == [PROGRAM]:
        del words[0]
    command = " ".join(words[:2])
    command_schema(command)
    options: dict[str, object] = {}
    flags = words[2:]
    while flags:
        flag = flags.pop(0)
        if not flag.startswith("--") or not flags:
            raise ValidationError(f"expected --<option> <value>, got {flag!r}")
        options[flag[2:].replace("-", "_")] = flags.pop(0)
    return command, options


def check_availability(
    product: str,
    /,
    *,
    options: Mapping[str, object],
    on_notice: Callable[[str, str, str], None] | None = None,
) -> dict[str, object]:
    """Report what the fake source has for the area of ``options``, checked now.

    ``options`` holds the ``area`` (GeoJSON), its ``countries`` and
    ``refresh``; each notice goes to ``on_notice`` as ``(level, code, text)``.
    """
    CALLS.append(("check_availability", product, dict(options)))
    if product not in AVAILABILITY_PRODUCTS:
        raise ValidationError(f"no availability of {product!r}", option="product")
    notice = ("info", "index_cached", "The sheet index answered from the cache.")
    if on_notice is not None:
        on_notice(*notice)
    return {
        "schema": "standin-availability/1",
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "request": {"product": product, "countries": options["countries"]},
        "areas": [
            {
                "country": "PL",
                "crs": "EPSG:2180",
                "bounds": [566000.0, 240000.0, 578000.0, 250000.0],
                "area_m2": LAND_M2,
                "land_m2": LAND_M2,
            }
        ],
        "combinations": [dict(item) for item in _COMBINATIONS],
        "failed": [],
        "notices": [dict(zip(("level", "code", "message"), notice, strict=True))],
        "ok": True,
    }


def check_command(
    command: str,
    /,
    *,
    options: Mapping[str, object],
    on_notice: Callable[[str, str, str], None] | None = None,
) -> dict[str, object]:
    """Plan a call without running it: the files of a station in the store.

    The plan names the store ``options["root"]``; each notice goes to
    ``on_notice`` as ``(level, code, text)``.
    """
    CALLS.append(("check_command", command, dict(options)))
    checked = _checked(command, options)
    if not _COMMANDS[command]["check"]:
        raise ValidationError(f"{command} has no check", option="check")
    notice = ("info", "plan_cached", "The station index answered from the cache.")
    if on_notice is not None:
        on_notice(*notice)
    return {
        "schema": "standin-plan/1",
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "root": checked["root"],
        "items": plan_items(str(checked["station"]), str(checked.get("kind", "hydro"))),
        "notices": [dict(zip(("level", "code", "message"), notice, strict=True))],
    }


def plan_items(station: str, kind: str) -> list[dict[str, object]]:
    """Return the positions of the plan of a station's files, in the plan's order."""
    folder = f"{kind}/{station}"
    items: list[dict[str, object]] = [
        {
            "file": f"{folder}/2023.csv",
            "status": "current",
            "local": "2023-12-31",
            "source": "2023-12-31",
            "bytes": 1200,
        },
        {
            "file": f"{folder}/2024.csv",
            "status": "newer",
            "local": "2024-06-30",
            "source": "2024-12-31",
            "bytes": 5400,
        },
        {
            "file": f"{folder}/2025.csv",
            "status": "missing",
            "local": None,
            "source": "2025-10-20",
            "bytes": None,
        },
        {
            "file": f"{folder}/stations.json",
            "status": "unverifiable",
            "local": "v3",
            "source": None,
            "bytes": None,
        },
    ]
    for place, item in enumerate(items):
        item["station"] = station
        if station == "999" or (station.startswith("9") and place == 2):
            item |= {"status": "check_failed", "source": None, "bytes": None}
            item["error"] = f"The source did not answer for {item['file']}."
    return items


def run_command(
    command: str,
    /,
    *,
    options: Mapping[str, object],
    plan: Mapping[str, object] | None = None,
    on_progress: Callable[[int, int, str, str], None] | None = None,
    on_notice: Callable[[str, str, str], None] | None = None,
) -> dict[str, object]:
    """Fetch a station's files into the store ``options["root"]``.

    Without ``plan`` every file the source tells about is fetched unless the
    store holds it; with the plan of ``check_command`` only its files to
    download (``newer``, ``missing``), each failing as stale when the source
    changed it since. A file the source could not tell about fails. Each
    event goes to ``on_progress`` as ``(current, total, station, status)``.
    """
    CALLS.append(
        (
            "run_command",
            command,
            {**options, **({} if plan is None else {"plan": plan})},
        )
    )
    checked = _checked(command, options)
    root = Path(str(checked["root"]))
    station = str(checked["station"])
    source = plan_items(station, str(checked.get("kind", "hydro")))
    wanted = source
    if plan is not None:
        planned = _items(plan["items"])
        wanted = [item for item in planned if item["status"] in ("newer", "missing")]
    current = {str(item["file"]): item for item in source}
    files: list[dict[str, object]] = []
    items: list[dict[str, object]] = []
    held = False
    for done, item in enumerate(wanted, start=1):
        name = str(item["file"])
        now = current.get(name, {"status": "check_failed", "error": "No such file."})
        if now["status"] == "check_failed":
            items.append(_failed(name, "source_unavailable", str(now["error"])))
            status = "failed"
        elif plan is not None and now["source"] != item["source"]:
            text = "The source changed since the plan was made: make a new plan."
            items.append(_failed(name, "conflict", text, reason="stale_plan"))
            status = "failed"
        else:
            fetched = _fetch(root, name, station, str(now["source"]))
            files.append(fetched)
            items.append({"id": name, "status": "ok"})
            status = "completed" if fetched["status"] == "new" else "skipped"
        if on_progress is not None:
            on_progress(done, len(wanted), station, status)
        if status == "completed" and not held:
            held = _hold(root)
    done_any = any(item["status"] == "ok" for item in items)
    failed_any = any(item["status"] == "failed" for item in items)
    notice = (
        "info",
        "run_done",
        f"Station {station}: {len(files)} files in the store.",
    )
    if on_notice is not None:
        on_notice(*notice)
    return {
        "schema": "standin-run/1",
        "root": str(root),
        "status": ("partial" if done_any else "failed") if failed_any else "ok",
        "files": files,
        "items": items,
        "notices": [dict(zip(("level", "code", "message"), notice, strict=True))],
    }


def _fetch(root: Path, name: str, station: str, label: str) -> dict[str, object]:
    """Write one file whole (``os.replace``) unless the store holds it."""
    target = root / name
    content = f"{station},{name},{label}\n".encode()
    status = "unchanged" if target.is_file() else "new"
    if status == "new":
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(f".{target.name}.part")
        part.write_bytes(content)
        os.replace(part, target)
    content = target.read_bytes()
    return {
        "path": name,
        "unit": station,
        "status": status,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "label": content.decode().strip().rpartition(",")[2],
        "version_path": name,
    }


def _hold(root: Path) -> bool:
    """Wait while the store holds ``HOLD``; whether it did."""
    hold = root / HOLD
    if not hold.exists():
        return False
    while hold.exists():
        time.sleep(0.05)
    return True


def _failed(
    name: str, code: str, message: str, *, reason: str | None = None
) -> dict[str, object]:
    """Return the item of a file that failed."""
    item: dict[str, object] = {"id": name, "status": "failed", "code": code}
    if reason is not None:
        item["reason"] = reason
    return item | {"message": message}


def _items(value: object) -> list[dict[str, object]]:
    """Return the positions of a plan document."""
    assert isinstance(value, list)
    return value


def _checked(command: str, options: Mapping[str, object]) -> dict[str, object]:
    """Return the options of a valid call in the catalog's order, normalised."""
    declared = {
        str(option["name"]): option
        for option in _options(command_schema(command)["options"])
    }
    for name in options:
        if name not in declared:
            raise ValidationError(f"unknown option {name!r}", option=name)
    checked: dict[str, object] = {}
    for name, option in declared.items():
        if name not in options:
            if option["required"]:
                raise ValidationError(f"option {name!r} is required", option=name)
            continue
        value = str(options[name]).strip()
        allowed = option.get("enum")
        if isinstance(allowed, list):
            value = value.lower()
            if value not in allowed:
                raise ValidationError(
                    f"{name} is one of {', '.join(allowed)}, not {value!r}", option=name
                )
        checked[name] = value
    return checked


def _options(value: object) -> list[dict[str, object]]:
    """Return the option entries of a command's description."""
    assert isinstance(value, list)
    return value
