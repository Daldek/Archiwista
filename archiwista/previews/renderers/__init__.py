"""Renderers of the previews, one module per family of files (plan v0.2, steps 5a1–5c).

Only render processes import this package (``archiwista.previews.worker``
loads it as it starts): renderers use GDAL, OGR and laspy, which the server
never loads. ``RENDERERS`` lists the renderers, one line per module; a
render process uses the first whose ``kinds`` include the file's kind
(``PreviewSource.kind``), and a file of a kind none handles has no preview
(``unsupported_format``). Tests start render processes with renderers of
their own (``archiwista.previews.worker.main(renderers=…)``).
"""

from archiwista.previews.renderers.archive import ArchiveRenderer
from archiwista.previews.renderers.document import DocumentRenderer
from archiwista.previews.renderers.points import PointsRenderer
from archiwista.previews.types import Renderer

RENDERERS: tuple[Renderer, ...] = (
    PointsRenderer(),
    ArchiveRenderer(),
    DocumentRenderer(),
)
