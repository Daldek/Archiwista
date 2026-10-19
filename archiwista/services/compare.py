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

An own file (``file:``) and a snapshot (``snapshot:``, its ``migawka.json``
as the index read it) have the rows of ``OWN_FIELDS`` (format, object count,
coordinate system, extent, size, content identity, the snapshot's date,
author and note, the file's dates), then one row per vector layer with its
object count; two sides with vector layers also get ``schema_diff``. Any
pair of kinds compares (a snapshot with its working file, a file with a
version); rows a side does not have hold ``null``.
"""

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, cast

from pydantic import ValidationError

from archiwista.api.models_compare import (
    CompareValue,
    Comparison,
    ComparisonRow,
    ComparisonSide,
    FieldTypeChange,
    LayerDiff,
    RowGroup,
    SchemaDiff,
    SchemaField,
)
from archiwista.auth import ProjectVisibility
from archiwista.errors import NotFoundError
from archiwista.index import (
    IndexQueries,
    OwnFileDetail,
    SnapshotRecord,
    own_file_id,
)
from archiwista.index.geometry import box_geometry
from archiwista.messages import MESSAGES
from archiwista.owndata.document import SnapshotDocument
from archiwista.owndata.reader import FieldInfo, LayerInfo
from archiwista.previews.service import object_url
from archiwista.previews.types import CONTENT_KEY
from archiwista.refs import (
    FileRef,
    ObjectRef,
    SnapshotRef,
    VersionRef,
    format_ref,
    parse_ref,
)

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
# Fields of an own file or a snapshot, in the order of the rows; each has its
# name ``compare_field_<field>``. ``created_at``, ``author`` and ``note``
# belong to a snapshot, ``first_seen_at`` and ``changed_at`` to a working
# file; ``modified_at`` is the working file's modification time (of a
# snapshot: the working file's when it was copied). A snapshot's size is the
# bytes of its copy.
OWN_FIELDS = (
    "format",
    "feature_count",
    "crs",
    "extent",
    "size_bytes",
    "content_method",
    "content_sha256",
    "created_at",
    "author",
    "note",
    "modified_at",
    "first_seen_at",
    "changed_at",
)
# Groups of rows in the order they are listed.
_GROUPS: tuple[RowGroup, ...] = ("metadata", "sidecar", "own", "layers")
# A store version's ``sha256`` is the hash of its file's bytes.
_BYTES = "bytes"


@dataclass(frozen=True, slots=True)
class _Compared:
    """One side: what is shown of it, its content and the values of its rows."""

    side: ComparisonSide
    content: tuple[str, str] | None
    """Content identity (method, ``sha256``), ``None`` when unknown."""
    values: dict[RowGroup, dict[str, CompareValue]]
    layers: tuple[LayerInfo, ...] = ()
    """Vector layers (``schema_diff``); empty for a side without them."""


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
        mix freely, e.g. a snapshot with its working file.
    visible : ProjectVisibility
        The projects the principal sees (own data); store versions are
        visible to everyone.

    Returns
    -------
    Comparison
        Both sides, ``same_content``, the rows (a version's index fields,
        its raw sidecar's fields, an own object's fields, its objects per
        layer) and ``schema_diff`` when both sides have vector layers.

    Raises
    ------
    InvalidRefError
        Not a reference (``422 invalid_ref``).
    NotFoundError
        The index does not know an object, or its project is not visible
        (``404``).
    """
    left = _compared(queries, parse_ref(a), visible)
    right = _compared(queries, parse_ref(b), visible)
    rows = [
        row
        for group in _GROUPS
        for row in _rows(group, left.values.get(group, {}), right.values.get(group, {}))
    ]
    same = left.content is not None and left.content == right.content
    schema = (
        _schema_diff(left.layers, right.layers)
        if left.layers and right.layers
        else None
    )
    return Comparison(
        a=left.side, b=right.side, same_content=same, rows=rows, schema_diff=schema
    )


def _compared(
    queries: IndexQueries, ref: ObjectRef, visible: ProjectVisibility
) -> _Compared:
    """Return one side of a comparison by the kind of its reference."""
    match ref:
        case VersionRef():
            return _version(queries, ref, visible)
        case FileRef(project, path):
            return _working_file(_own_file(queries, project, path, visible), ref)
        case SnapshotRef(project, label, path):
            detail = _own_file(queries, project, path, visible)
            found = next(
                (item for item in detail.snapshots if item.label == label), None
            )
            if found is None:
                message = MESSAGES["compare_snapshot_not_found"].format(
                    project=project, path=path, label=label
                )
                raise NotFoundError(message)
            return _snapshot(detail, found, ref)


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
        content=None if sha256 is None else (_BYTES, sha256),
        values={
            "metadata": {name: values[name] for name in VERSION_FIELDS},
            "sidecar": sidecar,
        },
    )


def _own_file(
    queries: IndexQueries, project: str, path: str, visible: ProjectVisibility
) -> OwnFileDetail:
    """Return the card of an own file; a project not visible is not found."""
    detail = queries.own_file(project, own_file_id(path), visible=visible)
    if detail is not None:
        return detail
    if queries.project(project, visible=visible) is None:
        raise NotFoundError(MESSAGES["project_not_found"].format(project=project))
    message = MESSAGES["compare_file_not_found"].format(project=project, path=path)
    raise NotFoundError(message)


def _working_file(detail: OwnFileDetail, ref: FileRef) -> _Compared:
    """Return the side of a working file of a data folder."""
    row = detail.file
    values: dict[str, CompareValue] = {
        "format": row.driver,
        "feature_count": detail.feature_count,
        "crs": detail.native_crs,
        "extent": _extent(detail.native_bbox),
        "size_bytes": row.size_bytes,
        "content_method": detail.content_method,
        "content_sha256": detail.content_sha256,
        "created_at": None,
        "author": None,
        "note": None,
        "modified_at": row.modified_at,
        "first_seen_at": detail.first_seen_at,
        "changed_at": detail.changed_at,
    }
    return _own_side(
        ref,
        label=MESSAGES["compare_title_working"],
        outline=detail.wgs84,
        content=_identity(detail.content_method, detail.content_sha256),
        values=values,
        layers=detail.layers,
    )


def _snapshot(
    detail: OwnFileDetail, record: SnapshotRecord, ref: SnapshotRef
) -> _Compared:
    """Return the side of a snapshot: the index record and its ``migawka.json``.

    A document the index holds but that is not ``archiwista-snapshot/1``
    (an invalid snapshot) leaves its fields empty.
    """
    document = _document(record)
    extent = document.extent if document else None
    raster = document.raster if document else None
    crs = extent.crs if extent else raster.crs if raster else None
    author = document.author if document else None
    layers = tuple(
        LayerInfo(
            name=layer.name,
            geometry_type=layer.geometry_type,
            feature_count=layer.feature_count,
            fields=tuple(FieldInfo(item.name, item.type) for item in layer.fields),
            crs=layer.crs,
            bbox=None,
        )
        for layer in (document.layers or [] if document else [])
    )
    values: dict[str, CompareValue] = {
        "format": document.source.format if document else None,
        "feature_count": document.feature_count if document else None,
        "crs": crs,
        "extent": _extent(extent.bbox if extent else None),
        "size_bytes": record.size_bytes,
        "content_method": record.content_method,
        "content_sha256": record.content_sha256,
        "created_at": record.created_at,
        "author": (author.name or author.id) if author else None,
        "note": (document.note or None) if document else None,
        "modified_at": document.source.modified_at if document else None,
        "first_seen_at": None,
        "changed_at": None,
    }
    outline = detail.wgs84
    if extent is not None and extent.wgs84 is not None:
        outline = box_geometry(extent.wgs84)
    return _own_side(
        ref,
        label=record.label,
        outline=outline,
        content=_identity(record.content_method, record.content_sha256),
        values=values,
        layers=layers,
    )


def _document(record: SnapshotRecord) -> SnapshotDocument | None:
    """Return a snapshot's ``migawka.json`` as a document, ``None`` if invalid."""
    if record.document is None:
        return None
    try:
        return SnapshotDocument.model_validate(record.document)
    except ValidationError:
        return None


def _own_side(
    ref: FileRef | SnapshotRef,
    *,
    label: str,
    outline: dict[str, Any] | None,
    content: tuple[str, str] | None,
    values: dict[str, CompareValue],
    layers: tuple[LayerInfo, ...],
) -> _Compared:
    """Return the side of an own file or a snapshot with its rows."""
    side = ComparisonSide(
        ref=format_ref(ref),
        kind="file" if isinstance(ref, FileRef) else "snapshot",
        title=MESSAGES["compare_title_version"].format(
            name=PurePosixPath(ref.path).name, label=label
        ),
        preview=f"{object_url(ref)}/preview",
        outline=outline,
    )
    return _Compared(
        side=side,
        content=content,
        values={
            "own": {name: values[name] for name in OWN_FIELDS},
            "layers": {layer.name: layer.feature_count for layer in layers},
        },
        layers=layers,
    )


def _identity(method: str | None, sha256: str | None) -> tuple[str, str] | None:
    """Return a content identity, ``None`` when it is not known."""
    if method is None or sha256 is None:
        return None
    return method, sha256.lower()


def _extent(bbox: Iterable[float] | None) -> str | None:
    """Return an extent as ``min_x, min_y, max_x, max_y`` (``None``: none)."""
    if bbox is None:
        return None
    return ", ".join(str(value) for value in bbox)


def _schema_diff(a: tuple[LayerInfo, ...], b: tuple[LayerInfo, ...]) -> SchemaDiff:
    """Return the differences of the vector layers of A and B (A into B)."""
    names_a = {layer.name for layer in a}
    by_name_b = {layer.name: layer for layer in b}
    return SchemaDiff(
        layers_only_a=[layer.name for layer in a if layer.name not in by_name_b],
        layers_only_b=[layer.name for layer in b if layer.name not in names_a],
        layers=[
            _layer_diff(layer, by_name_b[layer.name])
            for layer in a
            if layer.name in by_name_b
        ],
    )


def _layer_diff(a: LayerInfo, b: LayerInfo) -> LayerDiff:
    """Return the object counts and field differences of one layer."""
    types_a = {item.name: item.type for item in a.fields}
    types_b = {item.name: item.type for item in b.fields}
    return LayerDiff(
        name=a.name,
        feature_count_a=a.feature_count,
        feature_count_b=b.feature_count,
        fields_added=[
            SchemaField(name=item.name, type=item.type)
            for item in b.fields
            if item.name not in types_a
        ],
        fields_removed=[
            SchemaField(name=item.name, type=item.type)
            for item in a.fields
            if item.name not in types_b
        ],
        fields_changed=[
            FieldTypeChange(name=item.name, type_a=item.type, type_b=types_b[item.name])
            for item in a.fields
            if item.name in types_b and types_b[item.name] != item.type
        ],
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
    if group == "layers":
        return MESSAGES["compare_layer_features"].format(layer=field)
    return MESSAGES[f"compare_field_{field}"]


def _differs(a: CompareValue, b: CompareValue) -> bool:
    """Whether two values differ, also in type (``1`` is not ``true``)."""
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a):
        return not math.isnan(b)
    return type(a) is not type(b) or a != b
