"""Background jobs in worker processes: scans, unit outlines, link checks, previews.

``JobSupervisor`` records jobs in the local index and runs each in a worker
process (``archiwista.jobs.worker``) that reports in JSON Lines
(``archiwista.jobs.protocol``), following the rule of each kind
(``JOB_RULES``); ``ScanScheduler`` submits the periodic and control scans of
the configured stores (SPEC 4.4, 5.6; A-ADR-007).
"""

from archiwista.jobs.protocol import JOB_KINDS, JobKind, JobSpec, WorkerMessage
from archiwista.jobs.scheduler import PlannedScan, ScanScheduler, plan_scans
from archiwista.jobs.supervisor import (
    ACTIVE_STATES,
    FINISHED_STATES,
    JOB_RULES,
    JOB_STATES,
    MAX_PREVIEW_REFS,
    EventType,
    JobConflict,
    JobError,
    JobEvent,
    JobJoin,
    JobListener,
    JobPage,
    JobRecord,
    JobRule,
    JobState,
    JobSupervisor,
    ScanHistory,
    label,
)

__all__ = [
    "ACTIVE_STATES",
    "FINISHED_STATES",
    "JOB_KINDS",
    "JOB_RULES",
    "JOB_STATES",
    "MAX_PREVIEW_REFS",
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
    "PlannedScan",
    "ScanHistory",
    "ScanScheduler",
    "WorkerMessage",
    "label",
    "plan_scans",
]
