"""API models of a project's exports (A-ADR-049 decision 13, SPEC 8.4).

An export is the directory ``eksport/<name>/`` of a project, written from
its pins: a folder per category with copies of the pinned versions' files
and ``README.txt``, with ``zip`` also ``eksport/<name>.zip``. Its directory
appears as a copy path (``CopyPath``). The request model refuses unknown
members.
"""

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.models import CopyPath, Preferences
from archiwista.api.models_owndata import copy_path
from archiwista.config import AppSettings
from archiwista.projects import EXPORTS_DIR
from archiwista.projects.exports import (
    EXPORT_NAME_PATTERN,
    MAX_EXPORT_NAME_CHARS,
    README,
    ExportListing,
)
from archiwista.services.projects import ProjectExportDone

_PATH_EXAMPLE: dict[str, Any] = {
    "local": f"/mnt/nas/projekty/raba/{EXPORTS_DIR}/raba-2024",
    "aliases": [f"P:\\raba\\{EXPORTS_DIR}\\raba-2024"],
    "personal": None,
}
_EXPORT_EXAMPLE: dict[str, Any] = {
    "name": "raba-2024",
    "path": _PATH_EXAMPLE,
    "files": [
        "BDOT/1201_BDOT10k.gpkg",
        "NMT/M-34-63-D-c-3-4.asc",
        "NMT/M-34-63-D-c-3-4.prj",
        "ORTO/76040_1110238_M-34-63-D-c-3-4.tif",
        README,
    ],
    "pins": 3,
    "skipped": {"no_store": 0, "missing": 1},
    "zip": True,
    "written_at": "2026-10-31T12:00:00Z",
}


class ExportRequest(BaseModel):
    """An export to write (`POST /projects/{project}/exports`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"name": "raba-2024"},
                {"name": "raba-2014", "groups": ["2014"], "zip": True},
            ]
        },
    )

    name: str = Field(
        min_length=1,
        max_length=MAX_EXPORT_NAME_CHARS,
        pattern=EXPORT_NAME_PATTERN,
        description=(
            f"The export's directory `{EXPORTS_DIR}/<name>/`: 1 to 64 letters,"
            " digits, `.`, `_` and `-`, not starting with `.`. An export of that"
            " name is replaced, with its ZIP."
        ),
    )
    groups: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            "Only these groups' pins, in the file's order of groups; left out:"
            " every group's."
        ),
    )
    zip: bool = Field(
        default=False,
        description=(
            f"Also write the folder's content as `{EXPORTS_DIR}/<name>.zip`"
            " (`GET /projects/{project}/exports/{name}/zip`); without it, an"
            " older ZIP of that name is removed."
        ),
    )


class ExportSkipped(BaseModel):
    """Pins an export left out, by why."""

    no_store: int = Field(
        description="Pins whose producer's store matches no configured store."
    )
    missing: int = Field(
        description="Pins whose version is not present (not indexed or not on disk)."
    )


class ProjectExport(BaseModel):
    """An export just written (`POST /projects/{project}/exports`)."""

    model_config = ConfigDict(json_schema_extra={"examples": [_EXPORT_EXAMPLE]})

    name: str = Field(description="The export's name.")
    path: CopyPath = Field(description="The export's directory.")
    files: list[str] = Field(
        description=(
            "The files written in it, relative to it (`/`-separated): each"
            f" category folder's files by name, `{README}` last."
        )
    )
    pins: int = Field(
        description=(
            "Versions copied: each pinned version once, though two groups pin it."
        )
    )
    skipped: ExportSkipped = Field(description="Pins left out.")
    zip: bool = Field(description=f"`{EXPORTS_DIR}/<name>.zip` was written too.")
    written_at: datetime = Field(description=f"When `{README}` was written.")

    @classmethod
    def of(
        cls, done: ProjectExportDone, settings: AppSettings, preferences: Preferences
    ) -> Self:
        """Return the answer of an export just written."""
        export = done.export
        return cls(
            name=export.name,
            path=copy_path(settings, preferences, export.path),
            files=list(export.files),
            pins=export.versions,
            skipped=ExportSkipped(no_store=done.no_store, missing=done.missing),
            zip=export.zip,
            written_at=export.written_at,
        )


class ProjectExportItem(BaseModel):
    """An export found in a project's `eksport/`."""

    name: str = Field(description="The export's name.")
    path: CopyPath = Field(description="The export's directory.")
    files: list[str] = Field(
        description=(
            "Its files, relative to it (`/`-separated): each category folder's"
            f" files by name, `{README}` last."
        )
    )
    zip: bool = Field(
        description=(
            f"`{EXPORTS_DIR}/<name>.zip` is there"
            " (`GET /projects/{project}/exports/{name}/zip`)."
        )
    )
    written_at: datetime = Field(description=f"When its `{README}` was written.")
    changed_since: bool = Field(
        description=(
            "The project file changed after the export was written: it may no"
            " longer show the pins, so write it again."
        )
    )

    @classmethod
    def of(
        cls, listing: ExportListing, settings: AppSettings, preferences: Preferences
    ) -> Self:
        """Return an export as listed."""
        return cls(
            name=listing.name,
            path=copy_path(settings, preferences, listing.path),
            files=list(listing.files),
            zip=listing.zip,
            written_at=listing.written_at,
            changed_since=listing.changed_since,
        )


class ProjectExports(BaseModel):
    """A project's exports by name (`GET /projects/{project}/exports`)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            **{
                                key: _EXPORT_EXAMPLE[key]
                                for key in (
                                    "name",
                                    "path",
                                    "files",
                                    "zip",
                                    "written_at",
                                )
                            },
                            "changed_since": True,
                        }
                    ]
                }
            ]
        }
    )

    items: list[ProjectExportItem] = Field(description="The exports, by name.")
