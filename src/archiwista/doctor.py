"""Installation diagnostics shown by ``archiwista doctor``."""

import os
import socket
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TextIO

from archiwista._errors import OUTCOMES
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsProblem,
    SettingsValidationError,
    SourceRegistryView,
    TeamSettings,
    validate_settings,
)
from archiwista.messages import message, with_detail
from archiwista.security import LOOPBACK_HOST, tls_problem
from archiwista.sources import DefaultRoot, SourceState
from archiwista.sources.registry import (
    PluginRegistry,
    install_requirement,
    read_default_root,
    source_fix,
)

type CheckLevel = Literal["ok", "warning", "error"]

REQUIRED_PRODUCERS = frozenset({"kartograf"})

_FIX_BY_CODE = {
    "root_missing": "fix.reconnect",
    "root_not_directory": "fix.not_directory",
    "root_unreadable": "fix.permissions",
    "root_nested": "fix.nested",
    "project_dir_missing": "fix.project_dir",
    "project_dir_not_directory": "fix.not_directory",
    "project_dir_unreadable": "fix.permissions",
    "own_data_dir_missing": "fix.own_data_dir",
    "own_data_dir_not_directory": "fix.not_directory",
    "own_data_dir_unreadable": "fix.permissions",
    "own_data_dir_inside_store": "fix.own_data_dir",
    "own_data_dir_inside_app_data": "fix.own_data_dir",
    "own_data_dir_overlaps_project": "fix.own_data_dir",
}


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One diagnostic line.

    Parameters
    ----------
    level : {"ok", "warning", "error"}
        Errors make ``archiwista doctor`` exit with a non-zero status.
    message : str
        Description of what was found.
    fix : str or None
        Instruction how to repair the problem.
    """

    level: CheckLevel
    message: str
    fix: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """All diagnostic lines in display order."""

    checks: tuple[DoctorCheck, ...]

    @property
    def errors(self) -> int:
        """Number of errors."""
        return sum(check.level == "error" for check in self.checks)

    @property
    def warnings(self) -> int:
        """Number of warnings."""
        return sum(check.level == "warning" for check in self.checks)


def is_port_available(port: int) -> bool:
    """Return whether the server could listen on ``127.0.0.1:port`` now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if sys.platform != "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((LOOPBACK_HOST, port))
        except OSError:
            return False
    return True


def run_doctor(
    paths: AppPaths,
    registry: PluginRegistry,
    *,
    port_available: Callable[[int], bool] = is_port_available,
) -> DoctorReport:
    """Diagnose plugins, stores, permissions, and the port without writing.

    Parameters
    ----------
    paths : AppPaths
        Configuration file and local data directory.
    registry : PluginRegistry
        Producer plugins, their states and, for a producer that has one, its
        default store root.
    port_available : callable, optional
        Port check, replaceable in tests.

    Returns
    -------
    DoctorReport
        Diagnostic lines; nothing is created in stores, project directories,
        or the local data directory.
    """
    checks: list[DoctorCheck] = []
    settings = _load_settings(paths, checks)
    states = {state.producer: state for state in registry.states()}
    used = {
        producer: store.id for store in settings.stores for producer in store.roots()
    }
    for producer in sorted(states):
        required = producer in REQUIRED_PRODUCERS or producer in used
        checks.append(source_check(states[producer], required=required))
        root = read_default_root(registry, producer)
        if root is not None:
            checks.append(default_root_check(producer, root))
    for producer, store_id in sorted(used.items()):
        if producer not in states:
            checks.append(
                DoctorCheck(
                    "error",
                    message(
                        "doctor.source_unregistered", producer=producer, store=store_id
                    ),
                    _install_fix(producer),
                )
            )
    checks.extend(_store_checks(settings, registry))
    checks.append(_data_dir_check(paths.data_dir))
    privacy = _privacy_check(paths.data_dir)
    if privacy is not None:
        checks.append(privacy)
    checks.extend(team_checks(settings.team))
    checks.append(_port_check(settings.port, port_available))
    return DoctorReport(tuple(checks))


def _load_settings(paths: AppPaths, checks: list[DoctorCheck]) -> AppSettings:
    config = ConfigStore(paths.config_file)
    fix = message("fix.config", path=paths.config_file)
    try:
        settings = config.load()
    except SettingsValidationError as error:
        checks.extend(
            DoctorCheck("error", problem.message, fix) for problem in error.problems
        )
        return AppSettings()
    if config.exists():
        text = message("doctor.config_ok", path=paths.config_file)
        checks.append(DoctorCheck("ok", text))
    else:
        text = message("doctor.config_absent", path=paths.config_file)
        checks.append(DoctorCheck("warning", text))
    return settings


def source_check(state: SourceState, *, required: bool) -> DoctorCheck:
    """Describe a producer plugin's state, with a fix when needed.

    Parameters
    ----------
    state : SourceState
        The plugin's state.
    required : bool
        Whether a store or Archiwista itself needs the producer: then an
        unavailable plugin is an error, otherwise a warning.

    Returns
    -------
    DoctorCheck
        ``ok`` with the versions and schemas, or the problem and its fix.
    """
    unknown = message("doctor.unknown")
    values: dict[str, Any] = {
        "producer": state.producer,
        "version": state.package_version or unknown,
        "supported": state.supported_versions or unknown,
        "schemas": ", ".join(state.schemas) or unknown,
    }
    if state.status == "available":
        return DoctorCheck("ok", message("doctor.source_available", **values))
    level: CheckLevel = "error" if required else "warning"
    text = with_detail(message(f"doctor.source_{state.status}", **values), state.detail)
    return DoctorCheck(level, text, source_fix(state))


def default_root_check(producer: str, root: DefaultRoot) -> DoctorCheck:
    """Describe the default store root of a producer; it is a report, no problem.

    Parameters
    ----------
    producer : str
        Producer id.
    root : DefaultRoot
        What the producer's adapter reports.

    Returns
    -------
    DoctorCheck
        ``ok`` with the directory, the layer of the settings that gave it and
        what is there (nothing, a directory, a store with its marker); it has
        no fix.
    """
    state = "marked" if root.marked else "unmarked" if root.exists else "absent"
    text = message(
        "doctor.default_root",
        producer=producer,
        path=root.path,
        origin=message(f"doctor.default_root_{root.source}", name=root.name),
        state=message(f"doctor.default_root_{state}"),
    )
    return DoctorCheck("ok", text)


def _install_fix(producer: str) -> str:
    return message("fix.install", requirement=install_requirement(producer))


def _store_checks(
    settings: AppSettings, registry: SourceRegistryView
) -> list[DoctorCheck]:
    if not settings.stores:
        return [
            DoctorCheck("warning", message("doctor.no_stores"), message("fix.wizard"))
        ]
    problems = validate_settings(settings, registry)
    failed = {problem.field for problem in problems}
    checks = [
        DoctorCheck("error", problem.message, _fix(problem)) for problem in problems
    ]
    for index, store in enumerate(settings.stores):
        for producer, root in store.roots().items():
            if f"stores[{index}].{producer}" in failed:
                continue
            text = message(
                "doctor.store_ok",
                store=store.id,
                producer=producer,
                kind=message(f"store.kind_{store.kind}"),
                path=root,
            )
            checks.append(DoctorCheck("ok", text))
    for index, path in enumerate(settings.project_dirs):
        if f"project_dirs[{index}]" not in failed:
            text = message("doctor.project_dir_ok", path=path)
            checks.append(DoctorCheck("ok", text))
    return checks


def _fix(problem: SettingsProblem) -> str:
    if problem.hint is not None:
        return problem.hint
    if problem.code == "source_not_installed":
        producer = problem.field.rpartition(".")[2]
        return _install_fix(producer)
    return message(_FIX_BY_CODE.get(problem.code, "fix.source"))


def _data_dir_check(data_dir: Path) -> DoctorCheck:
    existing = data_dir
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    if existing.is_dir() and os.access(existing, os.W_OK | os.X_OK):
        return DoctorCheck("ok", message("doctor.data_dir_ok", path=data_dir))
    text = message("doctor.data_dir_unwritable", path=data_dir)
    return DoctorCheck("error", text, message("fix.data_dir"))


def _privacy_check(data_dir: Path) -> DoctorCheck | None:
    """Warn when other accounts of the computer may enter the local data (POSIX)."""
    if os.name != "posix":
        return None
    try:
        mode = stat.S_IMODE(data_dir.stat().st_mode)
    except OSError:
        return None
    if not mode & 0o077:
        return None
    text = message("doctor.data_dir_open", path=data_dir, mode=f"{mode:04o}")
    return DoctorCheck("warning", text, message("fix.data_dir_open", path=data_dir))


def team_checks(team: TeamSettings) -> list[DoctorCheck]:
    """Describe team mode: its address, TLS files and trusted proxies (ADR-046).

    Parameters
    ----------
    team : TeamSettings
        The table ``[team]`` of the settings.

    Returns
    -------
    list[DoctorCheck]
        Nothing in local mode. In team mode the address people open; the
        TLS files of the server loaded as a pair (an error when they cannot
        be, a warning when other accounts may read the key); an error when
        there is neither TLS in the server nor a trusted proxy; the trusted
        proxies.
    """
    if not team.enabled:
        return []
    checks = [DoctorCheck("ok", message("doctor.team_origin", origin=team.origin))]
    if team.tls_cert is not None and team.tls_key is not None:
        checks.extend(_tls_checks(team.tls_cert, team.tls_key))
    elif not team.trusted_proxies:
        text = message("serve.tls_required")
        checks.append(DoctorCheck("error", text, message("serve.hint_tls_required")))
    if team.trusted_proxies:
        proxies = ", ".join(team.trusted_proxies)
        checks.append(
            DoctorCheck("ok", message("doctor.team_proxies", proxies=proxies))
        )
    return checks


def _tls_checks(cert: Path, key: Path) -> list[DoctorCheck]:
    problem = tls_problem(cert, key)
    if problem is not None:
        text = with_detail(message("serve.tls_unusable", cert=cert, key=key), problem)
        return [DoctorCheck("error", text, message("serve.hint_tls_unusable"))]
    checks = [DoctorCheck("ok", message("doctor.team_tls", cert=cert, key=key))]
    if os.name == "posix":
        mode = stat.S_IMODE(key.stat().st_mode)
        if mode & 0o077:
            text = message("doctor.team_key_open", path=key, mode=f"{mode:04o}")
            fix = message("fix.team_key_open", path=key)
            checks.append(DoctorCheck("warning", text, fix))
    return checks


def _port_check(port: int, port_available: Callable[[int], bool]) -> DoctorCheck:
    if port_available(port):
        return DoctorCheck("ok", message("doctor.port_ok", port=port))
    text = message("doctor.port_busy", port=port)
    return DoctorCheck("warning", text, message("fix.port"))


def format_report(report: DoctorReport) -> str:
    """Render a report as text lines."""
    lines: list[str] = [message("doctor.title")]
    for check in report.checks:
        lines.append(f"[{message(f'doctor.level_{check.level}')}] {check.message}")
        if check.fix:
            lines.append("    " + message("doctor.fix", fix=check.fix))
    lines.append(
        message("doctor.summary", errors=report.errors, warnings=report.warnings)
    )
    return "\n".join(lines) + "\n"


def doctor_main(paths: AppPaths, registry: PluginRegistry, out: TextIO) -> int:
    """Print the diagnostics and return the process exit status.

    A failed check is an outcome, not an error (ERR §1): the report is the
    result and no error document follows it.

    Returns
    -------
    int
        ``0`` without errors, ``10`` (``partial``) when some checks failed and
        others passed, ``11`` (``failed``) when every check failed.
    """
    report = run_doctor(paths, registry)
    out.write(format_report(report))
    if not report.errors:
        return OUTCOMES["ok"]
    everything_failed = report.errors == len(report.checks)
    return OUTCOMES["failed" if everything_failed else "partial"]
