"""JSON Lines between the render pool and its render processes (decision 3).

A render process (``RENDER_WORKER_COMMAND``, started with the sandbox of
``archiwista.sandbox``) reads requests on its standard input, one JSON
object per line::

    {"id": "…", "op": "tile", "source": {…} | null, "params": {…}}

and answers each, in order, with one line on its standard output::

    {"id": "…", "status": "ok", "files": {"image.png": "<base64>"}}
    {"id": "…", "status": "error", "code": "unreadable", "detail": "…" | null}

``source`` is a ``PreviewSource`` (``null`` for operations whose parameters
carry their sources); ``files`` are the results in memory (a PNG,
``info.json``, JSON of features); ``code`` is a reason (``PreviewReason``)
or ``protocol_error``. ``detail`` is the library's message after
``scrub_paths``: no path of the source, its real path or any of their
directories leaves the process, only file names.
"""

import base64
import binascii
import json
import os
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archiwista.previews.types import JsonObject, PreviewSource

# ``-P``: the working directory is not on ``sys.path``.
RENDER_WORKER_COMMAND: tuple[str, ...] = (
    sys.executable,
    "-P",
    "-m",
    "archiwista.previews.worker",
)
CODE_PROTOCOL_ERROR = "protocol_error"
# Longest detail an answer carries; libraries may repeat themselves.
MAX_DETAIL_CHARS = 2000


class RenderProtocolError(ValueError):
    """A line is not a valid render request or answer."""


@dataclass(frozen=True, slots=True)
class RenderRequest:
    """One operation for a render process.

    Attributes
    ----------
    id : str
        Chosen by the sender; the answer repeats it.
    op : str
        Operation (``archiwista.previews.worker.OPERATIONS`` or ``build``).
    source : PreviewSource or None
        The file to read.
    params : dict
        Parameters of the operation (JSON).
    """

    id: str
    op: str
    source: PreviewSource | None
    params: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RenderAnswer:
    """The answer to one request: ``files``, or an error ``code``."""

    id: str
    files: Mapping[str, bytes] = field(default_factory=dict)
    code: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the operation succeeded."""
        return self.code is None


def encode_request(request: RenderRequest) -> str:
    """Return a request as one JSON line, without the line end."""
    return _dump(
        {
            "id": request.id,
            "op": request.op,
            "source": None if request.source is None else request.source.to_json(),
            "params": request.params,
        }
    )


def decode_request(line: str) -> RenderRequest:
    """Read one request line.

    Raises
    ------
    RenderProtocolError
        Not JSON, or not a request.
    """
    value = _load(line)
    try:
        params = value.get("params", {})
        if not isinstance(params, dict):
            raise TypeError("params is not an object")
        source = value.get("source")
        return RenderRequest(
            id=_text(value["id"]),
            op=_text(value["op"]),
            source=None if source is None else PreviewSource.from_json(source),
            params=params,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RenderProtocolError(f"invalid render request: {error}") from error


def encode_answer(answer: RenderAnswer) -> str:
    """Return an answer as one JSON line, without the line end."""
    if answer.ok:
        files = {
            name: base64.b64encode(data).decode("ascii")
            for name, data in answer.files.items()
        }
        return _dump({"id": answer.id, "status": "ok", "files": files})
    return _dump(
        {
            "id": answer.id,
            "status": "error",
            "code": answer.code,
            "detail": answer.detail,
        }
    )


def decode_answer(line: str) -> RenderAnswer:
    """Read one answer line.

    Raises
    ------
    RenderProtocolError
        Not JSON, or not an answer.
    """
    value = _load(line)
    try:
        answer_id = _text(value["id"])
        status = value["status"]
        if status == "ok":
            files = value["files"]
            if not isinstance(files, dict):
                raise TypeError("files is not an object")
            return RenderAnswer(
                answer_id,
                files={
                    _text(name): base64.b64decode(_text(data), validate=True)
                    for name, data in files.items()
                },
            )
        if status == "error":
            detail = value.get("detail")
            return RenderAnswer(
                answer_id,
                code=_text(value["code"]),
                detail=None if detail is None else _text(detail),
            )
        raise ValueError(f"unknown status {status!r}")
    except (KeyError, TypeError, ValueError, binascii.Error) as error:
        raise RenderProtocolError(f"invalid render answer: {error}") from error


def scrub_paths(
    text: str, paths: Iterable[Path], *, directories: Iterable[Path] = ()
) -> str:
    """Replace the paths of a source and their directories by file names.

    Every path, also after ``realpath``, becomes its file name; a path in
    one of their directories (a sibling ``.aux.xml``, a set member) keeps
    only its name below that directory, and a directory alone becomes its
    own name. ``directories`` (e.g. the process's work directory) are
    treated the same way. The result names no absolute path of these, so a
    library message about ``/home/ola/projekty/…`` reaches nobody who shares
    only the bytes (decision 3).

    Parameters
    ----------
    text : str
        A library's message.
    paths : Iterable[Path]
        Absolute paths of the source.
    directories : Iterable[Path], optional
        More directories to hide.

    Returns
    -------
    str
        The message, at most ``MAX_DETAIL_CHARS`` long.
    """
    replacements: dict[str, str] = {}
    folders: set[Path] = set()
    for path in paths:
        for variant in (path, Path(os.path.realpath(path))):
            replacements[str(variant)] = variant.name
            folders.update(variant.parents)
    for directory in directories:
        folders.update((directory, Path(os.path.realpath(directory))))
    for folder in folders:
        if folder.parent == folder:  # the root itself names nothing
            continue
        replacements.setdefault(str(folder), folder.name)
        replacements.setdefault(str(folder) + os.sep, "")
        replacements.setdefault(folder.as_posix() + "/", "")
    if replacements:
        # Longest first, in one pass: a replacement is never searched again.
        needles = sorted(replacements, key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(needle) for needle in needles))
        text = pattern.sub(lambda match: replacements[match.group(0)], text)
    return text[:MAX_DETAIL_CHARS]


def _dump(value: JsonObject) -> str:
    # JSON escapes control characters, so a value never breaks the line.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(line: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except ValueError as error:
        raise RenderProtocolError(f"not JSON: {line.strip()[:200]!r}") from error
    if not isinstance(value, dict):
        raise RenderProtocolError(f"not a JSON object: {line.strip()[:200]!r}")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{value!r} is not text")
    return value
