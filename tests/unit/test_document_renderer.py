"""Documents, auxiliary and unknown files: a reason, never an image (decision 5)."""

from pathlib import Path

import pytest

from archiwista.errors import PreviewUnavailableError
from archiwista.messages import MESSAGES
from archiwista.previews.renderers.document import DocumentRenderer
from archiwista.previews.types import PreviewSource
from tests.fixtures.store_files import pdf_document, world_file

_KEY = "d" * 64
_BOUNDS = (500_000.0, 300_000.0, 500_640.0, 300_640.0)


def _source(path: Path) -> PreviewSource:
    return PreviewSource(f"file:p:{path.name}", _KEY, (path,))


@pytest.mark.parametrize(
    ("name", "content", "reason", "driver"),
    [
        ("mapa.pdf", pdf_document("Mapa"), "document_no_preview", "PDF"),
        ("opis.txt", b"Opis arkusza\n", "document_no_preview", "TXT"),
        ("arkusz.jgw", world_file(_BOUNDS), "auxiliary_file", "world file"),
        ("arkusz.tfw", world_file(_BOUNDS), "auxiliary_file", "world file"),
        ("dzialki.prj", b'PROJCS["ETRF2000-PL / CS92"]', "auxiliary_file", None),
        ("skan.tif.aux.xml", b"<PAMDataset/>", "auxiliary_file", None),
        ("dane.dwg", b"AC1032\x00\x00", "unsupported_format", None),
    ],
)
def test_document_probe_gives_reason_with_polish_text(
    tmp_path: Path, name: str, content: bytes, reason: str, driver: str | None
) -> None:
    """Each file gets its reason, which has a Polish description and fix."""
    # Arrange
    path = tmp_path / name
    path.write_bytes(content)
    renderer = DocumentRenderer()

    # Act
    probe = renderer.probe(_source(path))
    with pytest.raises(PreviewUnavailableError) as thumbnail:
        renderer.thumbnail(_source(path), probe, "rgb", 256, None)
    with pytest.raises(PreviewUnavailableError) as tile:
        renderer.tile(_source(path), probe, "rgb", 10, 1, 1, {})

    # Assert
    assert (probe.reason, probe.driver) == (reason, driver)
    assert thumbnail.value.reason == tile.value.reason == reason
    assert MESSAGES[f"preview_reason_{reason}"]
    assert MESSAGES[f"preview_fix_{reason}"]


def test_document_pdf_without_signature_has_no_driver(tmp_path: Path) -> None:
    """A ``.pdf`` that is no PDF still has no preview, and is not called PDF."""
    path = tmp_path / "mapa.pdf"
    path.write_bytes(b"<html>nie PDF</html>")

    probe = DocumentRenderer().probe(_source(path))

    assert (probe.reason, probe.driver) == ("document_no_preview", None)


def test_document_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    """A file gone since the scan is ``missing_file`` (the worker's mapping)."""
    with pytest.raises(FileNotFoundError):
        DocumentRenderer().probe(_source(tmp_path / "brak.pdf"))
