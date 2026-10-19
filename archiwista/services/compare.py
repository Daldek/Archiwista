"""Metadata of two objects side by side (plan v0.2, decision 10, level 1).

``compare`` answers ``GET /compare?a=<ref>&b=<ref>`` and ``archiwista
compare REF REF`` from the local index alone: no data file is opened. For a
store version the rows are first its normalized index fields (data and
download dates, label, campaign, survey work number, edition, full sheet and
coverage, resolution, coordinate systems, ``nodata``, ``sha256``, size,
licence and attribution), then every field of its raw sidecar as a
flattened JSON path (``request.campaign``, ``source_files[0]``), named by
that path and not interpreted: Archiwista does not know the producer's
fields (A-ADR-014). Two versions of one slot or of two slots compare alike.

Own-data sides (``file:`` and ``snapshot:``: feature counts per layer,
extent, schema with ``schema_diff``, coordinate system, size, content
identity, author, note, dates) come with step 9, in ``_compared``; until
then they are refused like an unknown kind (``422 invalid_ref``).
"""

import json
import math
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, cast

from archiwista.api.models_compare import (
    CompareValue,
    Comparison,
    ComparisonRow,
    ComparisonSide,
    RowGroup,
)
from archiwista.auth import ProjectVisibility
from archiwista.errors import InvalidRefError, NotFoundError
from archiwista.index import IndexQueries
from archiwista.messages import MESSAGES
from archiwista.previews.service import object_url
from archiwista.previews.types import CONTENT_KEY
from archiwista.refs import ObjectRef, VersionRef, format_ref, parse_ref

# Normalized fields of a store version, in the order of the rows; each has
# its name ``compare_field_<field>``.
VERSION_FIELDS = (
    "data_date",
    "data_year",
    "downloaded_at",
    "label",
    "campaign",
    "survey_work_id",
    "edition",
    "full_sheet",
    "coverage",
    "resolution",
    "horizontal_crs",
    "vertical_crs",
    "nodata",
    "sha256",
    "size_bytes",
    "license",
    "attribution",
)


@dataclass(frozen=True, slots=True)
class _Compared:
    """One side: what is shown of it and the values of its rows."""

    side: ComparisonSide
    content: str | None
    """Identity of its content (``sha256``), ``None`` when unknown."""
    metadata: dict[str, CompareValue]
    sidecar: dict[str, CompareValue]


def compare(
    queries: IndexQueries, a: str, b: str, *, visible: ProjectVisibility
) -> Comparison:
    """Return the metadata of two objects side by side.

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index.
    a, b : str
        References of both sides (``ref`` of an answer); pairs of kinds
        mix freely, e.g. versions of two slots.
    visible : ProjectVisibility
        The projects the principal sees (own data, from step 9); store
        versions are visible to everyone.

    Returns
    -------
    Comparison
        Both sides, ``same_content`` and the rows: index fields first,
        then the raw sidecars' fields.

    Raises
    ------
    InvalidRefError
        Not a reference, or one of a kind not compared yet
        (``422 invalid_ref``).
    NotFoundError
        The index does not know an object (``404``).
    """
    left = _compared(queries, parse_ref(a), visible)
    right = _compared(queries, parse_ref(b), visible)
    rows = [
        *_rows("metadata", left.metadata, right.metadata),
        *_rows("sidecar", left.sidecar, right.sidecar),
    ]
    same = left.content is not None and left.content == right.content
    return Comparison(
        a=left.side, b=right.side, same_content=same, rows=rows, schema_diff=None
    )


def _compared(
    queries: IndexQueries, ref: ObjectRef, visible: ProjectVisibility
) -> _Compared:
    """Return one side of a comparison (own-data kinds: step 9)."""
    if isinstance(ref, VersionRef):
        return _version(queries, ref, visible)
    message = MESSAGES["compare_kind_unsupported"].format(ref=format_ref(ref))
    raise InvalidRefError(message)


def _version(
    queries: IndexQueries, ref: VersionRef, visible: ProjectVisibility
) -> _Compared:
    detail = queries.version(ref.store, ref.path, visible=visible)
    if detail is None:
        message = MESSAGES["api_version_unknown"].format(
            version=ref.path, store=ref.store
        )
        raise NotFoundError(message)
    summary = detail.summary
    values: dict[str, Any] = {
        "data_date": summary.data_date,
        "data_year": summary.data_year,
        "downloaded_at": summary.downloaded_at,
        "label": summary.label,
        "campaign": detail.campaign,
        "survey_work_id": detail.survey_work_id,
        "edition": detail.edition,
        "full_sheet": summary.full_sheet,
        "coverage": detail.coverage,
        "resolution": detail.resolution,
        "horizontal_crs": summary.horizontal_crs,
        "vertical_crs": summary.vertical_crs,
        "nodata": detail.nodata,
        "sha256": summary.sha256,
        "size_bytes": summary.size_bytes,
        "license": detail.license,
        "attribution": detail.attribution,
    }
    sha256 = summary.sha256.lower() if summary.sha256 else None
    if sha256 is not None and CONTENT_KEY.fullmatch(sha256) is None:
        sha256 = None
    title = MESSAGES["compare_title_version"].format(
        name=PurePosixPath(detail.slot).name,
        label=summary.label or MESSAGES["compare_title_no_label"],
    )
    side = ComparisonSide(
        ref=format_ref(ref),
        kind="version",
        title=title,
        preview=f"{object_url(ref)}/preview",
        outline=detail.footprint,
    )
    sidecar: dict[str, CompareValue] = {}
    raw = queries.sidecar(ref.store, ref.path)
    if raw is not None:
        _flatten(raw, "", sidecar)
    return _Compared(
        side=side,
        content=sha256,
        metadata={field: values[field] for field in VERSION_FIELDS},
        sidecar=sidecar,
    )


def _flatten(value: object, path: str, into: dict[str, CompareValue]) -> None:
    """Put the leaves of a JSON value into ``into`` under their JSON paths.

    Objects add ``.key`` and arrays ``[index]``; an empty object or array is
    a leaf holding its JSON text.
    """
    if isinstance(value, dict) and value:
        for key, item in value.items():
            _flatten(item, f"{path}.{key}" if path else str(key), into)
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            _flatten(item, f"{path}[{index}]", into)
    elif isinstance(value, dict | list):
        into[path] = json.dumps(value)
    else:
        into[path] = cast(CompareValue, value)


def _rows(
    group: RowGroup, a: dict[str, CompareValue], b: dict[str, CompareValue]
) -> list[ComparisonRow]:
    """Return the rows of a group: A's fields in order, then those only in B."""
    fields = [*a, *(field for field in b if field not in a)]
    return [
        ComparisonRow(
            group=group,
            field=field,
            label=_label(group, field),
            a=a.get(field),
            b=b.get(field),
            differs=_differs(a.get(field), b.get(field)),
        )
        for field in fields
    ]


def _label(group: RowGroup, field: str) -> str:
    if group == "sidecar":
        return field
    return MESSAGES[f"compare_field_{field}"]


def _differs(a: CompareValue, b: CompareValue) -> bool:
    """Whether two values differ, also in type (``1`` is not ``true``)."""
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a):
        return not math.isnan(b)
    return type(a) is not type(b) or a != b
