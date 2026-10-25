"""Renderer of documents, auxiliary files and unknown files (plan v0.2, decision 5).

None of these has a thumbnail or map tiles: the probe only confirms the file
can be read and gives the reason, which the interface shows with its
description and fix (``preview_reason_<code>``, ``preview_fix_<code>``):

- a document (PDF, TXT) → ``document_no_preview``: showing a PDF in the
  browser needs the files served (team mode, v0.4); the file card gives
  its path to copy;
- an auxiliary file (world files ``.jgw .tfw .pgw .wld``, ``.prj``,
  ``.aux.xml``) → ``auxiliary_file``: the preview is with the file it
  serves;
- any other file → ``unsupported_format``.

Only the first bytes of a file are read, never with GDAL.
"""

from archiwista.errors import PreviewUnavailableError
from archiwista.previews.types import (
    Extent,
    JsonObject,
    PreviewKind,
    PreviewProbe,
    PreviewReason,
    PreviewSource,
)

# Files that only serve another one, besides the world files of the format
# table: a CRS of a Shapefile or a raster, a GDAL sidecar of a raster.
AUXILIARY_SUFFIXES = (".prj", ".aux.xml")
# A PDF may carry up to 1 KiB of other bytes before its header.
PDF_HEADER_WINDOW_BYTES = 1024
PDF_SIGNATURE = b"%PDF-"


class DocumentRenderer:
    """Probe of documents, auxiliary and unknown files: a reason, no image."""

    @property
    def kinds(self) -> frozenset[PreviewKind]:
        """Documents, auxiliary files and files of no known format."""
        return frozenset({"document", "auxiliary", "unknown"})

    def probe(self, source: PreviewSource) -> PreviewProbe:
        """Read the file's first bytes and give the reason it has no preview.

        Raises
        ------
        FileNotFoundError
            The file is gone (``missing_file``).
        OSError
            The file cannot be read (``unreadable``).
        """
        main = source.paths[0]
        with main.open("rb") as stream:
            head = stream.read(PDF_HEADER_WINDOW_BYTES)
        reason = document_reason(source)
        driver = None if source.kind == "unknown" else source.format.name
        if source.format.name == "PDF" and PDF_SIGNATURE not in head:
            driver = None  # a ``.pdf`` that is no PDF: still no preview
        return PreviewProbe(kind=source.kind, driver=driver, reason=reason)

    def thumbnail(
        self,
        source: PreviewSource,
        probe: PreviewProbe,
        style: str,
        size: int,
        frame: Extent | None,
    ) -> bytes:
        """Refuse: such a file has no thumbnail.

        Raises
        ------
        PreviewUnavailableError
            Always, with the probe's reason.
        """
        raise PreviewUnavailableError(probe.reason or document_reason(source))

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
        """Refuse: such a file has no map tiles.

        Raises
        ------
        PreviewUnavailableError
            Always, with the probe's reason.
        """
        raise PreviewUnavailableError(probe.reason or document_reason(source))


def document_reason(source: PreviewSource) -> PreviewReason:
    """Return why a document, auxiliary or unknown file has no preview."""
    name = source.paths[0].name.lower()
    if source.kind == "auxiliary" or name.endswith(AUXILIARY_SUFFIXES):
        return "auxiliary_file"
    if source.kind == "document":
        return "document_no_preview"
    return "unsupported_format"
