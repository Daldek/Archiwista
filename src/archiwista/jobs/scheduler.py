"""Scheduled scans of the configured stores (SPEC 4.4, plan step 6b).

When the server starts, a store whose last scan ended more than 15 minutes
ago (or never) gets an incremental scan at once; otherwise its first scan
comes one interval after the start. Afterwards a store is scanned one
interval after its last scan ended, whatever started that scan: every
5 minutes on a local disk, every 15 minutes on a share (the settings). Once
every ``full_scan_interval_h`` hours (the settings, daily by default) the
scan is a full control scan instead, and a store never fully scanned gets a
full one: incremental scans do not list known version directories again,
so only a full scan notices files deleted or added inside them. An
unavailable store is only probed, at every tick: it is scanned as soon as
the probe finds it again and its directory is not an empty mount point. A
store added to the settings, or moved, gets a full scan right away. A store
with a job writing its index is left alone. The data folders of every
project get an ``own_scan`` the same way (``plan_own_scan``): at the start
when the last one ended more than 15 minutes ago, then every
``scan_interval_local_min``. Scheduled jobs act as the ``scheduler`` for
the owner; once an hour, the first time at the start, a tick also prunes old
jobs (``JobSupervisor.prune``: routine scans and routine ``own_scan`` runs
after 48 hours) and the entries of the action log older than
``action_log_retention_days`` (``StateStore.prune_actions``, logged as
``log.prune``). With the setting ``preview_warm_after_scan`` on, a store whose
newest succeeded scan indexed new versions gets a ``preview_warm`` job of
those versions (``since`` the scan's start), once per scan and only while
no job writes the store's index (ADR-041).
"""

import logging
import threading
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from archiwista.auth import SCHEDULER
from archiwista.config import (
    AppSettings,
    SettingsService,
    SourceRegistryView,
    StoreConfig,
)
from archiwista.errors import JobConflictError, NotFoundError, OfflineModeError
from archiwista.index import IndexQueries, ScanMode
from archiwista.jobs.availability import store_unreachable
from archiwista.jobs.supervisor import JobRecord, JobSupervisor, ScanHistory
from archiwista.state import StateStore

logger = logging.getLogger(__name__)

# A scan this recent when the server starts is not repeated at once.
STARTUP_STALE = timedelta(minutes=15)
# Seconds between two plannings (and probes of unavailable stores).
TICK_S = 60.0
# Time between two prunings of old jobs and log entries from a tick.
PRUNE_INTERVAL = timedelta(hours=1)
# Seconds a probe of an unavailable store may take (a hung share).
PROBE_TIMEOUT_S = 10.0


@dataclass(frozen=True, slots=True)
class PlannedScan:
    """A scan due now; ``probe``: only after a probe finds the store again."""

    store: str
    mode: ScanMode
    probe: bool = False


def plan_scans(
    settings: AppSettings,
    history: Mapping[str, ScanHistory],
    unavailable: Collection[str],
    *,
    now: datetime,
    started_at: datetime,
) -> tuple[PlannedScan, ...]:
    """Decide which stores to scan now, and how.

    Parameters
    ----------
    settings : AppSettings
        Stores, their kinds, the scan intervals and the full scan interval.
    history : Mapping[str, ScanHistory]
        Scans of each store (``JobSupervisor.scan_history``).
    unavailable : Collection[str]
        Stores the index records as unavailable: they are only probed.
    now : datetime
        The time of the planning (UTC).
    started_at : datetime
        When the server started.

    Returns
    -------
    tuple[PlannedScan, ...]
        Scans due now, in the order of the settings.
    """
    planned = []
    full_interval = timedelta(hours=settings.full_scan_interval_h)
    for store in settings.stores:
        scans = history.get(store.id, ScanHistory())
        if scans.busy:
            continue
        full = scans.full_at is None or now - scans.full_at >= full_interval
        mode: ScanMode = "full" if full else "incremental"
        if store.id in unavailable:
            planned.append(PlannedScan(store.id, mode, probe=True))
            continue
        interval = timedelta(seconds=settings.scan_interval_s(store.kind))
        last = scans.finished_at
        if last is None or last < started_at - STARTUP_STALE:
            due = started_at
        else:
            due = max(last, started_at) + interval
        if now >= due:
            planned.append(PlannedScan(store.id, mode))
    return tuple(planned)


def plan_own_scan(
    settings: AppSettings,
    history: ScanHistory,
    *,
    now: datetime,
    started_at: datetime,
) -> bool:
    """Decide whether the data folders of every project are due a scan now.

    Parameters
    ----------
    settings : AppSettings
        ``scan_interval_local_min``: the interval of the scans.
    history : ScanHistory
        Runs of every project (``JobSupervisor.own_scan_history``); one
        waiting or running (``busy``) is not doubled.
    now : datetime
        The time of the planning (UTC).
    started_at : datetime
        When the server started.

    Returns
    -------
    bool
        Whether to submit an ``own_scan`` of every project.
    """
    if history.busy:
        return False
    last = history.finished_at
    if last is None or last < started_at - STARTUP_STALE:
        due = started_at
    else:
        interval = timedelta(seconds=settings.scan_interval_s("local"))
        due = max(last, started_at) + interval
    return now >= due


class ScanScheduler:
    """Submit the scans ``plan_scans`` decides, and warm-ups after them, in a thread.

    Parameters
    ----------
    jobs : JobSupervisor
        The started supervisor that runs the scans.
    settings : SettingsService
        Settings in effect; a store added or moved gets a full scan.
    registry : SourceRegistryView
        Producer plugins, to probe unavailable stores.
    index_path : Path
        The local index (stores' availability).
    tick_s : float, default 60.0
        Seconds between two plannings.
    probe_timeout_s : float, default 10.0
        Seconds a probe may take before the store counts as unavailable.
    state : StateStore or None, optional
        The state database whose action log a tick prunes; none pruned
        without it.
    """

    def __init__(
        self,
        jobs: JobSupervisor,
        settings: SettingsService,
        registry: SourceRegistryView,
        *,
        index_path: Path,
        tick_s: float = TICK_S,
        probe_timeout_s: float = PROBE_TIMEOUT_S,
        state: StateStore | None = None,
    ) -> None:
        self._jobs = jobs
        self._settings = settings
        self._registry = registry
        self._queries = IndexQueries(index_path)
        self._tick_s = tick_s
        self._probe_timeout_s = probe_timeout_s
        self._state = state
        self._started_at = datetime.now(UTC)
        self._pruned_at: datetime | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._probing: set[str] = set()
        self._probing_lock = threading.Lock()
        # The newest scan of each store a warm-up of previews followed.
        self._warmed: dict[str, str] = {}

    def start(self) -> None:
        """Plan at once, then every ``tick_s``; follow settings changes."""
        self._started_at = datetime.now(UTC)
        self._unsubscribe = self._settings.subscribe(self._settings_changed)
        self._thread = threading.Thread(
            target=self._run, name="archiwista-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop planning; scans already submitted go on."""
        self._stop.set()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._thread is not None:
            self._thread.join(self._probe_timeout_s + 5)
            self._thread = None
        self._queries.close()

    def tick(self, now: datetime | None = None) -> tuple[JobRecord, ...]:
        """Plan once and submit the scans and warm-ups due; prune hourly.

        Parameters
        ----------
        now : datetime or None, optional
            The time of the planning; the current time when omitted.

        Returns
        -------
        tuple[JobRecord, ...]
            Jobs submitted.
        """
        moment = now or datetime.now(UTC)
        settings = self._settings.get()
        self._jobs.recover()
        if self._pruned_at is None or moment - self._pruned_at >= PRUNE_INTERVAL:
            self._jobs.prune(now=moment)
            if self._state is not None:
                kept = timedelta(days=settings.action_log_retention_days)
                self._state.prune_actions(moment - kept, actor=SCHEDULER)
            self._pruned_at = moment
        states = {state.store: state for state in self._queries.status().stores}
        history = {
            store.id: self._jobs.scan_history(store.id) for store in settings.stores
        }
        unavailable = {
            store for store, state in states.items() if state.status == "unavailable"
        }
        submitted = []
        for planned in plan_scans(
            settings, history, unavailable, now=moment, started_at=self._started_at
        ):
            config = settings.store(planned.store)
            if config is None:  # pragma: no cover - planned from these settings
                continue
            if not self._available_roots(config):
                logger.debug("Store %s: no source is available, no scan", config.id)
                continue
            state = states.get(planned.store)
            indexed = state is not None and bool(state.slots or state.versions)
            if planned.probe and not self._probe(config, indexed=indexed):
                continue
            job = self._submit(planned.store, planned.mode)
            if job is not None:
                submitted.append(job)
        if settings.preview_warm_after_scan:
            scanning = {job.store for job in submitted if job.store is not None}
            submitted += self._warm_after_scans(settings, history, scanning)
        if plan_own_scan(
            settings,
            self._jobs.own_scan_history(),
            now=moment,
            started_at=self._started_at,
        ):
            own = self._jobs.submit("own_scan", actor=SCHEDULER)
            submitted.append(own)
        return tuple(submitted)

    def _warm_after_scans(
        self,
        settings: AppSettings,
        history: Mapping[str, ScanHistory],
        scanning: Collection[str],
    ) -> list[JobRecord]:
        """Warm the previews of the versions each store's newest scan indexed.

        A store with a job of its index waiting or running, or whose scan
        this tick submitted, waits for a later tick. Each scan is followed
        once, and only a scan that wrote versions gets a warm-up: of the
        versions indexed since it started. The scans followed are kept in
        memory, so a restarted server follows each store's newest scan once
        more; that warm-up finds its work ready in the cache.
        """
        submitted = []
        for store in settings.stores:
            if store.id in scanning or history.get(store.id, ScanHistory()).busy:
                continue
            scans = self._jobs.list(
                kind="scan", store=store.id, state="succeeded", limit=1
            ).items
            if not scans or self._warmed.get(store.id) == scans[0].id:
                continue
            scan = scans[0]
            self._warmed[store.id] = scan.id
            written = (scan.result or {}).get("versions_written", 0)
            if not written or scan.started_at is None:
                continue
            params = {"store": store.id, "since": scan.started_at.isoformat()}
            job = self._jobs.submit("preview_warm", params=params, actor=SCHEDULER)
            submitted.append(job)
        return submitted

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # planning must go on
                logger.exception("Planning scheduled scans failed")
            self._stop.wait(self._tick_s)

    def _submit(self, store: str, mode: ScanMode) -> JobRecord | None:
        try:
            return self._jobs.submit(
                "scan", store=store, params={"mode": mode}, actor=SCHEDULER
            )
        except (JobConflictError, NotFoundError, OfflineModeError) as error:
            logger.info("Scheduled scan of store %s not submitted: %s", store, error)
            return None

    def _available_roots(self, config: StoreConfig) -> dict[str, Path]:
        """Return the store's directories whose source can scan them (SPEC 5.8).

        A directory of a source that is not available (not installed,
        incompatible, failed to load) is left out: it neither stops the scans
        of the store's other directories nor starts a job of its own.
        """
        available = {
            state.producer
            for state in self._registry.states()
            if state.status == "available"
        }
        return {
            producer: root
            for producer, root in config.roots().items()
            if producer in available
        }

    def _probe(self, config: StoreConfig, *, indexed: bool) -> bool:
        """Probe a store in a thread of its own, waiting ``probe_timeout_s``.

        A probe of a hung share does not stop the planning; the store is not
        probed again until that probe returns. Only the directories of
        available sources are probed.
        """
        with self._probing_lock:
            if config.id in self._probing:
                return False
            self._probing.add(config.id)
        found: list[bool] = []

        def probe() -> None:
            try:
                found.append(
                    all(
                        store_unreachable(
                            self._registry.probe(producer, root), root, indexed=indexed
                        )
                        is None
                        for producer, root in self._available_roots(config).items()
                    )
                )
            except Exception:  # a faulty plugin counts as unavailable
                logger.exception("Probing store %s failed", config.id)
            finally:
                with self._probing_lock:
                    self._probing.discard(config.id)

        thread = threading.Thread(
            target=probe, name=f"archiwista-probe-{config.id}", daemon=True
        )
        thread.start()
        thread.join(self._probe_timeout_s)
        return bool(found and found[0])

    def _settings_changed(self, previous: AppSettings, current: AppSettings) -> None:
        """Fully scan the stores added to the settings or moved."""
        before = {store.id: store.roots() for store in previous.stores}
        for store in current.stores:
            if before.get(store.id) != store.roots():
                self._submit(store.id, "full")
