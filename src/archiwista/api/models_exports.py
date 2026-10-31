"""API models of a project's exports (A-ADR-049 decision 13, SPEC 8.4).

An export is the directory ``zestawy/<name>/`` of a project, generated from
its pins: ``pliki.txt`` and ``ATRYBUCJE.txt``. Its directory appears as a
copy path (``CopyPath``). The request model refuses unknown members.
"""

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.models import CopyPath, Preferences
from archiwista.api.models_owndata import copy_path
from archiwista.config import AppSettings
from archiwista.projects import EXPORTS_DIR
from archiwista.projects.exports import (
    EXPORT_FILES,
    EXPORT_NAME_PATTERN,
    FILES_LIST,
    MAX_EXPORT_NAME_CHARS,
    ExportListing,
)
from archiwista.services.projects import ProjectExportDone

_PATH_EXAMPLE: dict[str, Any] = {
    "local": f"/mnt/nas/projekty/raba/{EXPORTS_DIR}/hydrograf",
    "aliases": [f"P:\\raba\\{EXPORTS_DIR}\\hydrograf"],
    "personal": None,
}
_EXPORT_EXAMPLE: dict[str, Any] = {
    "name": "hydrograf",
    "path": _PATH_EXAMPLE,
    "files": list(EXPORT_FILES),
    "pins": 12,
    "skipped": {"no_store": 0, "missing": 1},
    "written_at": "2026-10-31T12:00:00Z",
}


class ExportRequest(BaseModel):
    """An export to write (`POST /projects/{project}/exports`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"name": "hydrograf"},
                {"name": "nmt-2024", "groups": ["teren"]},
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
            " name is written again."
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
    files: list[str] = Field(description="The files written in it.")
    pins: int = Field(
        description=(
            f"Versions listed in `{FILES_LIST}`: each pinned version once, though"
            " two groups pin it."
        )
    )
    skipped: ExportSkipped = Field(description="Pins left out.")
    written_at: datetime = Field(description=f"When `{FILES_LIST}` was written.")

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
            written_at=export.written_at,
        )


class ProjectExportItem(BaseModel):
    """An export found in a project's `zestawy/`."""

    name: str = Field(description="The export's name.")
    path: CopyPath = Field(description="The export's directory.")
    files: list[str] = Field(description="Its files Archiwista writes.")
    written_at: datetime = Field(description="When its newest file was written.")
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
                                for key in ("name", "path", "files", "written_at")
                            },
                            "changed_since": True,
                        }
                    ]
                }
            ]
        }
    )

    items: list[ProjectExportItem] = Field(description="The exports, by name.")
