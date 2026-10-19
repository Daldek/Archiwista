"""Models of the metadata comparison (plan v0.2, steps 9-10; decision 10, level 1).

``Comparison`` answers ``GET /compare?a=<ref>&b=<ref>`` and ``archiwista
compare REF REF``: both sides (reference, kind, title, the address of their
preview and their outline), whether their content is the same, rows of one
field each with the human name of the field and the values of A and B,
marked when they differ, and for two sides with vector layers the
differences of their layers and fields (``schema_diff``). The interface
exports the rows as CSV itself; the server writes nothing.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.models import Geometry
from archiwista.messages import MESSAGES

type CompareValue = str | int | float | bool | datetime | date | None
# ``metadata``: normalized fields of a store version in the index;
# ``sidecar``: the raw sidecar's fields as flattened JSON paths, uninterpreted
# (A-ADR-014); ``own``: fields of an own file or a snapshot; ``layers``:
# objects per vector layer of an own file or a snapshot, by layer name.
type RowGroup = Literal["metadata", "sidecar", "own", "layers"]
type RefKind = Literal["version", "file", "snapshot"]

_A = (
    "version:zespol:nmt/pl_1992_1m_evrf2007/versions/N-34/130/D/d/2/4/"
    "2019-07-12_41022_0b7d6a1c/N-34-130-D-d-2-4.asc"
)
_B = (
    "version:zespol:nmt/pl_1992_1m_evrf2007/versions/N-34/130/D/d/2/4/"
    "2025-04-26_82710_fdd30535/N-34-130-D-d-2-4.asc"
)
_EXAMPLE: dict[str, Any] = {
    "a": {
        "ref": _A,
        "kind": "version",
        "title": "N-34-130-D-d-2-4.asc — 2019-07-12_41022",
        "preview": (
            "/api/v1/stores/zespol/versions/nmt/pl_1992_1m_evrf2007/versions/N-34/"
            "130/D/d/2/4/2019-07-12_41022_0b7d6a1c/N-34-130-D-d-2-4.asc/preview"
        ),
        "outline": None,
    },
    "b": {
        "ref": _B,
        "kind": "version",
        "title": "N-34-130-D-d-2-4.asc — 2025-04-26_82710",
        "preview": (
            "/api/v1/stores/zespol/versions/nmt/pl_1992_1m_evrf2007/versions/N-34/"
            "130/D/d/2/4/2025-04-26_82710_fdd30535/N-34-130-D-d-2-4.asc/preview"
        ),
        "outline": None,
    },
    "same_content": False,
    "rows": [
        {
            "group": "metadata",
            "field": "data_date",
            "label": MESSAGES["compare_field_data_date"],
            "a": "2019-07-12",
            "b": "2025-04-26",
            "differs": True,
        },
        {
            "group": "sidecar",
            "field": "request.campaign",
            "label": "request.campaign",
            "a": "41022",
            "b": "82710",
            "differs": True,
        },
    ],
    "schema_diff": None,
}


class CompareQuery(BaseModel):
    """The two objects of `GET /compare`, each a `ref` copied from an answer."""

    model_config = ConfigDict(extra="forbid")

    a: str = Field(description="Reference of side A (`ref` of an answer).")
    b: str = Field(description="Reference of side B (`ref` of an answer).")


class ComparisonSide(BaseModel):
    """One compared object."""

    ref: str = Field(description="Reference of the object.")
    kind: RefKind = Field(description="`version`, `file` or `snapshot`.")
    title: str = Field(description="Name of the object for people.")
    preview: str | None = Field(
        description="Address of the object's preview description (`…/preview`)."
    )
    outline: Geometry | None = Field(description="Outline: GeoJSON in WGS84.")


class ComparisonRow(BaseModel):
    """One field of both objects."""

    group: RowGroup = Field(
        description=(
            "`metadata`: a normalized field of a store version; `sidecar`: a"
            " field of the raw sidecar, named by its JSON path; `own`: a field"
            " of an own file or a snapshot; `layers`: objects of a vector layer"
            " (`field` is the layer name)."
        )
    )
    field: str = Field(
        description=(
            "Field id (a JSON path in the `sidecar` group, a layer name in `layers`)."
        )
    )
    label: str = Field(description="Human name of the field.")
    a: CompareValue = Field(description="Value of A; null when A has none.")
    b: CompareValue = Field(description="Value of B; null when B has none.")
    differs: bool = Field(description="Whether the values of A and B differ.")


class SchemaField(BaseModel):
    """A field of a vector layer with its OGR type."""

    name: str = Field(description="Field name.")
    type: str = Field(description="OGR type (`String`, `Integer`, `Real`…).")


class FieldTypeChange(BaseModel):
    """A field of both layers whose type differs."""

    name: str = Field(description="Field name.")
    type_a: str = Field(description="Its type in A.")
    type_b: str = Field(description="Its type in B.")


class LayerDiff(BaseModel):
    """A vector layer of both sides: object counts and field differences."""

    name: str = Field(description="Layer name.")
    feature_count_a: int | None = Field(
        description="Objects of the layer in A; null when unknown."
    )
    feature_count_b: int | None = Field(
        description="Objects of the layer in B; null when unknown."
    )
    fields_added: list[SchemaField] = Field(
        description="Fields only B has, in B's order."
    )
    fields_removed: list[SchemaField] = Field(
        description="Fields only A has, in A's order."
    )
    fields_changed: list[FieldTypeChange] = Field(
        description="Fields of both with another type, in A's order."
    )


class SchemaDiff(BaseModel):
    """Differences of the vector layers of two sides (A changed into B)."""

    layers_only_a: list[str] = Field(description="Layers only A has, in A's order.")
    layers_only_b: list[str] = Field(description="Layers only B has, in B's order.")
    layers: list[LayerDiff] = Field(
        description="Layers of both sides, in A's order, also when unchanged."
    )


class Comparison(BaseModel):
    """Metadata of two objects side by side (level 1 of the comparison)."""

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE]})

    a: ComparisonSide
    b: ComparisonSide
    same_content: bool = Field(
        description=(
            "Whether both are known to hold the same content: equal content"
            " identities (method and SHA-256; a store version's `sha256` counts"
            " as the method `bytes`)."
        )
    )
    rows: list[ComparisonRow] = Field(
        description=(
            "A store version's index fields, then its raw sidecar's flattened"
            " fields; an own file's or a snapshot's fields, then its objects per"
            " layer."
        )
    )
    schema_diff: SchemaDiff | None = Field(
        description=(
            "Differences of the vector layers and their fields when both sides"
            " have vector layers (own files and snapshots); null otherwise."
        )
    )
