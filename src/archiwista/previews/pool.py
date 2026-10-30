"""Render pool: long-lived render processes behind one bounded queue (decision 3).

``RenderPool`` runs the operations of ``archiwista.previews.worker.OPERATIONS``
(``probe`` 20 s, ``thumbnail`` 30 s, ``tile`` 15 s, ``features`` 15 s,
``members`` 10 s, ``layer_thumbnail`` 60 s, ``layer_tile`` 15 s) in at most
``workers`` render processes
(``RENDER_WORKER_COMMAND``; ``min(4, cpu)`` in ``archiwista serve``), each
started with the sandbox: the environment of ``untrusted_env``, a session
of its own and, on Linux, ``RLIMIT_AS`` of 2 GiB. The server itself never
opens a data file.

- The preview cache first: an operation kept there (``Operation.target``)
  answers from it without rendering, and what is rendered is put there. A
  request for a file whose ``info.json`` is cached carries that probe, so
  the render process does not recognise the file again. Files of other
  objects an answer carries (a layer's versions' tiles) are kept under
  those objects.
- One rendering per key: equal requests (operation, content, renderer
  version, parameters) wait for the same answer.
- At most ``queue_size`` (64) requests wait; one more is refused at once
  (``PreviewBusyError``: ``503 preview_busy`` with ``Retry-After``).
- A request every caller of which gave up (``arequest`` cancelled: the
  browser moved the map) leaves the queue before it is rendered.
- Past an operation's time limit the process is killed with its group, the
  request fails (``PreviewTimeoutError``) and the next one gets a new
  process. A process out of memory answers ``memory_limit`` and ends.
- ``timeout`` and ``memory_limit`` depend on the load, so they never enter
  the preview cache: this process remembers them for 10 minutes, and the
  same request fails at once meanwhile instead of killing another process.
  A probe ending in a lasting reason (``unreadable``, ``unsupported_format``
  …) is cached as ``info.json`` with the code only; the library's message
  reaches only the request that caused it.
- A process without work for 5 minutes ends; the next request starts one.
"""

import asyncio
import concurrent.futures
import contextlib
import hashlib
import json
import logging
import math
import os
import queue
import secrets
import signal
import sqlite3
import subprocess
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Literal, Self, cast

from archiwista.errors import (
    PreviewBusyError,
    PreviewTimeoutError,
    PreviewUnavailableError,
    RendererStartError,
)
from archiwista.messages import message
from archiwista.previews.cache import INFO_NAME, CacheKey, PreviewCache, cache_key
from archiwista.previews.protocol import (
    CODE_PROTOCOL_ERROR,
    RENDER_WORKER_COMMAND,
    RenderAnswer,
    RenderProtocolError,
    RenderRequest,
    decode_answer,
    encode_request,
)
from archiwista.previews.types import (
    PREVIEW_REASONS,
    TRANSIENT_REASONS,
    UNRENDERABLE_REASONS,
    JsonObject,
    PreviewProbe,
    PreviewReason,
    PreviewSource,
)
from archiwista.previews.worker import OPERATIONS, Operation, parse_object_file
from archiwista.sandbox import child_limits, kill_untrusted, untrusted_env

QUEUE_SIZE = 64
# Seconds a process without work lives on.
IDLE_S = 300.0
RENDER_MEMORY_BYTES = 2 * 1024**3
# Seconds a timeout or memory limit of a request is remembered.
FAILURE_MEMORY_S = 600.0
# ``Retry-After`` of a full queue.
RETRY_AFTER_S = 2
# Seconds a process has to end after its input is closed.
STOP_WAIT_S = 5.0

logger = logging.getLogger(__name__)

type _Outcome = RenderResult | BaseException


def default_render_workers() -> int:
    """Render processes of a server: as many as processors, at most four."""
    return min(4, os.cpu_count() or 1)


@dataclass(frozen=True, slots=True)
class RenderResult:
    """The result of an operation.

    Attributes
    ----------
    data : bytes
        PNG, ``info.json`` or JSON (``json()``).
    cached : bool
        Read from the preview cache; nothing was rendered.
    detail : str or None
        The library's message (no paths) of a probe that found a lasting
        reason, only for the request that rendered it.
    """

    data: bytes
    cached: bool = False
    detail: str | None = None

    def json(self) -> Any:
        """Return the data read as JSON."""
        return json.loads(self.data)

    def probe(self) -> PreviewProbe:
        """Return the data read as a probe (``info.json``)."""
        return PreviewProbe.from_bytes(self.data)


@dataclass(frozen=True, slots=True)
class PoolStats:
    """State of a render pool, for ``/health`` and tests.

    ``rendered`` counts the requests handed to render processes since the
    start (answers from the cache and joined requests not included);
    ``abandoned`` the requests dropped from the queue unrendered.
    """

    workers: int
    alive: int
    queued: int
    rendering: int
    rendered: int
    abandoned: int


@dataclass(frozen=True, slots=True)
class _Prepared:
    key: str
    request: RenderRequest
    operation: Operation
    timeout_s: float
    target: tuple[CacheKey, str] | None


@dataclass(eq=False, slots=True)
class _Call:
    """A request waiting for or in a render process, with its callers."""

    prepared: _Prepared
    future: concurrent.futures.Future[RenderResult] = field(
        default_factory=concurrent.futures.Future
    )
    waiters: int = 0
    started: bool = False


@dataclass(eq=False, slots=True)
class _Slot:
    """One render process and the thread feeding it."""

    index: int
    process: subprocess.Popen[bytes] | None = None
    lines: "queue.Queue[bytes | None] | None" = None
    reader: threading.Thread | None = None
    thread: threading.Thread | None = None
    last_used: float = 0.0


@dataclass(frozen=True, slots=True)
class _Failure:
    code: Literal["timeout", "memory_limit"]
    until: float


class _TimedOut(Exception):
    pass


class _Ended(Exception):
    def __init__(self, status: int | None) -> None:
        super().__init__(status)
        self.status = status


class _Closed(Exception):
    pass


class RenderPool:
    """Render processes behind one bounded queue, with the preview cache.

    Parameters
    ----------
    workers : int
        Render processes at most (started when needed).
    cache : PreviewCache
        Where results are kept; the pool does not close it.
    timeouts : Mapping[str, float] or None, optional
        Seconds per operation instead of ``Operation.timeout_s``.
    command : Sequence[str], optional
        Command of a render process (tests give one with test renderers);
        ``--previews-dir`` (the cache's root, for ``worker.cached_file``) is
        appended, and ``--work-dir`` when ``work_dir`` is given.
    work_dir : Path or None, optional
        Root of the processes' work directories (``AppPaths.work_dir``).
    queue_size : int, default 64
        Requests waiting at most.
    idle_s : float, default 300
        Seconds a process without work lives on.
    memory_bytes : int or None, default 2 GiB
        Address space of a process (``RLIMIT_AS``, Linux); ``None`` keeps
        the inherited limit.
    failure_s : float, default 600
        Seconds a timeout or memory limit of a request is remembered.

    Notes
    -----
    ``start`` first and ``close`` last (or ``with``); all methods are
    thread-safe.
    """

    def __init__(
        self,
        *,
        workers: int,
        cache: PreviewCache,
        timeouts: Mapping[str, float] | None = None,
        command: Sequence[str] = RENDER_WORKER_COMMAND,
        work_dir: Path | None = None,
        queue_size: int = QUEUE_SIZE,
        idle_s: float = IDLE_S,
        memory_bytes: int | None = RENDER_MEMORY_BYTES,
        failure_s: float = FAILURE_MEMORY_S,
    ) -> None:
        if workers < 1:
            raise ValueError("a render pool has at least one process")
        unknown = set(timeouts or {}) - set(OPERATIONS)
        if unknown:
            raise ValueError(f"unknown render operations {sorted(unknown)}")
        self._cache = cache
        self._timeouts = {
            name: float((timeouts or {}).get(name, operation.timeout_s))
            for name, operation in OPERATIONS.items()
        }
        self._command = tuple(command)
        self._work_dir = work_dir
        self._queue_size = queue_size
        self._idle_s = idle_s
        self._memory_bytes = memory_bytes
        self._failure_s = failure_s
        self._lock = threading.Lock()
        self._ready = threading.Condition(self._lock)
        self._queue: deque[_Call] = deque()
        self._calls: dict[str, _Call] = {}
        self._failures: dict[str, _Failure] = {}
        self._slots = tuple(_Slot(index) for index in range(workers))
        self._phase: Literal["new", "open", "closing", "closed"] = "new"
        self._rendering = 0
        self._rendered = 0
        self._abandoned = 0

    def __enter__(self) -> Self:
        """Start the pool for a ``with`` block."""
        self.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the pool."""
        self.close()

    @property
    def cache(self) -> PreviewCache:
        """The preview cache the pool keeps results in."""
        return self._cache

    @property
    def workers(self) -> int:
        """Render processes at most."""
        return len(self._slots)

    def start(self) -> None:
        """Start the threads feeding the processes (processes start on demand)."""
        with self._lock:
            if self._phase != "new":
                raise RuntimeError("a render pool starts once")
            self._phase = "open"
            for slot in self._slots:
                slot.thread = threading.Thread(
                    target=self._serve,
                    args=(slot,),
                    name=f"archiwista-render-{slot.index}",
                    daemon=True,
                )
                slot.thread.start()

    def close(self) -> None:
        """Stop: waiting requests fail (``PreviewBusyError``), processes end."""
        with self._lock:
            if self._phase == "new":
                self._phase = "closed"
            if self._phase != "open":
                return
            self._phase = "closing"
            waiting = list(self._queue)
            self._queue.clear()
            for call in waiting:
                self._forget(call)
            self._ready.notify_all()
            running = [slot.process for slot in self._slots if slot.process is not None]
        closed = PreviewBusyError(
            message("preview.closed"), retry_after_s=RETRY_AFTER_S
        )
        for call in waiting:
            _settle(call.future, closed)
        for process in running:
            kill_untrusted(process)
        for slot in self._slots:
            if slot.thread is not None:
                slot.thread.join(STOP_WAIT_S * 2)
        with self._lock:
            self._phase = "closed"

    def request(
        self,
        op: str,
        source: PreviewSource | None,
        params: JsonObject | None = None,
        *,
        timeout_s: float | None = None,
    ) -> RenderResult:
        """Run an operation, from the cache when it is there; wait for it.

        Parameters
        ----------
        op : str
            An operation of ``OPERATIONS``.
        source : PreviewSource or None
            The file (``None`` for operations whose parameters carry it).
        params : dict or None, optional
            Parameters of the operation (JSON).
        timeout_s : float or None, optional
            Time limit of the rendering instead of the operation's.

        Returns
        -------
        RenderResult
            The result.

        Raises
        ------
        PreviewBusyError
            The queue is full, or the pool is closing.
        PreviewTimeoutError
            The rendering ran past its limit, now or within 10 minutes.
        PreviewUnavailableError
            The file has no such preview (``reason``).
        RendererStartError
            No render process could be started (nothing is remembered).
        ValueError
            An unknown operation or parameters that are not JSON.
        """
        prepared = self._prepare(op, source, params, timeout_s)
        found = self._lookup(prepared)
        if isinstance(found, RenderResult):
            return found
        call = self._enter(found)
        try:
            return call.future.result()
        finally:
            self._leave(call)

    async def arequest(
        self,
        op: str,
        source: PreviewSource | None,
        params: JsonObject | None = None,
        *,
        timeout_s: float | None = None,
    ) -> RenderResult:
        """Run an operation like ``request``, awaiting it.

        Cancelling the awaiting task gives the request up: when no other
        caller waits for it and no process took it yet, it leaves the queue
        unrendered.
        """
        prepared = self._prepare(op, source, params, timeout_s)
        found = await asyncio.to_thread(self._lookup, prepared)
        if isinstance(found, RenderResult):
            return found
        call = self._enter(found)
        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[RenderResult] = loop.create_future()

        def deliver(done: concurrent.futures.Future[RenderResult]) -> None:
            with contextlib.suppress(RuntimeError):  # the loop is closed
                loop.call_soon_threadsafe(_relay, done, waiter)

        call.future.add_done_callback(deliver)
        try:
            return await waiter
        finally:
            self._leave(call)

    def stats(self) -> PoolStats:
        """Return the pool's processes, queue and counts now."""
        with self._lock:
            alive = sum(
                slot.process is not None and slot.process.poll() is None
                for slot in self._slots
            )
            return PoolStats(
                workers=len(self._slots),
                alive=alive,
                queued=len(self._queue),
                rendering=self._rendering,
                rendered=self._rendered,
                abandoned=self._abandoned,
            )

    # Callers' side.

    def _prepare(
        self,
        op: str,
        source: PreviewSource | None,
        params: JsonObject | None,
        timeout_s: float | None,
    ) -> _Prepared:
        operation = OPERATIONS.get(op)
        if operation is None:
            raise ValueError(f"unknown render operation {op!r}")
        values = dict(params or {})
        try:
            target = (
                None if operation.target is None else operation.target(source, values)
            )
            basis = [
                op,
                None if source is None else str(cache_key(source).directory),
                {name: value for name, value in values.items() if name != "probe"},
            ]
            text = json.dumps(basis, sort_keys=True, separators=(",", ":"))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid parameters of {op}: {error}") from error
        if target is not None:
            key = f"{op}:{target[0].directory}/{target[1]}"
        else:
            key = f"{op}:{hashlib.sha256(text.encode()).hexdigest()}"
        request = RenderRequest(secrets.token_hex(8), op, source, values)
        limit = self._timeouts[op] if timeout_s is None else timeout_s
        return _Prepared(key, request, operation, limit, target)

    def _lookup(self, prepared: _Prepared) -> RenderResult | _Prepared:
        """Answer from the cache, or add the cached probe to the request.

        Raises
        ------
        PreviewUnavailableError
            The cached probe says no operation can succeed (``unreadable``,
            ``unsupported_format``).
        """
        request = prepared.request
        try:
            if prepared.target is not None:
                data = self._cache.get(*prepared.target)
                if data is not None:
                    return RenderResult(data, cached=True)
            if request.source is None or request.op == "probe":
                return prepared
            if "probe" in request.params:
                return prepared
            info = self._cache.get(cache_key(request.source), INFO_NAME)
        except (OSError, sqlite3.Error):
            logger.exception("Reading the preview cache failed")
            return prepared
        if info is None:
            return prepared
        try:
            probe = PreviewProbe.from_bytes(info)
        except ValueError:  # a damaged object: the process probes again
            return prepared
        if probe.reason is not None and probe.reason in UNRENDERABLE_REASONS:
            raise PreviewUnavailableError(probe.reason)
        params = {**request.params, "probe": probe.to_json()}
        return replace(prepared, request=replace(request, params=params))

    def _enter(self, prepared: _Prepared) -> _Call:
        """Join the call of an equal request, or queue a new one."""
        with self._lock:
            if self._phase != "open":
                raise PreviewBusyError(
                    message("preview.closed"), retry_after_s=RETRY_AFTER_S
                )
            now = time.monotonic()
            failure = self._failures.get(prepared.key)
            if failure is not None:
                if failure.until > now:
                    raise _remembered(failure, now)
                del self._failures[prepared.key]
            call = self._calls.get(prepared.key)
            if call is None:
                if len(self._queue) >= self._queue_size:
                    text = message("preview.busy", seconds=RETRY_AFTER_S)
                    raise PreviewBusyError(text, retry_after_s=RETRY_AFTER_S)
                call = _Call(prepared)
                self._calls[prepared.key] = call
                self._queue.append(call)
                self._ready.notify()
            call.waiters += 1
            return call

    def _leave(self, call: _Call) -> None:
        """One caller is done; drop a request nobody waits for any more."""
        with self._lock:
            call.waiters -= 1
            if call.waiters > 0 or call.started or call.future.done():
                return
            with contextlib.suppress(ValueError):
                self._queue.remove(call)
            self._forget(call)
            self._abandoned += 1
        call.future.cancel()

    def _forget(self, call: _Call) -> None:
        if self._calls.get(call.prepared.key) is call:
            del self._calls[call.prepared.key]

    # Processes' side: one thread per slot.

    def _serve(self, slot: _Slot) -> None:
        try:
            while True:
                call, idle = self._next(slot)
                if idle:
                    self._stop(slot)
                    continue
                if call is None:
                    return
                self._run(slot, call)
        finally:
            self._stop(slot)

    def _next(self, slot: _Slot) -> tuple[_Call | None, bool]:
        """Take the next request, or say the slot's process is idle."""
        with self._lock:
            while self._phase == "open":
                if self._queue:
                    call = self._queue.popleft()
                    call.started = True
                    self._rendering += 1
                    self._rendered += 1
                    return call, False
                if slot.process is None:
                    self._ready.wait()
                    continue
                remaining = slot.last_used + self._idle_s - time.monotonic()
                if remaining <= 0:
                    return None, True
                self._ready.wait(remaining)
            return None, False

    def _run(self, slot: _Slot, call: _Call) -> None:
        outcome: _Outcome
        try:
            answer = self._exchange(slot, call)
        except _TimedOut:
            self._kill(slot)
            outcome = self._failed(call, "timeout")
        except _Ended as ended:
            outcome = self._ended(call, ended.status)
        except _Closed:
            outcome = PreviewBusyError(
                message("preview.closed"), retry_after_s=RETRY_AFTER_S
            )
        except Exception as error:  # cannot start a process, broken protocol
            logger.exception("Rendering %s failed", call.prepared.request.op)
            self._kill(slot)
            outcome = error
        else:
            outcome = self._answered(slot, call, answer)
        slot.last_used = time.monotonic()
        with self._lock:
            self._rendering -= 1
            self._forget(call)
        _settle(call.future, outcome)

    def _exchange(self, slot: _Slot, call: _Call) -> RenderAnswer:
        """Send the request to the slot's process and read its answer."""
        request = call.prepared.request
        process = self._ensure(slot)
        lines = cast("queue.Queue[bytes | None]", slot.lines)
        stdin = cast(IO[bytes], process.stdin)
        try:
            stdin.write((encode_request(request) + "\n").encode("utf-8"))
            stdin.flush()
        except OSError:  # the process ended meanwhile
            raise _Ended(self._reap(slot)) from None
        deadline = time.monotonic() + call.prepared.timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _TimedOut
            try:
                raw = lines.get(timeout=remaining)
            except queue.Empty:
                raise _TimedOut from None
            if raw is None:
                raise _Ended(self._reap(slot))
            try:
                answer = decode_answer(raw.decode("utf-8", "replace"))
            except RenderProtocolError as error:
                logger.warning("Render process %d: %s", process.pid, error)
                continue
            if answer.id == request.id:
                return answer

    def _answered(self, slot: _Slot, call: _Call, answer: RenderAnswer) -> _Outcome:
        prepared = call.prepared
        if answer.ok:
            data = answer.files.get(prepared.operation.result)
            if data is None:
                return RuntimeError(
                    f"render answer without {prepared.operation.result}"
                )
            self._keep(prepared, data)
            self._keep_others(prepared, answer.files)
            return RenderResult(data)
        code = cast(str, answer.code)
        if code == CODE_PROTOCOL_ERROR:
            return RuntimeError(f"render protocol error: {answer.detail}")
        if code == "memory_limit":
            self._reap(slot)  # the process ends after this answer
            return self._failed(call, "memory_limit")
        if code == "timeout":
            return self._failed(call, "timeout")
        return self._unavailable(prepared, code, answer.detail)

    def _unavailable(
        self, prepared: _Prepared, code: str, detail: str | None
    ) -> _Outcome:
        """Return the outcome of a file without such a preview.

        A probe's lasting reason is kept in the cache as ``info.json``.
        """
        source = prepared.request.source
        lasting = code in PREVIEW_REASONS and code not in TRANSIENT_REASONS
        if prepared.request.op == "probe" and source is not None and lasting:
            reason = cast(PreviewReason, code)
            data = PreviewProbe(kind=source.kind, reason=reason).to_bytes()
            self._keep(prepared, data)
            return RenderResult(data, detail=detail)
        return PreviewUnavailableError(code, detail)

    def _ended(self, call: _Call, status: int | None) -> _Outcome:
        """Return the outcome of a process that ended without answering."""
        with self._lock:
            closing = self._phase != "open"
        if closing:
            return PreviewBusyError(
                message("preview.closed"), retry_after_s=RETRY_AFTER_S
            )
        if status == -signal.SIGKILL:  # killed by the system, out of memory
            return self._failed(call, "memory_limit")
        detail = f"render process ended without an answer ({_status(status)})"
        return self._unavailable(call.prepared, "unreadable", detail)

    def _failed(
        self, call: _Call, code: Literal["timeout", "memory_limit"]
    ) -> _Outcome:
        """Remember a failure depending on the load and return its error."""
        now = time.monotonic()
        with self._lock:
            self._failures = {
                key: failure
                for key, failure in self._failures.items()
                if failure.until > now
            }
            self._failures[call.prepared.key] = _Failure(code, now + self._failure_s)
        if code == "timeout":
            seconds = math.ceil(call.prepared.timeout_s)
            return PreviewTimeoutError(message("preview.timeout", seconds=seconds))
        return PreviewUnavailableError("memory_limit")

    def _keep(self, prepared: _Prepared, data: bytes) -> None:
        if prepared.target is None:
            return
        try:
            self._cache.put(*prepared.target, data)
        except (OSError, sqlite3.Error):
            logger.exception("Keeping a preview in the cache failed")

    def _keep_others(self, prepared: _Prepared, files: Mapping[str, bytes]) -> None:
        """Keep the files of other objects an answer carries (``object_file``).

        A layer's tile or thumbnail brings its versions' own ones rendered on
        the way: each goes to its version's object, rendered once for every
        layer and view.
        """
        for name, data in files.items():
            if name == prepared.operation.result:
                continue
            try:
                key, file = parse_object_file(name)
                self._cache.put(key, file, data)
            except ValueError:
                logger.warning("A render answer named no cache object: %r", name)
            except (OSError, sqlite3.Error):
                logger.exception("Keeping a preview in the cache failed")

    def _ensure(self, slot: _Slot) -> subprocess.Popen[bytes]:
        """Return the slot's live process, started when needed.

        A process that cannot be started is a ``RendererStartError``: a
        fault of this computer, never remembered as the file's.
        """
        process = slot.process
        if process is not None and process.poll() is None:
            return process
        self._discard(slot)
        with self._lock:
            if self._phase != "open":
                raise _Closed
            argv = [*self._command, "--previews-dir", str(self._cache.root)]
            if self._work_dir is not None:
                argv += ["--work-dir", str(self._work_dir)]
            try:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    cwd=self._cache.root,
                    env=untrusted_env(),
                    **child_limits(self._memory_bytes),
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise RendererStartError from error
            lines: queue.Queue[bytes | None] = queue.Queue()
            reader = threading.Thread(
                target=_pump,
                args=(cast(IO[bytes], process.stdout), lines),
                name=f"archiwista-render-{slot.index}-out",
                daemon=True,
            )
            reader.start()
            slot.process, slot.lines, slot.reader = process, lines, reader
        return process

    def _reap(self, slot: _Slot) -> int | None:
        """Wait for a process that is ending; return its status."""
        process = slot.process
        if process is None:
            return None
        try:
            status = process.wait(STOP_WAIT_S)
        except subprocess.TimeoutExpired:
            kill_untrusted(process)
            status = process.wait()
        self._discard(slot)
        return status

    def _kill(self, slot: _Slot) -> None:
        process = slot.process
        if process is not None:
            kill_untrusted(process)
            process.wait()
        self._discard(slot)

    def _stop(self, slot: _Slot) -> None:
        """End the slot's process: close its input, kill it if it stays."""
        process = slot.process
        if process is None:
            return
        if process.stdin is not None:
            with contextlib.suppress(OSError):
                process.stdin.close()
        self._reap(slot)

    def _discard(self, slot: _Slot) -> None:
        """Forget the slot's ended process and close its pipes."""
        process = slot.process
        with self._lock:
            slot.process, slot.lines = None, None
            reader, slot.reader = slot.reader, None
        if process is None:
            return
        if process.poll() is None:
            kill_untrusted(process)
            process.wait()
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
        if reader is not None:
            reader.join(STOP_WAIT_S)


def _pump(stream: IO[bytes], lines: "queue.Queue[bytes | None]") -> None:
    """Pass a process's output lines on; ``None`` at its end."""
    try:
        for raw in iter(stream.readline, b""):
            lines.put(raw)
    except (OSError, ValueError):  # closed meanwhile
        pass
    finally:
        lines.put(None)


def _remembered(failure: _Failure, now: float) -> Exception:
    if failure.code == "timeout":
        minutes = max(1, math.ceil((failure.until - now) / 60))
        return PreviewTimeoutError(message("preview.timeout_recent", minutes=minutes))
    return PreviewUnavailableError("memory_limit")


def _settle(future: concurrent.futures.Future[RenderResult], outcome: _Outcome) -> None:
    with contextlib.suppress(concurrent.futures.InvalidStateError):
        if isinstance(outcome, BaseException):
            future.set_exception(outcome)
        else:
            future.set_result(outcome)


def _relay(
    done: concurrent.futures.Future[RenderResult],
    waiter: "asyncio.Future[RenderResult]",
) -> None:
    if waiter.done():
        return
    if done.cancelled():
        waiter.cancel()
        return
    error = done.exception()
    if error is not None:
        waiter.set_exception(error)
    else:
        waiter.set_result(done.result())


def _status(status: int | None) -> str:
    if status is None:
        return "status unknown"
    if status < 0:
        with contextlib.suppress(ValueError):
            return f"signal {signal.Signals(-status).name}"
        return f"signal {-status}"
    return f"exit code {status}"
