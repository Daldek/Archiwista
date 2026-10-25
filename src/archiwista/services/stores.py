"""Store state as people see it: usage, projects, problems, cleanup report.

``store_summary`` answers ``GET /stores/{store}`` from the index alone, so a
disconnected store still shows its last known state (``state.stale``).
Counts cover every project (a version any project pins is not unused) but
only projects the principal sees are named (A-ADR-029).
"""

from dataclasses import dataclass

from archiwista.auth import ProjectVisibility
from archiwista.config import StoreConfig, StoreKind
from archiwista.index import (
    IndexQueries,
    IssueRef,
    OrphanLink,
    PinRef,
    ProjectRef,
    StoreIndexState,
    StoreUsage,
    UnusedVersions,
)
from archiwista.services.problems import Problem, explain


@dataclass(frozen=True, slots=True)
class StoreSummary:
    """A configured store's state for the „Magazyn” view.

    Attributes
    ----------
    store : str
        Store id.
    name : str
        Human-readable store name.
    kind : {"local", "share"}
        Local disk or network share.
    state : StoreIndexState or None
        Index state with the last scan and its actor (``last_scan.actor``)
        and the running job; ``None`` before the store is in the index.
    usage : StoreUsage
        Disk usage per product, each content once (links add nothing).
    unused : UnusedVersions
        Present versions neither current, a full sheet, nor pinned by any
        project (visible or not).
    projects : tuple[ProjectRef, ...]
        Projects the principal sees whose manifest names this store.
    problems : tuple[Problem, ...]
        Store problems with fix instructions: producer findings, check
        findings (``link_mismatch``), orphan link sidecars and pinned
        files missing from the store (of projects the principal sees).
    """

    store: str
    name: str
    kind: StoreKind
    state: StoreIndexState | None
    usage: StoreUsage
    unused: UnusedVersions
    projects: tuple[ProjectRef, ...]
    problems: tuple[Problem, ...]


def store_summary(
    queries: IndexQueries, store: StoreConfig, *, visible: ProjectVisibility
) -> StoreSummary:
    """Return the state of a configured store from the index.

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index.
    store : StoreConfig
        The configured store.
    visible : ProjectVisibility
        Projects the principal sees (``Authorizer.visible_projects``).
    """
    producer = next(iter(store.roots()))
    state = next(
        (item for item in queries.status().stores if item.store == store.id), None
    )
    usage = queries.usage(store.id) or StoreUsage(store.id, (), 0, 0)
    unused = queries.unused_versions(store.id) or UnusedVersions(store.id, (), 0, 0, 0)
    problems = (
        *(issue_problem(issue, producer) for issue in queries.issues(store.id)),
        *(_orphan(link, producer) for link in queries.orphan_links(store.id)),
        *(
            _pin(pin, producer)
            for pin in queries.pin_problems(store.id, visible=visible)
        ),
    )
    return StoreSummary(
        store=store.id,
        name=store.name,
        kind=store.kind,
        state=state,
        usage=usage,
        unused=unused,
        projects=queries.projects(store=store.id, visible=visible),
        problems=problems,
    )


def issue_problem(issue: IssueRef, producer: str) -> Problem:
    """Return a store problem the index holds with its fix instruction.

    Parameters
    ----------
    issue : IssueRef
        A problem a scan or a check job recorded.
    producer : str
        Producer of the store directory, named in the instruction.
    """
    message, instruction = explain(issue.code, path=issue.path, producer=producer)
    return Problem(
        issue.code,
        message,
        instruction,
        path=issue.path,
        segment=issue.segment,
        slot=issue.slot,
        origin=issue.origin,
        first_seen_at=issue.first_seen_at,
    )


def _orphan(link: OrphanLink, producer: str) -> Problem:
    message, instruction = explain(
        "orphan_sidecar", path=link.slot, version=link.version, producer=producer
    )
    return Problem(
        "orphan_sidecar",
        message,
        instruction,
        path=link.slot,
        segment=link.segment,
        slot=link.slot,
    )


def _pin(pin: PinRef, producer: str) -> Problem:
    code = "missing_pin" if pin.state == "missing" else "pin_sha256_mismatch"
    message, instruction = explain(
        code,
        version=pin.version,
        project=pin.project,
        task=pin.task,
        producer=producer,
    )
    return Problem(
        code,
        message,
        instruction,
        path=pin.version,
        project=pin.project_key,
        task=pin.task,
    )
