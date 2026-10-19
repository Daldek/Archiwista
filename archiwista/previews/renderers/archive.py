"""Renderer of ZIP archives: their members listed, never unpacked (plan v0.2).

An archive has no thumbnail and no map tiles (``archive_members_only``);
its preview is the list of its members with their sizes and formats.
``zipfile`` is never used: it reads the whole central directory into
memory first, whatever it declares. Instead (SPEC 10.1, decision 5):

1. the end of central directory record is found in the file's last 64 KiB,
   with its ZIP64 record when it has one; more than ``MAX_ENTRIES`` entries
   or a central directory larger than ``MAX_DIRECTORY_BYTES`` make the
   archive ``too_large`` before anything else is read;
2. then the central directory is read entry by entry, at most
   ``MAX_LISTED`` of them (``truncated`` beyond): name, size, compressed
   size, format by the name's extension. No member is decompressed or
   written, and member names are only listed (``../x`` is a name, never a
   path).
"""

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO

from archiwista.errors import PreviewUnavailableError
from archiwista.formats import file_format
from archiwista.previews.types import (
    Extent,
    JsonObject,
    PreviewKind,
    PreviewProbe,
    PreviewReason,
    PreviewSource,
)

# Limits of decision 5: past them the archive is not listed at all.
MAX_ENTRIES = 100_000
MAX_DIRECTORY_BYTES = 64 * 1024**2
# Members listed at most; the rest only counted (``total``).
MAX_LISTED = 10_000

_END = struct.Struct("<4sHHHHIIH")
_END_SIGNATURE = b"PK\x05\x06"
_END_SEARCH_BYTES = _END.size + 0xFFFF  # the record and the longest comment
_LOCATOR = struct.Struct("<4sIQI")
_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP64_END = struct.Struct("<4sQHHIIQQQQ")
_ZIP64_END_SIGNATURE = b"PK\x06\x06"
_ENTRY = struct.Struct("<4sHHHHHHIIIHHHHHII")
_ENTRY_SIGNATURE = b"PK\x01\x02"
_ZIP64_EXTRA = 0x0001
_UTF8_FLAG = 0x0800
_MAX_16 = 0xFFFF
_MAX_32 = 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class CentralDirectory:
    """Where an archive's central directory lies, from its end records.

    Parameters
    ----------
    entries : int
        Entries the archive declares.
    size_bytes : int
        Size of the central directory.
    offset : int
        Position of its first entry in the file (data prepended to the
        archive, as in a self-extracting one, already counted).
    """

    entries: int
    size_bytes: int
    offset: int


class ArchiveRenderer:
    """ZIP archives: the number of members, then the list of the first ones."""

    @property
    def kinds(self) -> frozenset[PreviewKind]:
        """Archives."""
        return frozenset({"archive"})

    def probe(self, source: PreviewSource) -> PreviewProbe:
        """Read the end records: the number of members, or ``too_large``.

        Raises
        ------
        ValueError
            Not a ZIP archive, or a damaged one (``unreadable``).
        """
        with source.paths[0].open("rb") as stream:
            directory = read_central_directory(stream)
        reason: PreviewReason = (
            "too_large" if _too_large(directory) else "archive_members_only"
        )
        return PreviewProbe(
            kind="archive", driver="ZIP", members=directory.entries, reason=reason
        )

    def members(self, source: PreviewSource) -> JsonObject:
        """List the first ``MAX_LISTED`` members, without unpacking any.

        Returns
        -------
        JsonObject
            ``total`` (entries declared), ``truncated`` (more than listed)
            and ``members``: ``name``, ``size_bytes``, ``compressed_bytes``,
            ``directory``, ``format`` and ``kind`` (format table, by the
            name's extension).

        Raises
        ------
        PreviewUnavailableError
            ``too_large``: past the limits of entries or directory size.
        ValueError
            Not a ZIP archive, or a damaged one (``unreadable``).
        """
        with source.paths[0].open("rb") as stream:
            directory = read_central_directory(stream)
            if _too_large(directory):
                raise PreviewUnavailableError(
                    "too_large",
                    f"{directory.entries} entries, central directory of"
                    f" {directory.size_bytes} bytes",
                )
            listed = list(_entries(stream, directory, MAX_LISTED))
        return {
            "total": directory.entries,
            "truncated": directory.entries > len(listed),
            "members": listed,
        }

    def thumbnail(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        size: int,
        frame: Extent | None,
    ) -> bytes:
        """Refuse: an archive has no thumbnail, only its list of members.

        Raises
        ------
        PreviewUnavailableError
            Always, with the probe's reason.
        """
        raise PreviewUnavailableError(probe.reason or "archive_members_only")

    def tile(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        z: int,
        x: int,
        y: int,
        params: JsonObject,
    ) -> bytes:
        """Refuse: an archive has no map tiles.

        Raises
        ------
        PreviewUnavailableError
            Always, with the probe's reason.
        """
        raise PreviewUnavailableError(probe.reason or "archive_members_only")


def read_central_directory(stream: BinaryIO) -> CentralDirectory:
    """Read the end of central directory record, and its ZIP64 one if any.

    Only the file's last ``_END_SEARCH_BYTES`` and, for ZIP64, the
    56-byte record they point to are read.

    Raises
    ------
    ValueError
        No end record, or records pointing outside the file.
    """
    file_size = stream.seek(0, 2)
    start = max(0, file_size - _END_SEARCH_BYTES)
    stream.seek(start)
    tail = stream.read()
    position = tail.rfind(_END_SIGNATURE)
    while position >= 0 and position + _END.size > len(tail):
        position = tail.rfind(_END_SIGNATURE, 0, position)
    if position < 0:
        raise ValueError("not a ZIP archive: no end of central directory record")
    end_at = start + position
    (_, disk, _, _, entries, size, offset, _) = _END.unpack_from(tail, position)
    if disk != 0:
        raise ValueError("a multi-volume ZIP archive")
    directory_end = end_at
    zip64 = entries == _MAX_16 or size == _MAX_32 or offset == _MAX_32
    locator_at = position - _LOCATOR.size
    if locator_at >= 0 and tail[locator_at : locator_at + 4] == _LOCATOR_SIGNATURE:
        zip64 = True
    if zip64:
        entries, size, offset, directory_end = _zip64_end(
            stream, tail, start, position, file_size
        )
    if size > directory_end:
        raise ValueError("central directory larger than the archive")
    # Bytes prepended to the archive shift every offset by the same amount.
    shift = directory_end - size - offset
    if shift < 0:
        raise ValueError("central directory outside the archive")
    return CentralDirectory(entries=entries, size_bytes=size, offset=offset + shift)


def _zip64_end(
    stream: BinaryIO, tail: bytes, start: int, position: int, file_size: int
) -> tuple[int, int, int, int]:
    """Return entries, size, offset and position of the ZIP64 end record."""
    locator_at = position - _LOCATOR.size
    if locator_at < 0 or tail[locator_at : locator_at + 4] != _LOCATOR_SIGNATURE:
        raise ValueError("ZIP64 archive without its end record locator")
    (_, disk, record_at, _) = _LOCATOR.unpack_from(tail, locator_at)
    if disk != 0:
        raise ValueError("a multi-volume ZIP archive")
    # The record lies right before its locator; ``record_at`` is where the
    # archive says it is, which prepended bytes shift.
    expected_at = start + locator_at - _ZIP64_END.size
    if expected_at < 0 or record_at > file_size:
        raise ValueError("ZIP64 end record outside the archive")
    stream.seek(expected_at)
    record = stream.read(_ZIP64_END.size)
    if len(record) != _ZIP64_END.size or record[:4] != _ZIP64_END_SIGNATURE:
        raise ValueError("damaged ZIP64 end of central directory record")
    (_, _, _, _, disk_number, _, _, entries, size, offset) = _ZIP64_END.unpack(record)
    if disk_number != 0:
        raise ValueError("a multi-volume ZIP archive")
    return entries, size, offset, expected_at


def _too_large(directory: CentralDirectory) -> bool:
    return directory.entries > MAX_ENTRIES or directory.size_bytes > MAX_DIRECTORY_BYTES


def _entries(
    stream: BinaryIO, directory: CentralDirectory, limit: int
) -> Iterator[JsonObject]:
    """Read up to ``limit`` entries of the central directory, in order."""
    stream.seek(directory.offset)
    remaining = directory.size_bytes
    for _ in range(min(limit, directory.entries)):
        header = stream.read(_ENTRY.size)
        if len(header) != _ENTRY.size or header[:4] != _ENTRY_SIGNATURE:
            raise ValueError("damaged central directory entry")
        fields = _ENTRY.unpack(header)
        flags, compressed, size = fields[3], fields[8], fields[9]
        name_len, extra_len, comment_len = fields[10], fields[11], fields[12]
        variable = name_len + extra_len + comment_len
        remaining -= _ENTRY.size + variable
        if remaining < 0:
            raise ValueError("central directory entry past its declared size")
        raw = stream.read(variable)
        if len(raw) != variable:
            raise ValueError("truncated central directory entry")
        name = raw[:name_len].decode("utf-8" if flags & _UTF8_FLAG else "cp437")
        size, compressed = _zip64_sizes(
            raw[name_len : name_len + extra_len], size, compressed
        )
        found = file_format(PurePosixPath(name.rstrip("/")).name or name)
        yield {
            "name": name,
            "size_bytes": size,
            "compressed_bytes": compressed,
            "directory": name.endswith("/"),
            "format": found.name,
            "kind": found.kind,
        }


def _zip64_sizes(extra: bytes, size: int, compressed: int) -> tuple[int, int]:
    """Replace the sizes a ZIP64 extra field carries (``0xFFFFFFFF`` ones)."""
    position = 0
    while position + 4 <= len(extra):
        tag, length = struct.unpack_from("<HH", extra, position)
        body = extra[position + 4 : position + 4 + length]
        position += 4 + length
        if tag != _ZIP64_EXTRA:
            continue
        values = [
            struct.unpack_from("<Q", body, offset)[0]
            for offset in range(0, len(body) - 7, 8)
        ]
        if size == _MAX_32 and values:
            size = values.pop(0)
        if compressed == _MAX_32 and values:
            compressed = values.pop(0)
        break
    return size, compressed
