"""Render process: ``python -P -m archiwista.previews.worker [--work-dir DIR]``.

The render pool keeps a few of these processes alive (decision 3); the
``preview`` job starts one per file it builds (operation ``build``). Each is
started with the sandbox (``archiwista.sandbox``: no network, no sibling
files, explicit drivers, ``RLIMIT_AS``), reads requests of
``archiwista.previews.protocol`` on standard input until it ends and
answers each in order on standard output; whatever libraries print goes to
standard error, which the pool discards (it may name paths).

``OPERATIONS`` registers each operation of the pool with its time limit, its
handler (run here, by the renderer of the source's kind from
``archiwista.previews.renderers.RENDERERS``) and where the pool keeps its
result in the preview cache; one line per operation. Before an answer leaves
the process, every path of the source, its real path and their directories
in an error's detail become file names (``scrub_paths``). An own-data
working file (``PreviewSource.mutable``) is checked against its scan before
and after rendering (``changed_since_scan``). After running out of memory
the process answers ``memory_limit`` and ends, so the next request gets a
fresh one. A renderer reads a large file the cache keeps for its source (the
local COG, a consistent copy of an own-data SQLite file) through
``cached_file``; the cache's directory is ``--previews-dir DIR``.

This module imports no preview library at import time: the server reads
``OPERATIONS`` from it; renderers are loaded when the process starts.
"""

import argparse
import contextlib
import json
import logging
import os
import secrets
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, cast

from archiwista.errors import FormatRefusedError, PreviewUnavailableError
from archiwista.previews.cache import (
    INFO_NAME,
    OBJECTS_DIR,
    RENDERER_VERSIONS,
    CacheKey,
    cache_key,
    thumbnail_name,
    tile_name,
)
from archiwista.previews.compose import (
    LAYER_THUMBNAIL,
    LAYER_TILE,
    layer_thumbnail,
    layer_thumbnail_target,
    layer_tile,
    layer_tile_target,
)
from archiwista.previews.protocol import (
    CODE_PROTOCOL_ERROR,
    RenderAnswer,
    RenderProtocolError,
    RenderRequest,
    decode_request,
    encode_answer,
    scrub_paths,
)
from archiwista.previews.types import (
    Extent,
    FileStat,
    JsonObject,
    PreviewProbe,
    PreviewSource,
    Renderer,
    auto_build,
    build_product,
)
from archiwista.sandbox import process_dir

# Status of a process that ran out of memory: the pool starts a new one.
MEMORY_EXIT = 3
# Names of the results in an answer's ``files``.
IMAGE_NAME = "image.png"
FEATURES_NAME = "features.json"
MEMBERS_NAME = "members.json"

logger = logging.getLogger("archiwista.previews.worker")

type Handler = Callable[[Sequence[Renderer], RenderRequest], dict[str, bytes]]
type Target = Callable[[PreviewSource | None, JsonObject], tuple[CacheKey, str] | None]

_work_root: Path | None = None
_previews_root: Path | None = None


@dataclass(frozen=True, slots=True)
class Operation:
    """An operation of the render pool.

    Attributes
    ----------
    timeout_s : float
        Wall-clock seconds a render process has for it before it is killed.
    handler : Handler
        Runs the operation in the render process; returns the answer's
        ``files``.
    result : str
        Name of the result in ``files``.
    target : Target or None
        Cache object and name the pool keeps the result under (``None``:
        never kept).
    """

    timeout_s: float
    handler: Handler
    result: str
    target: Target | None = None


def main(
    argv: Sequence[str] | None = None, *, renderers: Sequence[Renderer] | None = None
) -> int:
    """Answer the requests on standard input; return the exit status.

    Parameters
    ----------
    argv : Sequence[str] or None, optional
        Arguments (``--work-dir``: root of the processes' work directories,
        ``AppPaths.work_dir``; ``--previews-dir``: the preview cache,
        ``AppPaths.previews_dir``); ``sys.argv[1:]`` when omitted.
    renderers : Sequence[Renderer] or None, optional
        Renderers to use; ``RENDERERS`` when omitted (tests give their own).

    Returns
    -------
    int
        ``0`` at the end of the input, ``MEMORY_EXIT`` after running out of
        memory.
    """
    global _work_root, _previews_root
    arguments = _parser().parse_args(argv)
    _work_root = arguments.work_dir
    _previews_root = arguments.previews_dir
    protocol = _protocol_stream()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    if renderers is None:
        from archiwista.previews.renderers import RENDERERS

        renderers = RENDERERS
    stdin = sys.stdin.buffer
    for raw in iter(stdin.readline, b""):
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        answer = answer_line(line, renderers)
        protocol.write(encode_answer(answer) + "\n")
        protocol.flush()
        if answer.code == "memory_limit":
            return MEMORY_EXIT
    return 0


def work_dir() -> Path:
    """Return this process's own work directory (``--work-dir``).

    Raises
    ------
    RuntimeError
        The process was started without ``--work-dir``.
    """
    if _work_root is None:
        raise RuntimeError("the render process has no work directory")
    return process_dir(_work_root)


@contextlib.contextmanager
def cached_file(source: PreviewSource, name: str) -> Iterator[Path | None]:
    """Hold a large file of the source's preview cache object while reading it.

    For ``cog.tif`` and ``source.gpkg`` (decision 3). The file is linked
    into this process's work directory, so another process evicting the
    object meanwhile leaves it readable to the end of the block, also to
    libraries opening it more than once; where no link can be made (another
    file system, no ``--work-dir``) the cache's own path is given. Render
    processes only read the cache: the pool and the ``preview`` job put
    into it.

    Parameters
    ----------
    source : PreviewSource
        The file whose object holds it (``cache_key(source)``).
    name : str
        The file in the object, e.g. ``COG_NAME``.

    Yields
    ------
    Path or None
        A path of the file, valid inside the block; ``None`` when the cache
        has no such file or the process has no ``--previews-dir``.
    """
    if _previews_root is None:
        yield None
        return
    found = _previews_root.joinpath(*cache_key(source).directory.parts, name)
    if _work_root is None:
        yield found if found.is_file() else None
        return
    link = work_dir() / f"cached-{secrets.token_hex(8)}-{found.name}"
    try:
        os.link(found, link)
    except FileNotFoundError:
        yield None
        return
    except OSError:  # another file system, or no hard links there
        yield found if found.is_file() else None
        return
    try:
        yield link
    finally:
        link.unlink(missing_ok=True)


def cached_bytes(key: CacheKey, name: str) -> bytes | None:
    """Return a small file of a preview cache object, read whole (not a use).

    For another object than the request's: a version's tile or probe in a
    layer (``archiwista.previews.compose``). ``None`` on a miss or without
    ``--previews-dir``.
    """
    if _previews_root is None:
        return None
    try:
        return _previews_root.joinpath(
            *key.directory.parts, *name.split("/")
        ).read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None


def object_file(key: CacheKey, name: str) -> str:
    """Return the name in an answer's ``files`` of a file of another object.

    An operation may render, on its way, files of other objects (a layer
    tile: its versions' tiles); the pool keeps each under its object
    (``parse_object_file``), so it is rendered once.
    """
    return f"{key.directory}/{name}"


def parse_object_file(text: str) -> tuple[CacheKey, str]:
    """Return the object and file name of ``object_file``.

    Raises
    ------
    ValueError
        Not such a name, or an object of another renderer version than the
        current one.
    """
    parts = text.split("/")
    if len(parts) < 5 or parts[0] != OBJECTS_DIR:
        raise ValueError(f"not a file of a cache object: {text!r}")
    prefix, content, renderer, *name = parts[1:]
    found, _, version = renderer.partition("-r")
    if prefix != content[:2] or found not in RENDERER_VERSIONS or not version.isdigit():
        raise ValueError(f"not a file of a cache object: {text!r}")
    key = CacheKey(content, found, int(version))  # type: ignore[arg-type]
    if key.renderer_version != RENDERER_VERSIONS[key.renderer]:
        raise ValueError(f"an object of an older renderer: {text!r}")
    return key, "/".join(name)


def answer_line(line: str, renderers: Sequence[Renderer]) -> RenderAnswer:
    """Run the request of one line and return its answer, paths scrubbed."""
    try:
        request = decode_request(line)
    except RenderProtocolError as error:
        return RenderAnswer(
            _request_id(line), code=CODE_PROTOCOL_ERROR, detail=str(error)
        )
    operation = OPERATIONS.get(request.op) or (BUILD if request.op == "build" else None)
    if operation is None:
        unknown = f"unknown operation {request.op!r}"
        return RenderAnswer(request.id, code=CODE_PROTOCOL_ERROR, detail=unknown)
    source = request.source
    code: str
    detail: str | None
    try:
        if source is not None:
            require_unchanged(source)
        files = operation.handler(renderers, request)
        if source is not None:
            require_unchanged(source)
    except PreviewUnavailableError as error:
        code, detail = error.reason, error.detail
    except FormatRefusedError as error:
        code, detail = "unsupported_format", str(error)
    except FileNotFoundError:
        code, detail = "missing_file", None
    except MemoryError:
        code, detail = "memory_limit", None
    except Exception as error:  # a library failing on the file
        code, detail = "unreadable", f"{type(error).__name__}: {error}"
    else:
        return RenderAnswer(request.id, files=files)
    if detail is not None:
        paths = () if source is None else source.paths
        hidden = () if _work_root is None else (_work_root,)
        detail = scrub_paths(detail, paths, directories=hidden)
    return RenderAnswer(request.id, code=code, detail=detail)


def renderer_for(renderers: Sequence[Renderer], source: PreviewSource) -> Renderer:
    """Return the renderer of a source's kind.

    Raises
    ------
    PreviewUnavailableError
        ``unsupported_format``: no renderer handles the kind.
    """
    kind = source.kind
    for renderer in renderers:
        if kind in renderer.kinds:
            return renderer
    raise PreviewUnavailableError("unsupported_format", f"no renderer of {kind} files")


def _probe(renderers: Sequence[Renderer], request: RenderRequest) -> dict[str, bytes]:
    source = _source(request)
    return {INFO_NAME: renderer_for(renderers, source).probe(source).to_bytes()}


def _thumbnail(
    renderers: Sequence[Renderer], request: RenderRequest
) -> dict[str, bytes]:
    source, renderer, probe = _prepared(renderers, request)
    params = request.params
    frame = params.get("frame")
    layer = params.get("layer")
    image = renderer.thumbnail(
        source,
        probe,
        str(params["style"]),
        int(params["size"]),
        None if frame is None else Extent(_bbox(frame["bbox"]), str(frame["crs"])),
        **({} if layer is None else {"layer": str(layer)}),
    )
    return {IMAGE_NAME: image}


def _tile(renderers: Sequence[Renderer], request: RenderRequest) -> dict[str, bytes]:
    source, renderer, probe = _prepared(renderers, request)
    params = request.params
    extra = {
        name: value
        for name, value in params.items()
        if name not in ("style", "z", "x", "y", "probe")
    }
    image = renderer.tile(
        source,
        probe,
        str(params["style"]),
        int(params["z"]),
        int(params["x"]),
        int(params["y"]),
        extra,
    )
    return {IMAGE_NAME: image}


def _features(
    renderers: Sequence[Renderer], request: RenderRequest
) -> dict[str, bytes]:
    source, renderer, probe = _prepared(renderers, request)
    params = request.params
    features = _optional_method(renderer, "features")
    layer = params.get("layer")
    result = features(
        source,
        probe,
        None if layer is None else str(layer),
        _bbox(params["bbox"]),
        int(params["zoom"]),
        int(params["limit"]),
    )
    return {FEATURES_NAME: _json_bytes(result)}


def _members(renderers: Sequence[Renderer], request: RenderRequest) -> dict[str, bytes]:
    source = _source(request)
    members = _optional_method(renderer_for(renderers, source), "members")
    return {MEMBERS_NAME: _json_bytes(members(source))}


def _build(renderers: Sequence[Renderer], request: RenderRequest) -> dict[str, bytes]:
    """Build what the ``preview`` job keeps for a file (its local COG).

    ``params``: ``out`` (where to write it), ``force`` (past the auto-build
    limits) and optionally ``probe``. Answers the probe; nothing is written
    for a file that needs no build.
    """
    source, renderer, probe = _prepared(renderers, request)
    params = request.params
    if build_product(probe) is not None:
        if not params.get("force") and not auto_build(source, probe):
            raise PreviewUnavailableError("too_large", "past the auto-build limits")
        build = _optional_method(renderer, "build")
        build(source, probe, Path(str(params["out"])))
    return {INFO_NAME: probe.to_bytes()}


def _info_target(
    source: PreviewSource | None, params: JsonObject
) -> tuple[CacheKey, str] | None:
    return None if source is None else (cache_key(source), INFO_NAME)


def _thumbnail_target(
    source: PreviewSource | None, params: JsonObject
) -> tuple[CacheKey, str] | None:
    if source is None:
        return None
    frame = params.get("frame")
    layer = params.get("layer")
    # A vector's chosen layer joins the frame in the name's digest; a
    # thumbnail of no chosen layer keeps the name of the frame alone.
    variant = frame if layer is None else {"frame": frame, "layer": str(layer)}
    name = thumbnail_name(
        str(params["style"]),
        int(params["size"]),
        None if variant is None else _canonical(variant),
    )
    return cache_key(source), name


def _tile_target(
    source: PreviewSource | None, params: JsonObject
) -> tuple[CacheKey, str] | None:
    if source is None:
        return None
    extra = {
        name: value
        for name, value in params.items()
        if name not in ("style", "z", "x", "y", "probe")
    }
    name = tile_name(
        str(params["style"]),
        int(params["z"]),
        int(params["x"]),
        int(params["y"]),
        _canonical(extra) if extra else None,
    )
    return cache_key(source), name


# Operations of the render pool (decision 3; one line each).
OPERATIONS: Mapping[str, Operation] = {
    "probe": Operation(20.0, _probe, INFO_NAME, _info_target),
    "thumbnail": Operation(30.0, _thumbnail, IMAGE_NAME, _thumbnail_target),
    "tile": Operation(15.0, _tile, IMAGE_NAME, _tile_target),
    "features": Operation(15.0, _features, FEATURES_NAME),
    "members": Operation(10.0, _members, MEMBERS_NAME),
    LAYER_THUMBNAIL: Operation(
        60.0, layer_thumbnail, IMAGE_NAME, layer_thumbnail_target
    ),
    LAYER_TILE: Operation(15.0, layer_tile, IMAGE_NAME, layer_tile_target),
}
# The ``preview`` job's build of one file, in a process of its own with
# 10 minutes and 4 GiB (decision 3); never an operation of the pool.
BUILD = Operation(600.0, _build, INFO_NAME)


def _source(request: RenderRequest) -> PreviewSource:
    if request.source is None:
        raise PreviewUnavailableError(CODE_PROTOCOL_ERROR, "the request has no source")
    return request.source


def _prepared(
    renderers: Sequence[Renderer], request: RenderRequest
) -> tuple[PreviewSource, Renderer, PreviewProbe]:
    """Return the source, its renderer and its probe (given, else made).

    A probe with a reason is the renderer's to judge: a file without a map
    preview (``no_crs``) may still have a thumbnail.
    """
    source = _source(request)
    renderer = renderer_for(renderers, source)
    given = request.params.get("probe")
    probe = renderer.probe(source) if given is None else PreviewProbe.from_json(given)
    return source, renderer, probe


def _optional_method(renderer: Renderer, name: str) -> Callable[..., Any]:
    method = getattr(renderer, name, None)
    if not callable(method):
        raise PreviewUnavailableError(
            "unsupported_format", f"no {name} for {sorted(renderer.kinds)} files"
        )
    return cast(Callable[..., Any], method)


def require_unchanged(source: PreviewSource) -> None:
    """Refuse a working file whose state differs from its scan.

    Raises
    ------
    FileNotFoundError
        The file is gone.
    PreviewUnavailableError
        ``changed_since_scan``.
    """
    if not source.mutable or source.stat is None:
        return
    main = source.paths[0]
    found = _stat(main)
    if found is None:
        raise FileNotFoundError(main.name)
    wal = _stat(main.with_name(main.name + "-wal"))
    if found != source.stat.main or wal != source.stat.wal:
        raise PreviewUnavailableError("changed_since_scan")


def _stat(path: Path) -> FileStat | None:
    try:
        found = os.stat(path)
    except FileNotFoundError:
        return None
    return FileStat(found.st_size, found.st_mtime_ns)


def _bbox(value: Any) -> tuple[float, float, float, float]:
    numbers = tuple(float(number) for number in value)
    if len(numbers) != 4:
        raise ValueError("a bounding box has four numbers")
    return numbers


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _request_id(line: str) -> str:
    """Return the id of a malformed request, when it has one."""
    try:
        value = json.loads(line)
    except ValueError:
        return ""
    found = value.get("id") if isinstance(value, dict) else None
    return found if isinstance(found, str) else ""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archiwista.previews.worker")
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--previews-dir", type=Path, default=None)
    return parser


def _protocol_stream() -> IO[str]:
    """Keep standard output for the protocol; send all other output to stderr.

    Libraries (and C code) writing to file descriptor 1 then write to the
    discarded standard error instead of breaking the protocol.
    """
    sys.stdout.flush()
    descriptor = os.dup(1)
    os.dup2(2, 1)
    return os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    # Run in the imported module, not in ``__main__``: renderers import
    # ``archiwista.previews.worker`` (``work_dir``, ``cached_file``) and must
    # see the directories ``main`` sets.
    from archiwista.previews import worker

    sys.exit(worker.main())
