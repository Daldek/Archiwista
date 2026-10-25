"""The ``preview`` job: local previews built file by file (decisions 3 and 6).

``run_preview`` runs in the job's worker process (``RUNNERS`` of
``archiwista.jobs.worker``). Its parameters, checked by the supervisor, are
``refs`` (at most 500), ``contents`` (the content key of each ref) and
``force`` (past the auto-build limits: a file over 2 GB, a raster over
1 Gpx or 8 GB unpacked). The job builds each content once, however many
refs share it:

1. each ref becomes its source through the resolver of its kind
   (``RESOLVERS``, by the text before the first ``:``), in the job's main
   thread;
2. a content whose preview is built (its ``info.json`` and, when it needs
   one, its local COG in the preview cache) is skipped as ``cached``;
3. the others are built, at most ``build_processes()`` at once, each in a
   render process of its own (``BUILD_COMMAND``, operation ``build``) with
   the sandbox, 10 minutes and 4 GiB; the object stays pinned in the cache
   while it is built. The process writes into this process's ``.incoming``
   directory of the cache, and the result moves into the cache.

A file whose build fails (time limit, memory, unreadable, too large without
``force``) fails alone: the job goes on, and its summary names it in
``failed`` with ``ref``, ``code`` and a Polish ``detail`` without paths; a
ref that does not resolve fails with a detail of its own, naming no other
ref of the same content.
Progress: ``current`` of ``total`` contents with ``built``, ``cached`` and
``failed``; the summary: ``built``, ``cached``, ``failed`` and ``seconds``.
An interrupt kills the build processes before the job ends.
"""

import concurrent.futures
import contextlib
import os
import secrets
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from archiwista.errors import (
    InvalidRefError,
    NotFoundError,
    OwnFileChangedError,
    PathOutsideRootError,
    PreviewUnavailableError,
    SourceUnavailableError,
)
from archiwista.jobs.protocol import JobSpec, JsonObject
from archiwista.messages import lookup, message, with_detail
from archiwista.previews.cache import INFO_NAME, CacheKey, PreviewCache, cache_key
from archiwista.previews.protocol import (
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
    PreviewProbe,
    PreviewReason,
    PreviewSource,
    auto_build,
    build_product,
)
from archiwista.previews.worker import BUILD
from archiwista.refs import job_resolver
from archiwista.sandbox import child_limits, kill_untrusted, untrusted_env

if TYPE_CHECKING:
    from archiwista.jobs.worker import Emitter

type SourceResolver = Callable[[str], PreviewSource]
type ResolverFactory = Callable[[JobSpec], SourceResolver]

# How the job turns a ref into its source, by the ref's kind (decision 10):
# ``version`` (step 6), ``file`` and ``snapshot`` (step 9), all through
# ``ObjectResolver``. A resolver raises ``InvalidRefError``,
# ``NotFoundError``, ``PathOutsideRootError``, ``OwnFileChangedError`` (a
# working file changed since its scan: ``changed_since_scan``),
# ``SourceUnavailableError`` (``store_unavailable``) or
# ``PreviewUnavailableError`` (e.g. ``missing_file``); it runs in the job's
# main thread only.
RESOLVERS: Mapping[str, ResolverFactory] = {
    "version": job_resolver,
    "file": job_resolver,
    "snapshot": job_resolver,
}
BUILD_COMMAND: tuple[str, ...] = RENDER_WORKER_COMMAND
BUILD_TIMEOUT_S = BUILD.timeout_s
BUILD_MEMORY_BYTES = 4 * 1024**3


def build_processes() -> int:
    """Build processes of one ``preview`` job at once: half the processors."""
    return max(1, (os.cpu_count() or 2) // 2)


@dataclass(frozen=True, slots=True)
class _Outcome:
    """How the build of one content ended, for all its refs.

    ``unresolved``: the failure of each ref when none of them resolved, each
    with its own code and detail, so a failure names no other ref of the
    same content (another project's file of the same bytes, decision 3).
    """

    status: Literal["built", "cached", "failed"]
    refs: tuple[str, ...]
    code: str | None = None
    detail: str | None = None
    unresolved: tuple[JsonObject, ...] = ()

    def failures(self) -> list[JsonObject]:
        if self.unresolved:
            return list(self.unresolved)
        return [
            {"ref": ref, "code": self.code, "detail": self.detail} for ref in self.refs
        ]


class _Interrupted(Exception):
    """The job is being interrupted; no new build process starts."""


class _Ended(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


def run_preview(spec: JobSpec, emit: "Emitter") -> JsonObject:
    """Build the previews of the job's refs; return the job's summary."""
    started = time.perf_counter()
    force = bool(spec.params.get("force", False))
    groups = _groups(spec.params["refs"], spec.params["contents"])
    total = len(groups)
    counts = {"built": 0, "cached": 0}
    failed: list[JsonObject] = []
    emit.progress(0, total, built=0, cached=0, failed=0)
    limit = spec.settings.preview_cache_limit_bytes
    with PreviewCache(spec.previews_dir, limit_bytes=limit) as cache:
        builder = _Builder(spec, cache, force=force)
        sources = [(refs, builder.resolve(refs)) for refs in groups.values()]
        workers = max(1, min(build_processes(), total))
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="archiwista-build"
        ) as executor:
            futures = [
                executor.submit(builder.build, refs, source) for refs, source in sources
            ]
            try:
                for done, future in enumerate(
                    concurrent.futures.as_completed(futures), start=1
                ):
                    outcome = future.result()
                    if outcome.status == "failed":
                        failed.extend(outcome.failures())
                    else:
                        counts[outcome.status] += 1
                    emit.progress(done, total, **counts, failed=len(failed))
            except BaseException:  # an interrupt: no build may outlive the job
                builder.stop()
                for future in futures:
                    future.cancel()
                raise
    return {
        **counts,
        "failed": failed,
        "seconds": round(time.perf_counter() - started, 3),
    }


class _Builder:
    """Builds of one job: resolution, the cache, the build processes."""

    def __init__(self, spec: JobSpec, cache: PreviewCache, *, force: bool) -> None:
        self._spec = spec
        self._cache = cache
        self._force = force
        self._resolvers: dict[str, SourceResolver] = {}
        self._lock = threading.Lock()
        self._children: set[subprocess.Popen[bytes]] = set()
        self._stopped = False

    def resolve(self, refs: Sequence[str]) -> PreviewSource | _Outcome:
        """Return the source of the first ref that resolves, else each failure."""
        failures: list[JsonObject] = []
        for ref in refs:
            found = self._resolve(ref)
            if isinstance(found, PreviewSource):
                return found
            code, detail = found
            failures.append({"ref": ref, "code": code, "detail": detail})
        return _Outcome("failed", tuple(refs), unresolved=tuple(failures))

    def _resolve(self, ref: str) -> PreviewSource | tuple[str, str]:
        """Return a ref's source, or the code and Polish detail of its failure."""
        scheme = ref.partition(":")[0]
        factory = RESOLVERS.get(scheme)
        if factory is None:
            return "invalid_ref", _unresolved(ref, None)
        if scheme not in self._resolvers:
            self._resolvers[scheme] = factory(self._spec)
        try:
            return self._resolvers[scheme](ref)
        except InvalidRefError as error:
            return "invalid_ref", _unresolved(ref, str(error))
        except NotFoundError as error:
            return "not_found", _unresolved(ref, str(error))
        except PathOutsideRootError as error:
            return "path_outside_root", _unresolved(ref, str(error))
        except OwnFileChangedError as error:
            return "changed_since_scan", str(error)
        except SourceUnavailableError as error:
            return "store_unavailable", str(error)
        except PreviewUnavailableError as error:
            reason = error.reason
            return reason, lookup(f"preview.reason_{reason}", reason)

    def build(self, refs: Sequence[str], source: PreviewSource | _Outcome) -> _Outcome:
        """Build one content unless it is built already; never raise for it."""
        if isinstance(source, _Outcome):
            return source
        key = cache_key(source)
        names = tuple(refs)
        info = self._cache.get(key, INFO_NAME)
        probe = None if info is None else _probe_of(info)
        if probe is not None:
            if probe.reason is not None and probe.reason in UNRENDERABLE_REASONS:
                return _failure(names, probe.reason, None)
            product = build_product(probe)
            if product is None or self._cache.has(key, product):
                return _Outcome("cached", names)
            if not self._force and not auto_build(source, probe):
                return _failure(names, "too_large", None)
        self._cache.pin(key)
        try:
            return self._build(names, source, key, probe)
        except _Interrupted:
            return _Outcome("failed", names, "interrupted", message("job.cancelled"))
        finally:
            self._cache.unpin(key)

    def stop(self) -> None:
        """Start no more build processes and kill the running ones."""
        with self._lock:
            self._stopped = True
            children = tuple(self._children)
        for process in children:
            kill_untrusted(process)

    def _build(
        self,
        refs: tuple[str, ...],
        source: PreviewSource,
        key: CacheKey,
        probe: PreviewProbe | None,
    ) -> _Outcome:
        out = self._cache.incoming_dir() / f"build-{secrets.token_hex(8)}"
        params: JsonObject = {"out": str(out), "force": self._force}
        if probe is not None:
            params["probe"] = probe.to_json()
        request = RenderRequest(secrets.token_hex(8), "build", source, params)
        try:
            answer = self._run(request)
        except subprocess.TimeoutExpired:
            return _failure(refs, "timeout", None)
        except _Ended as ended:
            code = "memory_limit" if ended.status == -signal.SIGKILL else "unreadable"
            detail = f"build process ended without an answer ({_status(ended.status)})"
            return _failure(refs, code, detail)
        try:
            return self._keep(refs, source, key, answer, out)
        finally:
            out.unlink(missing_ok=True)

    def _keep(
        self,
        refs: tuple[str, ...],
        source: PreviewSource,
        key: CacheKey,
        answer: RenderAnswer,
        out: Path,
    ) -> _Outcome:
        """Move a build's results into the cache."""
        if not answer.ok:
            code = str(answer.code)
            lasting = code in PREVIEW_REASONS and code not in TRANSIENT_REASONS
            if lasting and not self._cache.has(key, INFO_NAME):
                probe = PreviewProbe(kind=source.kind, reason=_reason(code))
                self._cache.put(key, INFO_NAME, probe.to_bytes())
            return _failure(refs, code, answer.detail)
        info = answer.files.get(INFO_NAME)
        if info is None:
            return _failure(refs, "unreadable", "build answer without info.json")
        self._cache.put(key, INFO_NAME, info)
        product = build_product(PreviewProbe.from_bytes(info))
        if product is None:
            return _Outcome("cached", refs)
        if not out.is_file() or out.stat().st_size == 0:
            return _failure(refs, "unreadable", "the build wrote nothing")
        self._cache.put(key, product, out)
        return _Outcome("built", refs)

    def _run(self, request: RenderRequest) -> RenderAnswer:
        """Run one build process to its end and return its answer."""
        argv = [*BUILD_COMMAND, "--work-dir", str(self._spec.work_dir)]
        with self._lock:
            if self._stopped:
                raise _Interrupted
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self._cache.root,
                env=untrusted_env(),
                **child_limits(BUILD_MEMORY_BYTES),
            )
            self._children.add(process)
        try:
            data = (encode_request(request) + "\n").encode("utf-8")
            try:
                output, _ = process.communicate(data, timeout=BUILD_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                kill_untrusted(process)
                process.communicate()
                raise
            except BaseException:
                kill_untrusted(process)
                process.wait()
                raise
        finally:
            with self._lock:
                self._children.discard(process)
                stopped = self._stopped
        if stopped:
            raise _Interrupted
        for line in output.decode("utf-8", "replace").splitlines():
            with contextlib.suppress(RenderProtocolError):
                answer = decode_answer(line)
                if answer.id == request.id:
                    return answer
        raise _Ended(process.returncode)


def _groups(refs: Sequence[str], contents: Sequence[str]) -> dict[str, list[str]]:
    """Return the refs of each content, contents in the order of first use."""
    groups: dict[str, list[str]] = {}
    for ref, content in zip(refs, contents, strict=True):
        groups.setdefault(content, []).append(ref)
    return groups


def _unresolved(ref: str, detail: str | None) -> str:
    """Return why a ref of the job did not resolve, in Polish."""
    reason = detail or message("preview.build_unknown_ref")
    return message("preview.build_unresolved", ref=ref, detail=reason)


def _failure(refs: tuple[str, ...], code: str, detail: str | None) -> _Outcome:
    """Return a failed build with a Polish detail (the library's appended)."""
    if code == "timeout":
        minutes = round(BUILD_TIMEOUT_S / 60)
        text: str = message("preview.build_timeout", minutes=minutes)
    elif code == "too_large":
        text = message("preview.build_too_large")
    else:
        reason = lookup(f"preview.reason_{code}", code)
        text = with_detail(reason, detail)
    return _Outcome("failed", refs, code, text)


def _probe_of(info: bytes) -> PreviewProbe | None:
    try:
        return PreviewProbe.from_bytes(info)
    except ValueError:  # a damaged object: built again
        return None


def _reason(code: str) -> PreviewReason:
    if code not in PREVIEW_REASONS:
        raise ValueError(f"unknown preview reason {code!r}")
    return code


def _status(status: int) -> str:
    if status < 0:
        with contextlib.suppress(ValueError):
            return f"signal {signal.Signals(-status).name}"
        return f"signal {-status}"
    return f"exit code {status}"
