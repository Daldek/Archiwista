"""Background jobs in worker processes: scans, unit outlines, link checks.

``JobSupervisor`` records jobs in the local index and runs each in a worker
process (``archiwista.jobs.worker``) that reports in JSON Lines
(``archiwista.jobs.protocol``); ``ScanScheduler`` submits the periodic and
control scans of the configured stores (SPEC 4.4, 5.6; A-ADR-007).
"""

from archiwista.jobs.protocol import JOB_KINDS, JobKind, JobSpec, WorkerMessage
from archiwista.jobs.scheduler import PlannedScan, ScanScheduler, plan_scans
from archiwista.jobs.supervisor import (
    ACTIVE_STATES,
    FINISHED_STATES,
    INDEX_JOB_KINDS,
    JOB_STATES,
    NETWORK_JOB_KINDS,
    EventType,
    JobError,
    JobEvent,
    JobListener,
    JobPage,
    JobRecord,
    JobState,
    JobSupervisor,
    ScanHistory,
    label,
)

__all__ = [
    "ACTIVE_STATES",
    "FINISHED_STATES",
    "INDEX_JOB_KINDS",
    "JOB_KINDS",
    "JOB_STATES",
    "NETWORK_JOB_KINDS",
    "EventType",
    "JobError",
    "JobEvent",
    "JobKind",
    "JobListener",
    "JobPage",
    "JobRecord",
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
