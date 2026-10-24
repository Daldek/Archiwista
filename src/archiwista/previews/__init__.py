"""Previews of data files: cache, render pool, ``preview`` job (plan v0.2, decision 3).

The server never opens a data file: ``RenderPool`` hands operations
(``probe``, ``thumbnail``, ``tile``, ``features``, ``members``) to
long-lived render processes (``archiwista.previews.worker``, with the sandbox
of ``archiwista.sandbox``) and keeps their results in the ``PreviewCache``
under the file's content, so equal bytes are rendered once. The ``preview``
job (``archiwista.previews.build``) builds local COGs, each file in a
process of its own. Renderers (``archiwista.previews.renderers``) are loaded
by render processes only.
"""

from archiwista.previews.cache import (
    COG_NAME,
    INFO_NAME,
    RENDERER_VERSIONS,
    CacheKey,
    CacheUsage,
    PreviewCache,
    cache_key,
    composite_key,
    path_key,
)
from archiwista.previews.pool import (
    PoolStats,
    RenderPool,
    RenderResult,
    default_render_workers,
)
from archiwista.previews.types import (
    PREVIEW_KINDS,
    PREVIEW_REASONS,
    PREVIEW_STATES,
    STYLE_NAMES,
    Extent,
    PreviewKind,
    PreviewProbe,
    PreviewReason,
    PreviewSource,
    PreviewState,
    Renderer,
    StyleName,
)

__all__ = [
    "COG_NAME",
    "INFO_NAME",
    "PREVIEW_KINDS",
    "PREVIEW_REASONS",
    "PREVIEW_STATES",
    "RENDERER_VERSIONS",
    "STYLE_NAMES",
    "CacheKey",
    "CacheUsage",
    "Extent",
    "PoolStats",
    "PreviewCache",
    "PreviewKind",
    "PreviewProbe",
    "PreviewReason",
    "PreviewSource",
    "PreviewState",
    "RenderPool",
    "RenderResult",
    "Renderer",
    "StyleName",
    "cache_key",
    "composite_key",
    "default_render_workers",
    "path_key",
]
