"""Background jobs in worker processes: scans, previews, producers' runs, projects.

``JobSupervisor`` records jobs in the local index and runs each in a worker
process (``archiwista.jobs.worker``) that reports in JSON Lines
(``archiwista.jobs.protocol``), following the rule of each kind
(``JOB_RULES``); ``ScanScheduler`` submits the periodic and control scans of
the configured stores (SPEC 4.4, 5.6; A-ADR-007).

The names are imported from their modules on first use (PEP 562): a worker
process, which imports this package first, then loads only what its job
needs, never the supervisor or the scheduler (ADR-044).
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from archiwista.jobs.error import JobError
    from archiwista.jobs.protocol import (
        JOB_KINDS,
        PROJECT_KINDS,
        WARM_FILTERS,
        JobKind,
        JobSpec,
        WorkerMessage,
    )
    from archiwista.jobs.scheduler import (
        PlannedScan,
        ScanScheduler,
        plan_own_scan,
        plan_scans,
    )
    from archiwista.jobs.supervisor import (
        ACTIVE_STATES,
        FINISHED_STATES,
        JOB_RULES,
        JOB_STATES,
        MAX_JOB_CALLS,
        MAX_PREVIEW_REFS,
        EventType,
        JobConflict,
        JobEvent,
        JobJoin,
        JobListener,
        JobPage,
        JobRecord,
        JobRule,
        JobState,
        JobSupervisor,
        LogTail,
        ScanHistory,
    )

# The module of each name below the package.
_MODULES: dict[str, str] = {
    "JobError": "error",
    **dict.fromkeys(
        (
            "JOB_KINDS",
            "PROJECT_KINDS",
            "WARM_FILTERS",
            "JobKind",
            "JobSpec",
            "WorkerMessage",
        ),
        "protocol",
    ),
    **dict.fromkeys(
        ("PlannedScan", "ScanScheduler", "plan_own_scan", "plan_scans"), "scheduler"
    ),
    **dict.fromkeys(
        (
            "ACTIVE_STATES",
            "FINISHED_STATES",
            "JOB_RULES",
            "JOB_STATES",
            "MAX_JOB_CALLS",
            "MAX_PREVIEW_REFS",
            "EventType",
            "JobConflict",
            "JobEvent",
            "JobJoin",
            "JobListener",
            "JobPage",
            "JobRecord",
            "JobRule",
            "JobState",
            "JobSupervisor",
            "LogTail",
            "ScanHistory",
        ),
        "supervisor",
    ),
}

__all__ = [
    "ACTIVE_STATES",
    "FINISHED_STATES",
    "JOB_KINDS",
    "JOB_RULES",
    "JOB_STATES",
    "MAX_JOB_CALLS",
    "MAX_PREVIEW_REFS",
    "PROJECT_KINDS",
    "WARM_FILTERS",
    "EventType",
    "JobConflict",
    "JobError",
    "JobEvent",
    "JobJoin",
    "JobKind",
    "JobListener",
    "JobPage",
    "JobRecord",
    "JobRule",
    "JobSpec",
    "JobState",
    "JobSupervisor",
    "LogTail",
    "PlannedScan",
    "ScanHistory",
    "ScanScheduler",
    "WorkerMessage",
    "plan_own_scan",
    "plan_scans",
]


if not TYPE_CHECKING:
    # Hidden from type checkers, which read the imports above: a name the
    # package does not export stays an error for them.

    def __getattr__(name: str) -> object:
        """Return an exported name, its module imported on first use.

        Raises
        ------
        AttributeError
            No exported name ``name``: a submodule not imported yet, or none.
        """
        module = _MODULES.get(name)
        if module is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        value = getattr(import_module(f"{__name__}.{module}"), name)
        globals()[name] = value
        return value
