"""Installation diagnostics shown by ``archiwista doctor``."""

import os
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TextIO

from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsProblem,
    SettingsValidationError,
    SourceRegistryView,
    validate_settings,
)
from archiwista.messages import MESSAGES, with_detail
from archiwista.security import LOOPBACK_HOST
from archiwista.sources import SourceState
from archiwista.sources.registry import install_requirement, source_fix

type CheckLevel = Literal["ok", "warning", "error"]

REQUIRED_PRODUCERS = frozenset({"kartograf"})

_FIX_BY_CODE = {
    "root_missing": "fix_reconnect",
    "root_not_directory": "fix_not_directory",
    "root_unreadable": "fix_permissions",
    "root_nested": "fix_nested",
    "project_dir_missing": "fix_project_dir",
    "project_dir_not_directory": "fix_not_directory",
    "project_dir_unreadable": "fix_permissions",
}


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One diagnostic line.

    Parameters
    ----------
    level : {"ok", "warning", "error"}
        Errors make ``archiwista doctor`` exit with a non-zero status.
    message : str
        Polish description of what was found.
    fix : str or None
        Polish instruction how to repair the problem.
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
    registry: SourceRegistryView,
    *,
    port_available: Callable[[int], bool] = is_port_available,
) -> DoctorReport:
    """Diagnose plugins, stores, permissions, and the port without writing.

    Parameters
    ----------
    paths : AppPaths
        Configuration file and local data directory.
    registry : SourceRegistryView
        Producer plugins and their states.
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
    for producer, store_id in sorted(used.items()):
        if producer not in states:
            checks.append(
                DoctorCheck(
                    "error",
                    MESSAGES["doctor_source_unregistered"].format(
                        producer=producer, store=store_id
                    ),
                    _install_fix(producer),
                )
            )
    checks.extend(_store_checks(settings, registry))
    checks.append(_data_dir_check(paths.data_dir))
    checks.append(_port_check(settings.port, port_available))
    return DoctorReport(tuple(checks))


def _load_settings(paths: AppPaths, checks: list[DoctorCheck]) -> AppSettings:
    config = ConfigStore(paths.config_file)
    fix = MESSAGES["fix_config"].format(path=paths.config_file)
    try:
        settings = config.load()
    except SettingsValidationError as error:
        checks.extend(
            DoctorCheck("error", problem.message, fix) for problem in error.problems
        )
        return AppSettings()
    if config.exists():
        message = MESSAGES["doctor_config_ok"].format(path=paths.config_file)
        checks.append(DoctorCheck("ok", message))
    else:
        message = MESSAGES["doctor_config_absent"].format(path=paths.config_file)
        checks.append(DoctorCheck("warning", message))
    return settings


def source_check(state: SourceState, *, required: bool) -> DoctorCheck:
    """Describe a producer plugin's state in Polish, with a fix when needed.

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
    unknown = MESSAGES["doctor_unknown"]
    values = {
        "producer": state.producer,
        "version": state.package_version or unknown,
        "supported": state.supported_versions or unknown,
        "schemas": ", ".join(state.schemas) or unknown,
    }
    if state.status == "available":
        return DoctorCheck("ok", MESSAGES["doctor_source_available"].format(**values))
    level: CheckLevel = "error" if required else "warning"
    message = with_detail(
        MESSAGES[f"doctor_source_{state.status}"].format(**values), state.detail
    )
    return DoctorCheck(level, message, source_fix(state))


def _install_fix(producer: str) -> str:
    return MESSAGES["fix_install"].format(requirement=install_requirement(producer))


def _store_checks(
    settings: AppSettings, registry: SourceRegistryView
) -> list[DoctorCheck]:
    if not settings.stores:
        return [
            DoctorCheck("warning", MESSAGES["doctor_no_stores"], MESSAGES["fix_wizard"])
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
            message = MESSAGES["doctor_store_ok"].format(
                store=store.id,
                producer=producer,
                kind=MESSAGES[f"store_kind_{store.kind}"],
                path=root,
            )
            checks.append(DoctorCheck("ok", message))
    for index, path in enumerate(settings.project_dirs):
        if f"project_dirs[{index}]" not in failed:
            message = MESSAGES["doctor_project_dir_ok"].format(path=path)
            checks.append(DoctorCheck("ok", message))
    return checks


def _fix(problem: SettingsProblem) -> str:
    if problem.code == "source_not_installed":
        producer = problem.field.rpartition(".")[2]
        return _install_fix(producer)
    return MESSAGES[_FIX_BY_CODE.get(problem.code, "fix_source")]


def _data_dir_check(data_dir: Path) -> DoctorCheck:
    existing = data_dir
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    if existing.is_dir() and os.access(existing, os.W_OK | os.X_OK):
        return DoctorCheck("ok", MESSAGES["doctor_data_dir_ok"].format(path=data_dir))
    message = MESSAGES["doctor_data_dir_unwritable"].format(path=data_dir)
    return DoctorCheck("error", message, MESSAGES["fix_data_dir"])


def _port_check(port: int, port_available: Callable[[int], bool]) -> DoctorCheck:
    if port_available(port):
        return DoctorCheck("ok", MESSAGES["doctor_port_ok"].format(port=port))
    message = MESSAGES["doctor_port_busy"].format(port=port)
    return DoctorCheck("warning", message, MESSAGES["fix_port"])


def format_report(report: DoctorReport) -> str:
    """Render a report as Polish text lines."""
    lines = [MESSAGES["doctor_title"]]
    for check in report.checks:
        lines.append(f"[{MESSAGES[f'doctor_level_{check.level}']}] {check.message}")
        if check.fix:
            lines.append("    " + MESSAGES["doctor_fix"].format(fix=check.fix))
    lines.append(
        MESSAGES["doctor_summary"].format(
            errors=report.errors, warnings=report.warnings
        )
    )
    return "\n".join(lines) + "\n"


def doctor_main(paths: AppPaths, registry: SourceRegistryView, out: TextIO) -> int:
    """Print the diagnostics and return the process exit status.

    Returns
    -------
    int
        ``0`` without errors, ``1`` when any check failed.
    """
    report = run_doctor(paths, registry)
    out.write(format_report(report))
    return 1 if report.errors else 0
