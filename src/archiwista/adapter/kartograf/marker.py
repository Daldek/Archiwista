"""Judge the marker of a Kartograf store by file name and schema.

The root of a Kartograf store holds ``kartograf-store.json``, schema
``kartograf-store/1`` (DEV-19.12): the first write into a new root creates it,
and ``kartograf store init`` marks an existing store after verifying its
layout. A tool tells the store of another tool by the file name of its marker
and imports nothing of it, and a root that has the layout but no marker is
unusable until ``store init`` has run (DEV-19.13, ADR-031). Kartograf's public
API has no function that tells a marked, an unmarked and a foreign directory
apart, so the adapter judges them here, and
``tests/contract/test_kartograf_marker.py`` holds the judgement to Kartograf's
own writers (``kartograf.testing``, ``kartograf.init_store``) so that it
cannot drift. Nothing of ``kartograf`` is imported here.
"""

import json
import os
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from archiwista.messages import Message, message

MARKER = "kartograf-store.json"
MARKER_SCHEMA = "kartograf-store/1"
# Markers of the stores of the other Nogat tools by file name (DEV-19.12), with
# the name of the tool as a person reads it.
OTHER_MARKERS = {"imgw-store.json": "IMGW"}
# The staging directory of a version: what is being written is no layout yet.
STAGING_DIR = ".incoming"
# A schema is cut in a message: it comes from a file that is not ours.
_SHOWN_SCHEMA = 80


class Refusal(NamedTuple):
    """Why a directory is not a Kartograf store Archiwista reads.

    Attributes
    ----------
    reason : str
        Machine code: ``foreign_store``, ``unsupported_marker``,
        ``not_a_store`` or ``no_marker``.
    detail : Message
        What is wrong, a catalog message.
    hint : Message or None
        One line that tells how to fix it, when there is a command to run.
    """

    reason: str
    detail: Message
    hint: Message | None = None


def refusal(
    root: Path, segments: Sequence[str], known: Sequence[str]
) -> Refusal | None:
    """Return why ``root`` is not a store to read, ``None`` when it is.

    A marker decides: the marker of another tool makes the directory foreign,
    the Kartograf marker of the schema this adapter reads makes it a store, any
    other one is unsupported. Without a marker the segments decide: none is an
    empty directory, a new store whose first write creates the marker; none
    known to Kartograf is the parent of a store or something else; known ones
    with a file below them are a store without its marker; known ones without
    any file are no layout yet.

    Parameters
    ----------
    root : Path
        The configured directory.
    segments : sequence of str
        Its segments (``list_segments``), unknown ones included.
    known : sequence of str
        The segments that Kartograf recognises.

    Returns
    -------
    Refusal or None
        The reason, text and fix; ``None`` for a directory to read.

    Raises
    ------
    OSError
        A marker or a directory below the segments cannot be read.
    """
    for name, tool in OTHER_MARKERS.items():
        if (root / name).is_file():
            detail = message("source.foreign_store", marker=name, tool=tool)
            return Refusal("foreign_store", detail)
    marker = root / MARKER
    if marker.is_file():
        return _judge_marker(marker)
    if not segments:
        return None
    if not known:
        detail = message("source.kartograf_not_store", marker=MARKER)
        return Refusal("not_a_store", detail)
    if _holds_files(root, known):
        detail = message("source.no_marker", marker=MARKER)
        hint = message("fix.store_init", path=shlex.quote(str(root)))
        return Refusal("no_marker", detail, hint)
    return None


def _judge_marker(marker: Path) -> Refusal | None:
    """Return the refusal of a marker that is not ``kartograf-store/1``."""
    try:
        document = json.loads(marker.read_text(encoding="utf-8"))
    except ValueError:  # not JSON, or not UTF-8
        document = None
    if not isinstance(document, dict) or "schema" not in document:
        detail = message(
            "source.invalid_marker", marker=MARKER, supported=MARKER_SCHEMA
        )
        return Refusal("unsupported_marker", detail)
    if document["schema"] == MARKER_SCHEMA:
        return None
    detail = message(
        "source.unsupported_marker",
        marker=MARKER,
        found=str(document["schema"])[:_SHOWN_SCHEMA],
        supported=MARKER_SCHEMA,
    )
    return Refusal("unsupported_marker", detail)


def _holds_files(root: Path, segments: Sequence[str]) -> bool:
    """Say whether a file lies below a segment; staging directories do not count."""
    for segment in segments:
        for _, dirs, files in os.walk(root / segment):
            if files:
                return True
            dirs[:] = [name for name in dirs if name != STAGING_DIR]
    return False
